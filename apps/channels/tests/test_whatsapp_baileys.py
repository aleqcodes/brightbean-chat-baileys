"""Regression coverage for the separate Baileys channel and private callback."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from apps.channels.capabilities import capabilities_for
from apps.channels.models import BaileysSession, ChannelConnection, ConnectionStatus
from apps.channels.policy import policy_for
from apps.common.platforms import Platform
from apps.members.roles import WorkspaceRole
from tests.support import Tenancy, make_connection

pytestmark = pytest.mark.django_db


def _url(tenancy: Tenancy, name: str, **kwargs: Any) -> str:
    return reverse(f"channels:{name}", kwargs={"workspace_id": tenancy.workspace.pk, **kwargs})


def _signed_callback(
    client: Client,
    connection: ChannelConnection,
    *,
    nonce: str | None = None,
    valid_signature: bool = True,
    payload: dict[str, Any] | None = None,
) -> Any:
    key = bytes(range(32))
    timestamp = str(int(time.time()))
    nonce = nonce or uuid.uuid4().hex
    body = json.dumps(
        {
            "schema_version": 1,
            "event_id": str(uuid.uuid4()),
            "connection_id": str(connection.pk),
            "session_generation": 1,
            "occurred_at": "2026-10-22T12:00:00Z",
            "type": "connection.update",
            "payload": payload or {"state": "connected", "account_jid": "15551234567@s.whatsapp.net"},
        },
        separators=(",", ":"),
    ).encode()
    path = "/internal/baileys/events/"
    canonical = b"\n".join((b"POST", path.encode(), timestamp.encode(), nonce.encode(), body))
    signature = hmac.new(key, canonical, hashlib.sha256).hexdigest() if valid_signature else "0" * 64
    return client.post(
        path,
        data=body,
        content_type="application/json",
        HTTP_X_BAILEYS_TIMESTAMP=timestamp,
        HTTP_X_BAILEYS_NONCE=nonce,
        HTTP_X_BAILEYS_SIGNATURE=signature,
    )


class TestBaileysRegistry:
    def test_baileys_is_separate_and_conservative(self) -> None:
        policy = policy_for(Platform.WHATSAPP_BAILEYS)
        caps = capabilities_for(Platform.WHATSAPP_BAILEYS)
        cloud_policy = policy_for(Platform.WHATSAPP)
        assert policy.window_hours == 24
        assert policy.outside_window == "blocked"
        assert policy.broadcast_allowed is False
        assert policy.rate_default == 1.0
        assert caps.proactive_send is False and caps.broadcast_allowed is False
        assert not any((caps.image, caps.audio, caps.video, caps.file))
        assert cloud_policy.outside_window == "needs_template"
        assert cloud_policy.broadcast_allowed is True




def test_gateway_request_signs_the_exact_private_request(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.channels.providers import whatsapp_baileys

    key = bytes(range(32))
    monkeypatch.setenv("BAILEYS_DJANGO_TO_GATEWAY_HMAC_KEY", base64.b64encode(key).decode())
    monkeypatch.setattr(whatsapp_baileys.settings, "BAILEYS_GATEWAY_URL", "http://baileys-gateway:3100", raising=False)
    sent: dict[str, Any] = {}

    def capture(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        sent.update(method=method, url=url, **kwargs)
        return {"state": "accepted"}

    monkeypatch.setattr(whatsapp_baileys, "request_json", capture)

    response = whatsapp_baileys.gateway_request("POST", "/v1/sessions/abc/send", {"text": "hello"})

    headers = sent["headers"]
    canonical = b"\n".join(
        (
            b"POST",
            b"/v1/sessions/abc/send",
            headers["X-Baileys-Timestamp"].encode(),
            headers["X-Baileys-Nonce"].encode(),
            sent["content"],
        )
    )
    expected = hmac.new(key, canonical, hashlib.sha256).hexdigest()
    assert response == {"state": "accepted"}
    assert sent["url"] == "http://baileys-gateway:3100/v1/sessions/abc/send"
    assert headers["X-Baileys-Signature"] == expected
    assert json.loads(sent["content"]) == {"text": "hello"}
    assert sent["follow_redirects"] is False


class TestBaileysConnect:
    def test_risk_ack_is_required_before_a_pending_connection_is_created(self, client: Client, tenancy: Tenancy) -> None:
        client.force_login(tenancy.user_for(WorkspaceRole.ADMIN))
        response = client.post(_url(tenancy, "whatsapp_baileys_connect"), {"display_name": "Support"})
        assert response.status_code == 200
        assert not ChannelConnection.objects.for_workspace(tenancy.workspace).filter(
            platform=Platform.WHATSAPP_BAILEYS
        ).exists()

    def test_explicit_risk_ack_creates_disabled_pending_row_and_session(self, client: Client, tenancy: Tenancy) -> None:
        client.force_login(tenancy.user_for(WorkspaceRole.ADMIN))
        response = client.post(
            _url(tenancy, "whatsapp_baileys_connect"),
            {"display_name": "Support", "accept_risk": "yes"},
        )
        assert response.status_code == 302
        connection = ChannelConnection.objects.for_workspace(tenancy.workspace).get(platform=Platform.WHATSAPP_BAILEYS)
        assert connection.external_id.startswith("pending:")
        assert connection.status == ConnectionStatus.DISABLED
        session = BaileysSession.objects.get(connection=connection)
        assert session.state == "pending_pairing"
        assert session.risk_accepted_at is not None

    def test_non_admin_cannot_poll_pairing_state(self, client: Client, tenancy: Tenancy) -> None:
        connection = make_connection(
            tenancy.workspace,
            platform=Platform.WHATSAPP_BAILEYS,
            external_id=f"pending:{uuid.uuid4()}",
            status=ConnectionStatus.DISABLED,
        )
        BaileysSession.objects.create(connection=connection)
        client.force_login(tenancy.user_for(WorkspaceRole.EDITOR))
        response = client.get(_url(tenancy, "whatsapp_baileys_status", connection_id=connection.pk))
        assert response.status_code == 403

    def test_generic_enable_cannot_fake_a_linked_session(self, client: Client, tenancy: Tenancy) -> None:
        connection = make_connection(
            tenancy.workspace,
            platform=Platform.WHATSAPP_BAILEYS,
            external_id=f"pending:{uuid.uuid4()}",
            status=ConnectionStatus.DISABLED,
        )
        BaileysSession.objects.create(connection=connection)
        client.force_login(tenancy.user_for(WorkspaceRole.ADMIN))
        response = client.post(
            _url(tenancy, "set_status", connection_id=connection.pk),
            {"status": ConnectionStatus.ACTIVE},
        )
        connection.refresh_from_db()
        assert response.status_code == 302
        assert connection.status == ConnectionStatus.DISABLED


class TestBaileysInternalCallback:
    def test_signed_connected_transition_binds_number_and_replay_is_rejected(
        self, client: Client, tenancy: Tenancy, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        key = base64.b64encode(bytes(range(32))).decode()
        monkeypatch.setenv("BAILEYS_GATEWAY_TO_DJANGO_HMAC_KEY", key)
        connection = make_connection(
            tenancy.workspace,
            platform=Platform.WHATSAPP_BAILEYS,
            external_id=f"pending:{uuid.uuid4()}",
            status=ConnectionStatus.DISABLED,
        )
        BaileysSession.objects.create(connection=connection)
        nonce = uuid.uuid4().hex
        response = _signed_callback(client, connection, nonce=nonce)
        assert response.status_code == 200
        connection.refresh_from_db()
        session = BaileysSession.objects.get(connection=connection)
        assert connection.external_id == "+15551234567"
        assert connection.status == ConnectionStatus.ACTIVE
        assert session.state == "connected"
        assert _signed_callback(client, connection, nonce=nonce).status_code == 403

    def test_invalid_signature_cannot_change_session_state(
        self, client: Client, tenancy: Tenancy, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BAILEYS_GATEWAY_TO_DJANGO_HMAC_KEY", base64.b64encode(bytes(range(32))).decode())
        connection = make_connection(
            tenancy.workspace,
            platform=Platform.WHATSAPP_BAILEYS,
            external_id=f"pending:{uuid.uuid4()}",
            status=ConnectionStatus.DISABLED,
        )
        session = BaileysSession.objects.create(connection=connection)
        response = _signed_callback(client, connection, valid_signature=False)
        assert response.status_code == 403
        connection.refresh_from_db()
        session.refresh_from_db()
        assert connection.status == ConnectionStatus.DISABLED
        assert session.state == "pending_pairing"
