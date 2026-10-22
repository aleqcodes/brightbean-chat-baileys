import { createCipheriv, createDecipheriv, randomBytes } from 'node:crypto';
import { mkdir, readFile, rename, writeFile, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { BufferJSON, initAuthCreds, proto, type AuthenticationState, type SignalDataTypeMap } from '@whiskeysockets/baileys';

export class AuthStore {
  readonly #dir: string;
  readonly #key: Buffer;
  constructor(dir: string, key: Buffer) { this.#dir = dir; this.#key = key; }

  async #read(connectionId: string): Promise<Record<string, unknown>> {
    try {
      const record = JSON.parse(await readFile(join(this.#dir, `${connectionId}.auth`), 'utf8')) as { iv: string; tag: string; data: string };
      const decipher = createDecipheriv('aes-256-gcm', this.#key, Buffer.from(record.iv, 'base64'));
      decipher.setAuthTag(Buffer.from(record.tag, 'base64'));
      return JSON.parse(Buffer.concat([decipher.update(Buffer.from(record.data, 'base64')), decipher.final()]).toString('utf8'), BufferJSON.reviver) as Record<string, unknown>;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return { creds: initAuthCreds(), keys: {} };
      throw new Error('Unable to decrypt session auth state');
    }
  }

  async #write(connectionId: string, state: Record<string, unknown>): Promise<void> {
    await mkdir(this.#dir, { recursive: true, mode: 0o700 });
    const iv = randomBytes(12);
    const cipher = createCipheriv('aes-256-gcm', this.#key, iv);
    const ciphertext = Buffer.concat([cipher.update(JSON.stringify(state, BufferJSON.replacer)), cipher.final()]);
    const tmp = join(this.#dir, `.${connectionId}.${randomBytes(8).toString('hex')}.tmp`);
    await writeFile(tmp, JSON.stringify({ iv: iv.toString('base64'), tag: cipher.getAuthTag().toString('base64'), data: ciphertext.toString('base64') }), { mode: 0o600, flag: 'wx' });
    await rename(tmp, join(this.#dir, `${connectionId}.auth`));
  }

  async use(connectionId: string): Promise<{ state: AuthenticationState; saveCreds: () => Promise<void> }> {
    const record = await this.#read(connectionId);
    const creds = record.creds as AuthenticationState['creds'];
    const keysData = (record.keys ?? {}) as Record<string, Record<string, unknown>>;
    const save = async (): Promise<void> => this.#write(connectionId, { creds, keys: keysData });
    return {
      state: {
        creds,
        keys: {
          get: async <T extends keyof SignalDataTypeMap>(type: T, ids: string[]) => {
            const values = keysData[type] ?? {};
            return Object.fromEntries(ids.map(id => [id, values[id] ? (type === 'app-state-sync-key' ? proto.Message.AppStateSyncKeyData.create(values[id] as object) : values[id]) : null])) as { [id: string]: SignalDataTypeMap[T] };
          },
          set: async (data) => {
            for (const [type, entries] of Object.entries(data)) {
              const category = keysData[type] ?? (keysData[type] = {});
              for (const [id, value] of Object.entries(entries ?? {})) value == null ? delete category[id] : category[id] = value;
            }
            await save();
          },
        },
      },
      saveCreds: save,
    };
  }

  async clear(connectionId: string): Promise<void> {
    await rm(join(this.#dir, `${connectionId}.auth`), { force: true });
  }
}
