import { createHmac, randomUUID, timingSafeEqual } from 'node:crypto';
import type { IncomingMessage } from 'node:http';
import { appendFile, mkdir, readFile } from 'node:fs/promises';
import { join } from 'node:path';

export class ReplayGuard {
  readonly #file: string;
  readonly #seen = new Map<string, number>();
  #ready: Promise<void>;
  constructor(dir: string) { this.#file = join(dir, 'nonces.jsonl'); this.#ready = this.#load(); }
  async #load(): Promise<void> {
    await mkdir(this.#file.slice(0, this.#file.lastIndexOf('/')), { recursive: true, mode: 0o700 });
    try {
      const lines = (await readFile(this.#file, 'utf8')).trim().split('\n').filter(Boolean);
      for (const line of lines) { const item = JSON.parse(line) as [string, number]; if (item[1] > Date.now()) this.#seen.set(item[0], item[1]); }
    } catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error; }
  }
  async accept(nonce: string, ttlMs: number): Promise<boolean> {
    await this.#ready;
    const now = Date.now();
    for (const [key, expiry] of this.#seen) if (expiry <= now) this.#seen.delete(key);
    if (this.#seen.has(nonce)) return false;
    const expiry = now + ttlMs;
    this.#seen.set(nonce, expiry);
    await appendFile(this.#file, `${JSON.stringify([nonce, expiry])}\n`, { mode: 0o600 });
    return true;
  }
}

export async function readBody(req: IncomingMessage, maxBytes: number): Promise<Buffer> {
  const chunks: Buffer[] = [];
  let length = 0;
  for await (const chunk of req) {
    const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    length += bytes.length;
    if (length > maxBytes) throw new Error('body_too_large');
    chunks.push(bytes);
  }
  return Buffer.concat(chunks, length);
}

export async function verify(req: IncomingMessage, path: string, body: Buffer, secret: Buffer, guard: ReplayGuard, toleranceSeconds: number): Promise<boolean> {
  const timestamp = req.headers['x-baileys-timestamp'];
  const nonce = req.headers['x-baileys-nonce'];
  const signature = req.headers['x-baileys-signature'];
  if (typeof timestamp !== 'string' || typeof nonce !== 'string' || typeof signature !== 'string' || !/^[0-9]{10,13}$/.test(timestamp) || !/^[A-Za-z0-9_-]{20,128}$/.test(nonce)) return false;
  const timestampMs = Number(timestamp) * (timestamp.length === 13 ? 1 : 1000);
  if (Math.abs(Date.now() - timestampMs) > toleranceSeconds * 1000) return false;
  const input = `${req.method ?? 'GET'}\n${path}\n${timestamp}\n${nonce}\n`;
  const expected = createHmac('sha256', secret).update(input).update(body).digest();
  let supplied: Buffer;
  try { supplied = Buffer.from(signature, 'hex'); } catch { return false; }
  if (supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) return false;
  return guard.accept(nonce, toleranceSeconds * 2000);
}

export function sign(method: string, path: string, body: Buffer, secret: Buffer): Record<string, string> {
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const nonce = randomUUID();
  const value = createHmac('sha256', secret).update(`${method}\n${path}\n${timestamp}\n${nonce}\n`).update(body).digest('hex');
  return { 'X-Baileys-Timestamp': timestamp, 'X-Baileys-Nonce': nonce, 'X-Baileys-Signature': value };
}
