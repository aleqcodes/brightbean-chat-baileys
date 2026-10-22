# Baileys gateway

Private Node 24 service for the separately authenticated Django transport. It is a single replica: do not scale horizontally or share its state volume between writers. The gateway binds only inside the Compose network; Compose has no published gateway port.

## Configuration and deployment

Production requires three independent base64-encoded 32-byte secrets: `BAILEYS_SESSION_MASTER_KEY`, `BAILEYS_DJANGO_TO_GATEWAY_HMAC_KEY`, and `BAILEYS_GATEWAY_TO_DJANGO_HMAC_KEY`. Generate each independently with `openssl rand -base64 32`. Keep them in the deployment secret manager. `BAILEYS_GATEWAY_URL` is the private service URL consumed by Django; `DJANGO_INTERNAL_BASE_URL` is the fixed callback origin, never tenant supplied. `BAILEYS_STATE_DIR` holds encrypted session records and operational journals; preserve the named volume across upgrades and restrict access to the gateway uid.

Start using `docker compose -f docker-compose.prod.yml up -d --build`. Back up the state volume only as encrypted opaque files. Restore the same master key before restoring the volume. To rotate the master key, stop the gateway, decrypt/re-encrypt every auth record with a one-time offline migration using old and new keys, verify recovery, then deploy the new key; changing the key in place makes records unreadable. Logout removes the per-connection auth record. Outbox and command journals are retained as operational data.

## Protocol

Every private request, including GET, is signed over exact UTF-8/byte sequence `METHOD\nPATH\nTIMESTAMP\nNONCE\nBODY` with HMAC-SHA256. Header names are `X-Baileys-Timestamp`, `X-Baileys-Nonce`, and `X-Baileys-Signature` (hex digest). Timestamps accept seconds or milliseconds within five minutes; nonce use is persisted. Callback uses the independent reverse-direction key. JSON command schemas reject unknown keys; QR and status responses are `no-store`. `/readyz` indicates service readiness and intentionally says nothing about handset connectivity.

Routes are `/v1/sessions/{connectionId}/pair`, `/status`, `/qr`, `/send`, `/logout`, and `/disable`. The QR response contains a `data:image/png;base64,...` data URI and `expires_at`; it is memory-only and expires. A successful connection callback includes Baileys' account JID (device suffix removed) for Django-side canonical identity binding. Send accepts individual phone-number JIDs and LIDs, with text only. Inbound translation accepts newly notified 1:1 text and media messages only; groups, statuses, history batches, from-me, protocol and unsupported payloads are ignored. The current event callback schema deliberately does not claim Django-side ingest is configured until its signed callback endpoint is deployed.

## Security and implementation boundaries

Baileys is an unofficial WhatsApp Web client. WhatsApp may change or restrict it; linking a number carries account risk. The gateway does not implement campaigns, groups, broadcast, contact scraping, arbitrary media URL fetches, or anti-ban behavior. Media metadata is translated but media bytes are not yet transferred. It does not provide cross-workspace number ownership enforcement or a Django operator UI by itself. Unknown send results are journaled as `unknown` and never blindly retried. Baileys 7.0.0-rc14 is pinned (MIT license); audit the full transitive tree separately before distribution. No phone-based E2E has been performed.
