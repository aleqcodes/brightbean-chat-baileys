import makeWASocket, { DisconnectReason, type WASocket } from '@whiskeysockets/baileys';
import pino from 'pino';
import { Boom } from '@hapi/boom';
import { randomUUID } from 'node:crypto';
import QRCode from 'qrcode';
import { readFile, rename, writeFile, mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { AuthStore } from './store.js';
import { EventOutbox } from '../events/outbox.js';
import { translateMessage } from '../events/translate.js';

const baileysLogger = pino({ level: 'silent' });

type Status = { state: string; session_generation: number; expires_at?: string; error_code?: string };
type Command = { command_id: string; jid: string; text: string };
type Ack = { state: 'sent' | 'unknown' | 'failed'; provider_message_id?: string };

export class SessionManager {
  readonly #auth: AuthStore;
  readonly #outbox: EventOutbox;
  readonly #dir: string;
  readonly #sockets = new Map<string, WASocket>();
  readonly #status = new Map<string, Status>();
  readonly #qr = new Map<string, { value: string; expiresAt: string }>();
  readonly #commands = new Map<string, Ack>();
  #generation = new Map<string, number>();
  #enabled = new Set<string>();
  #stopping = false;
  readonly #starting = new Map<string, Promise<void>>();
  constructor(dir: string, auth: AuthStore, outbox: EventOutbox) { this.#dir = dir; this.#auth = auth; this.#outbox = outbox; }
  async initialize(): Promise<void> {
    await mkdir(this.#dir, { recursive: true, mode: 0o700 });
    try {
      const saved = JSON.parse(await readFile(join(this.#dir, 'gateway.json'), 'utf8')) as { enabled: string[]; generation: [string, number][]; commands: [string, Ack][] };
      this.#enabled = new Set(saved.enabled); this.#generation = new Map(saved.generation); for (const [id, ack] of saved.commands) this.#commands.set(id, ack);
    } catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error; }
  }
  async #persist(): Promise<void> {
    const path = join(this.#dir, 'gateway.json');
    await writeFile(`${path}.tmp`, JSON.stringify({ enabled: [...this.#enabled], generation: [...this.#generation], commands: [...this.#commands] }), { mode: 0o600 });
    await rename(`${path}.tmp`, path);
  }
  async startPairing(id: string): Promise<Status> {
    if (this.#stopping) throw new Error('shutting_down');
    this.#enabled.add(id); await this.#persist(); await this.#start(id);
    return this.getStatus(id);
  }
  async #start(id: string): Promise<void> {
    const pending = this.#starting.get(id);
    if (pending) return pending;
    const attempt = this.#startSocket(id);
    this.#starting.set(id, attempt);
    try { await attempt; }
    finally { if (this.#starting.get(id) === attempt) this.#starting.delete(id); }
  }
  async #startSocket(id: string): Promise<void> {
    if (this.#sockets.has(id) || this.#stopping || !this.#enabled.has(id)) return;
    const generation = (this.#generation.get(id) ?? 0) + 1;
    this.#generation.set(id, generation); await this.#persist();
    const { state, saveCreds } = await this.#auth.use(id);
    const socket = makeWASocket({ auth: state, printQRInTerminal: false, logger: baileysLogger });
    this.#sockets.set(id, socket); this.#status.set(id, { state: 'connecting', session_generation: generation });
    socket.ev.on('creds.update', () => { void saveCreds(); });
    socket.ev.on('messages.upsert', batch => {
      for (const message of batch.messages) { const event = translateMessage(id, generation, message, batch.type); if (event) void this.#outbox.enqueue(event); }
    });
    socket.ev.on('connection.update', update => {
      if (update.qr) {
        const expiresAt = new Date(Date.now() + 60000).toISOString();
        this.#qr.set(id, { value: update.qr, expiresAt });
        this.#status.set(id, { state: 'qr_ready', session_generation: generation, expires_at: expiresAt });
      }
      if (update.connection === 'open') {
        this.#qr.delete(id);
        this.#status.set(id, { state: 'connected', session_generation: generation });
        const accountJid = socket.user?.id.replace(/:\d+(?=@)/, '');
        void this.#outbox.enqueue({ schema_version: 1, event_id: randomUUID(), connection_id: id, session_generation: generation, occurred_at: new Date().toISOString(), type: 'connection.update', payload: { state: 'connected', ...(accountJid ? { account_jid: accountJid } : {}) } });
      }
      if (update.connection === 'close') {
        const code = (update.lastDisconnect?.error as Boom | undefined)?.output?.statusCode;
        const existing = this.#status.get(id)?.state;
        if (existing === 'disabled' || existing === 'logged_out') {
          this.#sockets.delete(id);
          this.#qr.delete(id);
          return;
        }
        const loggedOut = code === DisconnectReason.loggedOut;
        const errorCode = loggedOut ? 'logged_out' : typeof code === 'number' ? `disconnect_${code}` : 'disconnected';
        this.#sockets.delete(id); this.#qr.delete(id);
        this.#status.set(id, { state: loggedOut ? 'logged_out' : 'reconnecting', session_generation: generation, error_code: errorCode });
        if (loggedOut) {
          this.#enabled.delete(id);
          void this.#auth.clear(id);
          void this.#persist();
        }
        void this.#outbox.enqueue({ schema_version: 1, event_id: randomUUID(), connection_id: id, session_generation: generation, occurred_at: new Date().toISOString(), type: 'connection.update', payload: { state: loggedOut ? 'logged_out' : 'reconnecting', error_code: errorCode } });
        if (!loggedOut && this.#enabled.has(id) && !this.#stopping) {
          const wait = Math.min(30000, 1000 * (2 ** Math.min(generation, 5))) + Math.floor(Math.random() * 1000);
          setTimeout(() => void this.#start(id), wait).unref();
        }
      }
    });
  }
  getStatus(id: string): Status { return this.#status.get(id) ?? { state: this.#enabled.has(id) ? 'connecting' : 'disabled', session_generation: this.#generation.get(id) ?? 0 }; }
  async getPairingQr(id: string): Promise<{ qr?: string; expires_at?: string }> {
    const entry = this.#qr.get(id);
    if (!entry || Date.parse(entry.expiresAt) <= Date.now()) return {};
    return { qr: await QRCode.toDataURL(entry.value), expires_at: entry.expiresAt };
  }
  async send(id: string, command: Command): Promise<Ack> {
    const prior = this.#commands.get(command.command_id); if (prior) return prior;
    const socket = this.#sockets.get(id); if (!socket || !this.#enabled.has(id)) return { state: 'failed' };
    this.#commands.set(command.command_id, { state: 'unknown' }); await this.#persist();
    try {
      const result = await socket.sendMessage(command.jid, { text: command.text });
      const ack: Ack = result?.key.id ? { state: 'sent', provider_message_id: result.key.id } : { state: 'unknown' };
      this.#commands.set(command.command_id, ack); await this.#persist(); return ack;
    } catch { const ack: Ack = { state: 'unknown' }; this.#commands.set(command.command_id, ack); await this.#persist(); return ack; }
  }
  async logout(id: string): Promise<void> { this.#enabled.delete(id); this.#status.set(id, { state: 'logged_out', session_generation: this.#generation.get(id) ?? 0 }); this.#sockets.get(id)?.end(new Error('logout')); this.#sockets.delete(id); this.#qr.delete(id); await this.#auth.clear(id); await this.#persist(); }
  async disable(id: string): Promise<void> { this.#enabled.delete(id); this.#status.set(id, { state: 'disabled', session_generation: this.#generation.get(id) ?? 0 }); this.#sockets.get(id)?.end(new Error('disabled')); this.#sockets.delete(id); await this.#persist(); }
  async resumeOnBoot(): Promise<void> { for (const id of this.#enabled) void this.#start(id); }
  async shutdown(): Promise<void> { this.#stopping = true; this.#outbox.stop(); for (const socket of this.#sockets.values()) socket.end(undefined); this.#sockets.clear(); await this.#persist(); }
}
