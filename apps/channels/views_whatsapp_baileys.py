"""Workspace-protected pairing and status views for WhatsApp (Baileys)."""
from __future__ import annotations

import logging
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.channels.models import BaileysSession, ChannelConnection, ConnectionStatus
from apps.channels.plan import plan_refusal
from apps.channels.providers.exceptions import APIError
from apps.channels.providers.whatsapp_baileys import gateway_request
from apps.common.platforms import Platform
from apps.members.decorators import require_permission
from apps.members.requests import WorkspaceRequest

logger = logging.getLogger(__name__)

RISK_NOTICE = (
    "Baileys is an unofficial WhatsApp Web client, not authorized by Meta. "
    "It may stop working or cause this number to be restricted or suspended. "
    "No availability or anti-blocking guarantee is made."
)


def _owned(workspace_id: str, connection_id: str) -> ChannelConnection:
    connection = ChannelConnection.objects.for_workspace(workspace_id).filter(
        pk=connection_id, platform=Platform.WHATSAPP_BAILEYS.value
    ).first()
    if connection is None:
        raise Http404
    return connection


@login_required
@require_permission("manage_channels")
def whatsapp_baileys_connect(request: WorkspaceRequest, workspace_id: str) -> HttpResponse:
    """Create a disabled provisional connection; explicit pairing follows."""
    if request.method == "POST":
        name = (request.POST.get("display_name") or "WhatsApp (Baileys)").strip()[:200]
        if request.POST.get("accept_risk") != "yes":
            messages.error(request, "You must acknowledge the unofficial-channel risks before connecting.")
        elif refusal := plan_refusal(request.workspace):
            messages.error(request, refusal)
        else:
            connection = ChannelConnection(
                workspace=request.workspace,
                platform=Platform.WHATSAPP_BAILEYS.value,
                display_name=name or "WhatsApp (Baileys)",
                external_id=f"pending:{uuid.uuid4()}",
                status=ConnectionStatus.DISABLED,
            )
            try:
                with transaction.atomic():
                    connection.save()
                    BaileysSession.objects.create(connection=connection, risk_accepted_at=timezone.now())
            except IntegrityError:
                messages.error(request, "Could not create this channel. Please retry.")
            else:
                return redirect("channels:whatsapp_baileys_detail", workspace_id=workspace_id, connection_id=connection.pk)
    return render(request, "channels/whatsapp_baileys_connect.html", {
        "risk_notice": RISK_NOTICE,
        "list_url": reverse("channels:list", kwargs={"workspace_id": workspace_id}),
    })


@login_required
@require_permission("manage_channels")
@require_GET
def whatsapp_baileys_detail(request: WorkspaceRequest, workspace_id: str, connection_id: str) -> HttpResponse:
    connection = _owned(workspace_id, connection_id)
    session, _ = BaileysSession.objects.get_or_create(connection=connection)
    return render(request, "channels/whatsapp_baileys_detail.html", {
        "connection": connection,
        "session": session,
        "risk_notice": RISK_NOTICE,
        "pair_url": reverse("channels:whatsapp_baileys_pair", kwargs={"workspace_id": workspace_id, "connection_id": connection.pk}),
        "status_url": reverse("channels:whatsapp_baileys_status", kwargs={"workspace_id": workspace_id, "connection_id": connection.pk}),
        "qr_url": reverse("channels:whatsapp_baileys_qr", kwargs={"workspace_id": workspace_id, "connection_id": connection.pk}),
        "logout_url": reverse("channels:whatsapp_baileys_logout", kwargs={"workspace_id": workspace_id, "connection_id": connection.pk}),
        "list_url": reverse("channels:list", kwargs={"workspace_id": workspace_id}),
    })

@login_required
@require_permission("manage_channels")
@require_POST
def whatsapp_baileys_pair(request: WorkspaceRequest, workspace_id: str, connection_id: str) -> HttpResponse:
    connection = _owned(workspace_id, connection_id)
    session, _ = BaileysSession.objects.get_or_create(connection=connection)
    try:
        gateway_request("POST", f"/v1/sessions/{connection.pk}/pair", {"request_id": str(uuid.uuid4())})
    except APIError:
        messages.error(request, "Baileys gateway is unavailable; the connection remains unpaired.")
    else:
        session.state = "connecting"
        session.save(update_fields=["state", "updated_at"])
        messages.success(request, "Pairing started. Scan the current QR code with WhatsApp linked devices.")
    return redirect("channels:whatsapp_baileys_detail", workspace_id=workspace_id, connection_id=connection.pk)


@login_required
@require_permission("manage_channels")
@require_GET
def whatsapp_baileys_status(request: WorkspaceRequest, workspace_id: str, connection_id: str) -> HttpResponse:
    connection = _owned(workspace_id, connection_id)
    session, _ = BaileysSession.objects.get_or_create(connection=connection)
    try:
        live = gateway_request("GET", f"/v1/sessions/{connection.pk}/status")
    except APIError:
        live = {}
    status_data = {
        "state": live.get("state", session.state),
        "connection_status": connection.status,
        "generation": live.get("session_generation", session.session_generation),
        "pairing_expires_at": live.get("expires_at") or (session.pairing_expires_at.isoformat() if session.pairing_expires_at else None),
        "last_connected_at": session.last_connected_at.isoformat() if session.last_connected_at else None,
        "last_error_code": live.get("error_code", session.last_error_code),
        "gateway_available": bool(live),
    }
    if request.headers.get("HX-Request") == "true":
        return render(request, "channels/_whatsapp_baileys_status.html", {
            "status_data": status_data,
            "connection": connection,
            "status_url": reverse("channels:whatsapp_baileys_status", kwargs={"workspace_id": workspace_id, "connection_id": connection.pk}),
        })
    response = JsonResponse(status_data)
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_permission("manage_channels")
@require_GET
def whatsapp_baileys_qr(request: WorkspaceRequest, workspace_id: str, connection_id: str) -> HttpResponse:
    connection = _owned(workspace_id, connection_id)
    try:
        result = gateway_request("GET", f"/v1/sessions/{connection.pk}/qr")
    except APIError:
        return JsonResponse({"error": "gateway_unavailable"}, status=503, headers={"Cache-Control": "no-store"})
    if request.headers.get("HX-Request") == "true":
        qr = result.get("qr")
        if not isinstance(qr, str) or not qr.startswith("data:image/png;base64,"):
            qr = ""
        response = render(request, "channels/_whatsapp_baileys_qr.html", {
            "qr": qr,
            "expires_at": result.get("expires_at"),
            "connection": connection,
            "qr_url": reverse("channels:whatsapp_baileys_qr", kwargs={"workspace_id": workspace_id, "connection_id": connection.pk}),
        })
        response["Cache-Control"] = "no-store, private"
        response["Pragma"] = "no-cache"
        return response
    response = JsonResponse({"qr": result.get("qr"), "expires_at": result.get("expires_at")})
    response["Cache-Control"] = "no-store, private"
    response["Pragma"] = "no-cache"
    return response


@login_required
@require_permission("manage_channels")
@require_POST
def whatsapp_baileys_logout(request: WorkspaceRequest, workspace_id: str, connection_id: str) -> HttpResponse:
    connection = _owned(workspace_id, connection_id)
    try:
        gateway_request("POST", f"/v1/sessions/{connection.pk}/logout", {"request_id": str(uuid.uuid4())})
    except APIError:
        messages.error(request, "Gateway is unavailable; logout could not be confirmed.")
    else:
        connection.status = ConnectionStatus.NEEDS_REAUTH
        connection.save(update_fields=["status"])
        session = BaileysSession.objects.filter(connection=connection).first()
        if session:
            session.state = "logged_out"
            session.save(update_fields=["state", "updated_at"])
        messages.success(request, "Session closed. Pair again to reconnect; stored conversations were retained.")
    return redirect("channels:whatsapp_baileys_detail", workspace_id=workspace_id, connection_id=connection.pk)
