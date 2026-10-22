import { z } from 'zod';

export const sendSchema = z.object({
  command_id: z.string().uuid(),
  jid: z.string().max(160).regex(/^[0-9]{5,20}@(s\.whatsapp\.net|lid)$/),
  text: z.string().min(1).max(65536),
}).strict();
