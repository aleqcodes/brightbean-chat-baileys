# WhatsApp (Baileys)

WhatsApp (Baileys) is a separate, unofficial WhatsApp Web channel. It does not replace the official WhatsApp Cloud API channel or its approved templates. Baileys is not authorized by Meta; WhatsApp may change its protocol, stop the integration, restrict or suspend the linked number. There is no availability or anti-blocking guarantee. Do not use it for spam, unsolicited messages, contact scraping, number rotation, or bulk campaigns.

## Current support

- QR linking from workspace channel settings; the QR is served only to authenticated `manage_channels` users and has `Cache-Control: no-store`.
- One persistent linked-device session per connection, encrypted at rest by the gateway, with session state kept separate from Django's channel status.
- New 1:1 incoming text messages are normalized through the existing channel event log and messaging ingest pipeline. Historical sync, groups, broadcasts/statuses, newsletters, and messages sent by the linked account are ignored.
- 1:1 text sends go through the existing opt-in, opt-out, 24-hour product window, and message retry pipeline. Outside the product window, messages are blocked. This 24-hour rule is a conservative product choice, not a claim about WhatsApp Web's technical requirements.
- Flow quick replies are rendered as numbered text options instead of tappable controls. Contacts can answer with the number or visible label, and either response follows the matching flow branch.
- Cloud API templates, broadcasts, and campaigns are disabled for Baileys.

**Not yet supported:** inbound or outbound media transfer, delivery/read receipts, group chats, campaigns, multi-part send reconciliation, and real-device E2E verification. Text replies support phone-number JIDs and direct LID JIDs; the gateway does not attempt to reverse-resolve an LID to a phone number. Unsupported events are ignored; sends are not reported as delivered. An ambiguous gateway send remains retry-protected by the persisted Django message UUID and gateway command journal, but the UI has no separate `unknown` status.

## Architecture and trust boundaries

Django remains authoritative for workspace ownership, permissions, opt-in/compliance, identities, messages, and flow/inbox processing. `services/baileys-gateway` is a separate Node 24 + TypeScript process that owns Baileys sockets and AES-256-GCM-encrypted auth state. PostgreSQL stores no QR or Baileys keys. The gateway is private on the Compose network; no gateway port is published. Django-to-gateway commands and gateway-to-Django callbacks use independent 32-byte base64 HMAC keys, timestamps, and replay-resistant nonces. The callback reuses `WebhookEventLog` deduplication and `record_events`.

Baileys is pinned to `@whiskeysockets/baileys` **7.0.0-rc14** (MIT; see the gateway lockfile metadata). The v7 release candidate is required for native LID-addressed sends and updates the bundled WhatsApp Web client revision used during pairing. The gateway's encrypted auth store persists the additional v7 Signal keys. The BrightBean fork remains AGPL-3.0. Review the exact dependency tree and upstream terms again before distributing an image.

## Development

The regular development stack starts the gateway as a private service:

```sh
docker compose up --build
```

For local development, Compose provides three distinct development-only keys when the corresponding variables are empty. Do not copy these defaults to a deployed environment. To test pairing, open **Workspace settings → Channels → WhatsApp (Baileys)**, acknowledge the risk, create the connection, choose **Link / reconnect by QR**, and scan the current QR from WhatsApp → Linked devices.

## Production setup

1. Copy `deploy/env.prod.example` to `.env`.
2. Run `make prod-secrets`; paste the three generated `BAILEYS_*_KEY` values into `.env`. The master key and each HMAC key must be independent canonical base64 encodings of 32 random bytes.
3. Back up `BAILEYS_SESSION_MASTER_KEY` separately from the database and state volume. Losing it makes saved gateway auth records unrecoverable. Losing either HMAC key breaks the corresponding service direction.
4. Start with `make prod-up`. `baileys-gateway` has no `ports:` mapping; only Caddy publishes host ports.
5. Back up the encrypted `baileys_state` volume along with PostgreSQL. Restore both together and keep the master key. A key rotation without a re-encryption tool is not supported; retain the old key until a tested migration procedure exists.
6. To revoke a linked device, use **Close linked session**. Deleting a channel logs out best-effort and preserves stored conversations. Disabling a channel stops Django sends and asks the gateway to stop the socket without deleting the saved auth state.

For deployments where Django app/worker and the gateway cannot share a private persistent service and volume, do not run the gateway as a cron job or in the Django worker. Deploy it as a persistent private service with durable encrypted storage and equivalent network controls.

## Verification limits

Gateway unit tests use the installed Baileys API without a live phone. CI cannot prove that WhatsApp will accept a QR, keep a session linked, or deliver a message. Perform any real-device check only with a dedicated test number and consenting participants. The current implementation has not been verified against a real device; no real WhatsApp E2E result is claimed.
