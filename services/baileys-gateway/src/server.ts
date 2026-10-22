import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { z } from 'zod';
import { config } from './config.js';
import { readBody, ReplayGuard, verify } from './auth/http-signatures.js';
import { AuthStore } from './sessions/store.js';
import { SessionManager } from './sessions/manager.js';
import { EventOutbox } from './events/outbox.js';
import { sendSchema } from './sessions/commands.js';

const guard = new ReplayGuard(config.stateDir);
const outbox = new EventOutbox(config.stateDir, config.callbackUrl, config.outboundKey);
const sessions = new SessionManager(config.stateDir, new AuthStore(config.stateDir, config.masterKey), outbox);
const uuid = z.string().uuid();
const pairSchema = z.object({ request_id: uuid }).strict();

function reply(res: ServerResponse, status: number, value: unknown): void {
  const body = JSON.stringify(value);
  res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'Content-Length': Buffer.byteLength(body) });
  res.end(body);
}

async function route(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const path = req.url ?? '';
  if (req.method === 'GET' && path === '/readyz') { reply(res, 200, { ready: true }); return; }
  if (!/^\/(v1\/sessions\/[^/]+\/(pair|status|qr|send|logout|disable))$/.test(path)) { reply(res, 404, { error: 'not_found' }); return; }
  if (req.headers['content-type'] !== 'application/json') { reply(res, 415, { error: 'content_type' }); return; }
  let body: Buffer;
  try { body = await readBody(req, config.maxBodyBytes); } catch { reply(res, 413, { error: 'request_too_large' }); return; }
  if (!(await verify(req, path, body, config.inboundKey, guard, config.timestampToleranceSeconds))) { reply(res, 401, { error: 'unauthorized' }); return; }
  const match = /^\/v1\/sessions\/([^/]+)\/(pair|status|qr|send|logout|disable)$/.exec(path);
  if (!match || !uuid.safeParse(match[1]).success) { reply(res, 404, { error: 'not_found' }); return; }
  const [, id, action] = match;
  try {
    if (action === 'status' && req.method === 'GET') { reply(res, 200, sessions.getStatus(id!)); return; }
    if (action === 'qr' && req.method === 'GET') { reply(res, 200, await sessions.getPairingQr(id!)); return; }
    const input: unknown = body.length ? JSON.parse(body.toString('utf8')) : null;
    if (action === 'pair' && req.method === 'POST') { if (!pairSchema.safeParse(input).success) { reply(res, 400, { error: 'invalid_request' }); return; } reply(res, 200, await sessions.startPairing(id!)); return; }
    if (action === 'send' && req.method === 'POST') { const parsed = sendSchema.safeParse(input); if (!parsed.success) { reply(res, 400, { error: 'invalid_request' }); return; } reply(res, 200, await sessions.send(id!, parsed.data)); return; }
    if (action === 'logout' && req.method === 'POST') { if (!pairSchema.safeParse(input).success) { reply(res, 400, { error: 'invalid_request' }); return; } await sessions.logout(id!); reply(res, 200, { state: 'logged_out' }); return; }
    if (action === 'disable' && req.method === 'POST') { if (!pairSchema.safeParse(input).success) { reply(res, 400, { error: 'invalid_request' }); return; } await sessions.disable(id!); reply(res, 200, { state: 'disabled' }); return; }
    reply(res, 405, { error: 'method_not_allowed' });
  } catch { reply(res, 503, { error: 'temporarily_unavailable' }); }
}

await sessions.initialize();
await outbox.load();
await sessions.resumeOnBoot();
const server = createServer((req, res) => { void route(req, res).catch(() => { if (!res.headersSent) reply(res, 500, { error: 'internal_error' }); }); });
server.requestTimeout = 15000;
server.headersTimeout = 10000;
server.listen(config.port, '0.0.0.0');
let closing = false;
async function shutdown(): Promise<void> { if (closing) return; closing = true; server.close(); await sessions.shutdown(); }
process.on('SIGTERM', () => { void shutdown(); });
process.on('SIGINT', () => { void shutdown(); });
