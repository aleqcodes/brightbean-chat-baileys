import type { WAMessage } from '@whiskeysockets/baileys';
import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac, randomUUID } from 'node:crypto';
import { EventEmitter } from 'node:events';
import { ReplayGuard, verify } from '../auth/http-signatures.js';
import { translateMessage } from '../events/translate.js';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { sendSchema } from '../sessions/commands.js';
import { join } from 'node:path';

const secret = Buffer.alloc(32, 9);

test('HMAC verifies exact request and rejects nonce replay', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'baileys-test-'));
  try {
    const guard = new ReplayGuard(dir);
    const body = Buffer.from('{"request_id":"x"}');
    const timestamp = Math.floor(Date.now() / 1000).toString();
    const nonce = randomUUID();
    const signature = createHmac('sha256', secret).update(`POST\n/v1/x\n${timestamp}\n${nonce}\n`).update(body).digest('hex');
    const headers = { 'x-baileys-timestamp': timestamp, 'x-baileys-nonce': nonce, 'x-baileys-signature': signature };
    const req = Object.assign(new EventEmitter(), { method: 'POST', headers }) as never;
    assert.equal(await verify(req, '/v1/x', body, secret, guard, 300), true);
    assert.equal(await verify(req, '/v1/x', body, secret, guard, 300), false);
    assert.equal(await verify(req, '/v1/x', Buffer.from('{}'), secret, guard, 300), false);
  } finally { await rm(dir, { recursive: true, force: true }); }
});

test('translator ignores groups, history and from-me messages', () => {
  const message = { key: { id: 'm1', remoteJid: '12345@s.whatsapp.net', fromMe: false }, message: { conversation: 'hello' } } as unknown as WAMessage;
  assert.equal(translateMessage('00000000-0000-4000-8000-000000000001', 1, message, 'notify')?.payload.content !== undefined, true);
  assert.equal(translateMessage('id', 1, message, 'append'), undefined);
  assert.equal(translateMessage('id', 1, { key: { ...message.key, remoteJid: '123@g.us' }, message: message.message } as WAMessage, 'notify'), undefined);
  assert.equal(translateMessage('id', 1, { key: { ...message.key, fromMe: true }, message: message.message } as WAMessage, 'notify'), undefined);
});
test('send command accepts phone-number and LID JIDs but rejects non-user destinations', () => {
  const base = { command_id: randomUUID(), text: 'hello' };
  assert.equal(sendSchema.safeParse({ ...base, jid: '15551234567@s.whatsapp.net' }).success, true);
  assert.equal(sendSchema.safeParse({ ...base, jid: '123456789012345@lid' }).success, true);
  assert.equal(sendSchema.safeParse({ ...base, jid: '12345@g.us' }).success, false);
  assert.equal(sendSchema.safeParse({ ...base, jid: 'not-a-user@lid' }).success, false);
});
