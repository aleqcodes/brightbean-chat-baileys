import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { sign } from '../auth/http-signatures.js';
import type { GatewayEvent } from './translate.js';

export class EventOutbox {
  readonly #file: string;
  readonly #callback: URL;
  readonly #key: Buffer;
  readonly #items = new Map<string, GatewayEvent>();
  #tail: Promise<void> = Promise.resolve();
  #stopping = false;
  constructor(dir: string, callback: URL, key: Buffer) { this.#file = join(dir, 'outbox.json'); this.#callback = callback; this.#key = key; }
  async load(): Promise<void> {
    await mkdir(this.#file.slice(0, this.#file.lastIndexOf('/')), { recursive: true, mode: 0o700 });
    try { for (const event of JSON.parse(await readFile(this.#file, 'utf8')) as GatewayEvent[]) this.#items.set(event.event_id, event); }
    catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error; }
    for (const event of this.#items.values()) void this.#deliver(event);
  }
  async #persist(): Promise<void> {
    const temp = `${this.#file}.tmp`;
    await writeFile(temp, JSON.stringify([...this.#items.values()]), { mode: 0o600 });
    await rename(temp, this.#file);
  }
  async enqueue(event: GatewayEvent): Promise<void> {
    this.#items.set(event.event_id, event);
    this.#tail = this.#tail.then(() => this.#persist());
    await this.#tail;
    void this.#deliver(event);
  }
  async #deliver(event: GatewayEvent): Promise<void> {
    let delay = 1000;
    while (!this.#stopping && this.#items.has(event.event_id)) {
      const body = Buffer.from(JSON.stringify(event));
      try {
        const response = await fetch(this.#callback, { method: 'POST', headers: { 'Content-Type': 'application/json', ...sign('POST', this.#callback.pathname, body, this.#key) }, body, signal: AbortSignal.timeout(10000), redirect: 'error' });
        if (response.ok) {
          this.#items.delete(event.event_id);
          this.#tail = this.#tail.then(() => this.#persist());
          await this.#tail;
          return;
        }
      } catch { /* retain in durable outbox */ }
      await new Promise(resolve => setTimeout(resolve, delay));
      delay = Math.min(delay * 2, 60000);
    }
  }
  stop(): void { this.#stopping = true; }
  get size(): number { return this.#items.size; }
}
