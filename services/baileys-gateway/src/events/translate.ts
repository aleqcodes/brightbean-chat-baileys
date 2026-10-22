import { createHash } from 'node:crypto';
import type { WAMessage } from '@whiskeysockets/baileys';

export type GatewayEvent = { schema_version: 1; event_id: string; connection_id: string; session_generation: number; occurred_at: string; type: string; payload: Record<string, unknown> };

export function translateMessage(connectionId: string, generation: number, message: WAMessage, upsertType: string): GatewayEvent | undefined {
  if (upsertType !== 'notify' || !message.key.id || !message.key.remoteJid || message.key.fromMe) return;
  const jid = message.key.remoteJid;
  if (!jid.endsWith('@s.whatsapp.net') && !jid.endsWith('@lid')) return;
  const content = message.message?.ephemeralMessage?.message ?? message.message;
  if (!content) return;
  let payload: Record<string, unknown>;
  if (content.conversation || content.extendedTextMessage?.text) payload = { message_id: message.key.id, chat_jid: jid, from_me: false, content: { kind: 'text', text: content.conversation ?? content.extendedTextMessage?.text } };
  else if (content.imageMessage || content.videoMessage || content.audioMessage || content.documentMessage) {
    const media = (content.imageMessage ?? content.videoMessage ?? content.audioMessage ?? content.documentMessage) as unknown as Record<string, unknown>;
    const kind = content.imageMessage ? 'image' : content.videoMessage ? 'video' : content.audioMessage ? 'audio' : 'document';
    const caption = typeof media.caption === 'string' ? media.caption : '';
    const mimetype = typeof media.mimetype === 'string' ? media.mimetype : '';
    const fileName = typeof media.fileName === 'string' ? media.fileName : '';
    payload = { message_id: message.key.id, chat_jid: jid, from_me: false, content: { kind, caption, mimetype, file_name: fileName } };
  } else return;
  const identity = [connectionId, 'message.upsert', jid, message.key.id, 'false', message.key.participant ?? ''].join('\n');
  return { schema_version: 1, event_id: createHash('sha256').update(identity).digest('hex'), connection_id: connectionId, session_generation: generation, occurred_at: new Date().toISOString(), type: 'message.upsert', payload };
}
