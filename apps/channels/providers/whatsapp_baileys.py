"""Transport adapter for the separately supervised WhatsApp Web gateway.

This is deliberately distinct from the official WhatsApp Cloud API adapter.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
import uuid
from typing import Any

from django.conf import settings

from apps.channels.capabilities import capabilities_for
from apps.channels.downgrade import downgrade
from apps.channels.events import NormalizedEvent, OutboundMessage, SendResult, SendStatus
from apps.channels.models import BaileysSession, ChannelConnection, ConnectionStatus
from apps.channels.providers.base import Adapter, request_json
from apps.channels.providers.exceptions import APIError
from apps.common.platforms import Platform

logger = logging.getLogger(__name__)
_CAPABILITIES = capabilities_for(Platform.WHATSAPP_BAILEYS)


def _signed_request(method: str, path: str, body: bytes = b"") -> dict[str, str]:
    key_text = os.environ.get("BAILEYS_DJANGO_TO_GATEWAY_HMAC_KEY", "")
    try:
        key = base64.b64decode(key_text, validate=True)
    except (ValueError, base64.binascii.Error):
        key = b""
    if len(key) != 32 or base64.b64encode(key).decode() != key_text:
        raise APIError("Baileys gateway is not configured.", status_code=503, code="gateway_unavailable")
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    canonical = b"\n".join((method.encode(), path.encode(), timestamp.encode(), nonce.encode(), body))
    signature = hmac.new(key, canonical, hashlib.sha256).hexdigest()
    return {
        "X-Baileys-Timestamp": timestamp,
        "X-Baileys-Nonce": nonce,
        "X-Baileys-Signature": signature,
    }


def gateway_request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Make one signed call to the configured private service, without redirects."""
    base = str(getattr(settings, "BAILEYS_GATEWAY_URL", "") or os.environ.get("BAILEYS_GATEWAY_URL", "")).rstrip("/")
    if not base.startswith("http://") and not base.startswith("https://"):
        raise APIError("Baileys gateway is not configured.", status_code=503, code="gateway_unavailable")
    body = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else b""
    headers = _signed_request(method, path, body)
    headers["Content-Type"] = "application/json"
    try:
        return request_json(
            method,
            f"{base}{path}",
            content=body or None,
            headers=headers,
            timeout=4.0,
            follow_redirects=False,
        )
    except APIError:
        logger.warning("Baileys gateway request failed (%s %s).", method, path)
        raise APIError("Baileys gateway is unavailable.", status_code=503, code="gateway_unavailable") from None


def _is_supported_recipient_jid(recipient: str) -> bool:
    return re.fullmatch(r"[0-9]{5,20}@(s\.whatsapp\.net|lid)", recipient) is not None


class WhatsAppBaileysAdapter(Adapter):
    platform = Platform.WHATSAPP_BAILEYS.value
    capabilities = _CAPABILITIES
    webhook_content = "json"

    def verify_webhook(self, request: Any, connection: ChannelConnection) -> bool:
        # Gateway callbacks use a separate bilateral HMAC endpoint, never this public adapter hook.
        return False

    def parse_events(self, request: Any, connection: ChannelConnection) -> list[NormalizedEvent]:
        return []

    def send(self, connection: ChannelConnection, identity: Any, outbound: OutboundMessage) -> SendResult:
        if connection.platform != self.platform or connection.status != ConnectionStatus.ACTIVE:
            raise APIError("This channel is not available for sending.", status_code=409, code="channel_unavailable")
        if not BaileysSession.objects.filter(connection=connection, state="connected").exists():
            raise APIError("The linked WhatsApp session is not connected.", status_code=409, code="session_disconnected")
        if outbound.template_ref:
            raise APIError("WhatsApp templates are supported only by the Cloud API channel.", status_code=400, code="template_unsupported")
        recipient = str(getattr(identity, "platform_user_id", ""))
        if not _is_supported_recipient_jid(recipient):
            raise APIError("This gateway version can send only to verified WhatsApp user JIDs.", status_code=400, code="recipient_unsupported")
        rendered = downgrade(outbound, self.capabilities)
        if len(rendered.messages) != 1:
            raise APIError("This gateway version cannot split one reply into multiple sends.", status_code=400, code="message_unsupported")
        message = rendered.messages[0]
        body = message.to_body()
        if any(block.get("type") != "text" for block in body["blocks"]):
            raise APIError("This gateway version supports text messages only.", status_code=400, code="media_unsupported")
        text = "\n".join(block.get("text", "") for block in body["blocks"] if isinstance(block.get("text"), str))
        if not text:
            raise APIError("Empty messages are not supported.", status_code=400, code="message_unsupported")
        try:
            command_id = str(uuid.UUID(outbound.command_id))
        except (ValueError, AttributeError):
            command_id = str(uuid.uuid4())
        result = gateway_request("POST", f"/v1/sessions/{connection.pk}/send", {
            "command_id": command_id, "jid": recipient, "text": text,
        })
        state = result.get("state")
        if state == "sent" and isinstance(result.get("provider_message_id"), str):
            return SendResult(SendStatus.SENT, provider_message_id=result["provider_message_id"][:200])
        if state == "unknown":
            raise APIError("WhatsApp send outcome is pending confirmation.", status_code=503, code="send_unknown")
        error = result.get("error")
        code = error if error in {"rate_limited", "session_disconnected", "recipient_unavailable", "unsupported_media"} else "send_failed"
        return SendResult(SendStatus.FAILED, error=code)
    def on_disconnect(self, connection: ChannelConnection) -> None:
        gateway_request(
            "POST",
            f"/v1/sessions/{connection.pk}/logout",
            {"request_id": str(uuid.uuid4())},
        )


from apps.channels.registry import register_adapter  # noqa: E402

register_adapter(Platform.WHATSAPP_BAILEYS, WhatsAppBaileysAdapter)
