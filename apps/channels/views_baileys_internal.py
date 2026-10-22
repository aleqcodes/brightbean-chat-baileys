"""Private gateway callback: bilateral HMAC, anti-replay, and shared ingest path."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.core.exceptions import RequestDataTooBig
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.channels.events import EventPayload, EventType, NormalizedEvent
from apps.channels.models import BaileysRequestNonce, BaileysSession, ChannelConnection, ConnectionStatus
from apps.channels.registry import adapter_for
from apps.common.platforms import Platform

logger = logging.getLogger(__name__)


MAX_BODY_BYTES = 256 * 1024
MAX_CLOCK_SKEW_SECONDS = 300


def _signature_matches(request: HttpRequest, body: bytes) -> bool:
    key_text = os.environ.get("BAILEYS_GATEWAY_TO_DJANGO_HMAC_KEY", "")
    timestamp = request.headers.get("X-Baileys-Timestamp", "")
    nonce = request.headers.get("X-Baileys-Nonce", "")
    presented = request.headers.get("X-Baileys-Signature", "")
    if len(timestamp) not in {10, 13} or not timestamp.isdigit() or not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", nonce):
        return False
    try:
        key = base64.b64decode(key_text, validate=True)
    except (ValueError, base64.binascii.Error):
        return False
    if len(key) != 32 or base64.b64encode(key).decode() != key_text:
        return False
    timestamp_seconds = int(timestamp) / (1000 if len(timestamp) == 13 else 1)
    if abs(time.time() - timestamp_seconds) > MAX_CLOCK_SKEW_SECONDS:
        return False
    canonical = b"\n".join((request.method.encode(), request.path.encode(), timestamp.encode(), nonce.encode(), body))
    expected = hmac.new(key, canonical, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, presented)


def _accepted_nonce(nonce: str) -> bool:
    try:
        with transaction.atomic():
            BaileysRequestNonce.objects.filter(created_at__lt=timezone.now() - timedelta(minutes=10)).delete()
            BaileysRequestNonce.objects.create(nonce=nonce)
    except IntegrityError:
        return False
    return True


@csrf_exempt
@require_POST
def baileys_internal_event(request: HttpRequest) -> HttpResponse:
    if request.content_type != "application/json":
        return HttpResponse("Bad request", status=400)
    length = request.META.get("CONTENT_LENGTH", "")
    if length.isdigit() and int(length) > MAX_BODY_BYTES:
        return HttpResponse("Payload too large", status=413)
    try:
        raw = request.body
    except RequestDataTooBig:
        return HttpResponse("Payload too large", status=413)
    if len(raw) > MAX_BODY_BYTES:
        return HttpResponse("Payload too large", status=413)
    if not _signature_matches(request, raw):
        return HttpResponse("Forbidden", status=403)
    nonce = request.headers.get("X-Baileys-Nonce", "")
    if not _accepted_nonce(nonce):
        return HttpResponse("Forbidden", status=403)
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return HttpResponse("Bad request", status=400)
    if not isinstance(data, dict) or set(data) != {
        "schema_version", "event_id", "connection_id", "session_generation", "occurred_at", "type", "payload"
    }:
        return HttpResponse("Bad request", status=400)
    if data.get("schema_version") != 1 or not isinstance(data.get("event_id"), str) or not 1 <= len(data["event_id"]) <= 200:
        return HttpResponse("Bad request", status=400)
    try:
        connection_id = UUID(data.get("connection_id", ""))
        connection = ChannelConnection.objects.unscoped().get(pk=connection_id, platform=Platform.WHATSAPP_BAILEYS.value)
    except (ValueError, TypeError, ChannelConnection.DoesNotExist):
        return HttpResponse("Forbidden", status=403)
    payload = data.get("payload")
    generation = data.get("session_generation")
    event_type = data.get("type")
    if connection.status == ConnectionStatus.DISABLED and event_type != "connection.update":
        return HttpResponse("Forbidden", status=403)
    if not isinstance(payload, dict) or not isinstance(generation, int) or generation < 0:
        return HttpResponse("Bad request", status=400)
    session, _ = BaileysSession.objects.get_or_create(connection=connection)
    if generation < session.session_generation:
        return JsonResponse({"status": "stale"})
    if event_type == "connection.update":
        return _connection_update(connection, session, generation, payload)
    if event_type not in {"message.upsert", "message.receipt"}:
        return JsonResponse({"status": "ignored"})
    if generation != session.session_generation or session.state != "connected" or connection.status != ConnectionStatus.ACTIVE:
        return JsonResponse({"status": "not_ready"})
    event = _normalized_event(connection, data, payload)
    if event is None:
        return JsonResponse({"status": "ignored"})
    from apps.channels.views_webhooks import record_events

    record_events(connection, [event], adapter_for(Platform.WHATSAPP_BAILEYS))
    return JsonResponse({"status": "persisted"})


def _connection_update(connection: ChannelConnection, session: BaileysSession, generation: int, payload: dict[str, Any]) -> JsonResponse:
    state = payload.get("state")
    allowed = {"pending_pairing", "qr_ready", "connecting", "connected", "reconnecting", "logged_out", "needs_reauth", "error"}
    if not isinstance(state, str) or state not in allowed:
        return JsonResponse({"status": "ignored"})
    with transaction.atomic():
        session = BaileysSession.objects.select_for_update().get(pk=session.pk)
        # The bilaterally signed gateway callback resolved this exact connection.
        connection = ChannelConnection.objects.unscoped().select_for_update().get(pk=connection.pk)
        if generation < session.session_generation:
            return JsonResponse({"status": "stale"})
        if connection.status == ConnectionStatus.DISABLED and session.state == "disabled" and state == "connected":
            return JsonResponse({"status": "stale"})
        session.session_generation = generation
        session.state = state
        session.last_error_code = str(payload.get("error_code", ""))[:64] if state == "error" else ""
        if state == "connected":
            jid = payload.get("account_jid")
            if not isinstance(jid, str) or not jid.endswith("@s.whatsapp.net"):
                session.state = "needs_reauth"
                session.last_error_code = "invalid_account_identity"
                connection.status = ConnectionStatus.NEEDS_REAUTH
            else:
                digits = jid.removesuffix("@s.whatsapp.net").split(":", 1)[0]
                if not digits.isdigit() or not 7 <= len(digits) <= 15:
                    session.state = "needs_reauth"
                    session.last_error_code = "invalid_account_identity"
                    connection.status = ConnectionStatus.NEEDS_REAUTH
                else:
                    connection.external_id = f"+{digits}"
                    connection.status = ConnectionStatus.ACTIVE
                    session.last_connected_at = timezone.now()
        elif state in {"logged_out", "needs_reauth"}:
            connection.status = ConnectionStatus.NEEDS_REAUTH
            session.last_disconnected_at = timezone.now()
        elif state == "disabled":
            connection.status = ConnectionStatus.DISABLED
        try:
            with transaction.atomic():
                connection.save(update_fields=["external_id", "status"])
        except IntegrityError:
            session.state = "needs_reauth"
            session.last_error_code = "account_already_linked"
            session.last_disconnected_at = timezone.now()
            session.save()
            connection.status = ConnectionStatus.NEEDS_REAUTH
            connection.save(update_fields=["status"])
            try:
                from apps.channels.providers.whatsapp_baileys import gateway_request

                gateway_request("POST", f"/v1/sessions/{connection.pk}/logout", {"request_id": str(UUID(int=0))})
            except Exception:
                logger.warning("Baileys duplicate-account logout failed.")
            return JsonResponse({"status": "rejected"})
        session.save()
    return JsonResponse({"status": "persisted"})


def _normalized_event(connection: ChannelConnection, data: dict[str, Any], payload: dict[str, Any]) -> NormalizedEvent | None:
    jid = payload.get("chat_jid")
    message_id = payload.get("message_id")
    if not isinstance(jid, str) or len(jid) > 200 or not (
        jid.endswith("@s.whatsapp.net") or jid.endswith("@lid")
    ):
        return None
    if not isinstance(message_id, str) or not message_id or len(message_id) > 200:
        return None
    safe_raw = {"type": data["type"], "schema_version": 1}
    try:
        timestamp = datetime.fromisoformat(data.get("occurred_at", "").replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            return None
    except (ValueError, AttributeError):
        timestamp = timezone.now()
    if data["type"] == "message.upsert":
        if payload.get("from_me") is not False:
            return None
        content = payload.get("content")
        if not isinstance(content, dict):
            return None
        kind = content.get("kind")
        if kind == "text" and isinstance(content.get("text"), str):
            text = content["text"][:16_000]
            event_payload = EventPayload(text=text)
            safe_raw["kind"] = "text"
            return NormalizedEvent(EventType.MESSAGE, connection, jid, f"baileys:{data['event_id']}", timestamp, event_payload, safe_raw)
        if kind in {"image", "video", "audio", "document"} and isinstance(content.get("media_id"), str):
            media_kind = "file" if kind == "document" else kind
            caption = content.get("caption", "")
            event_payload = EventPayload(
                text=caption[:16_000] if isinstance(caption, str) else "",
                media_ids=(content["media_id"][:200],),
                media_kinds=(media_kind,),
            )
            safe_raw["kind"] = media_kind
            return NormalizedEvent(EventType.MESSAGE, connection, jid, f"baileys:{data['event_id']}", timestamp, event_payload, safe_raw)
        return None
    status = payload.get("status")
    if status not in {"sent", "delivered", "read"}:
        return None
    safe_raw["status"] = status
    return NormalizedEvent(
        EventType.DELIVERY_STATUS,
        connection,
        jid,
        f"baileys:{data['event_id']}",
        timestamp,
        EventPayload(extra={"message_id": message_id, "status": status}),
        safe_raw,
    )
