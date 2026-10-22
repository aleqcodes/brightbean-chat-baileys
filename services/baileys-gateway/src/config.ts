import { createHash } from 'node:crypto';

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Missing required configuration: ${name}`);
  return value;
}

function key(name: string): Buffer {
  const encoded = required(name);
  const value = Buffer.from(encoded, 'base64');
  if (value.length !== 32 || value.toString('base64') !== encoded) {
    throw new Error(`${name} must be canonical base64 encoding of exactly 32 bytes`);
  }
  return value;
}

const url = new URL(required('DJANGO_INTERNAL_BASE_URL'));
if (url.protocol !== 'http:' && url.protocol !== 'https:') throw new Error('Invalid Django callback URL');
if (url.username || url.password || url.search || url.hash) throw new Error('Django callback URL must be an origin/path only');

export const config = Object.freeze({
  port: Number(process.env.PORT ?? '3100'),
  stateDir: process.env.BAILEYS_STATE_DIR ?? '/var/lib/baileys',
  masterKey: key('BAILEYS_SESSION_MASTER_KEY'),
  inboundKey: key('BAILEYS_DJANGO_TO_GATEWAY_HMAC_KEY'),
  outboundKey: key('BAILEYS_GATEWAY_TO_DJANGO_HMAC_KEY'),
  callbackUrl: new URL('/internal/baileys/events/', url),
  maxBodyBytes: 1024 * 1024,
  timestampToleranceSeconds: 300,
});
if (!Number.isInteger(config.port) || config.port < 1 || config.port > 65535) throw new Error('Invalid PORT');

export function opaqueId(input: string): string {
  return createHash('sha256').update(input).digest('hex');
}
