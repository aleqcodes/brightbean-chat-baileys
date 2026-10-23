/**
 * Human labels for schema properties.
 *
 * The artefact carries almost no `title` keywords, and its `description`s are
 * developer copy citing SPEC sections — useful as help text, wrong as a label.
 * So a property falls back through: schema `title`, this table, then a
 * humanised property name. A node type added later gets the humanised form,
 * which is serviceable; adding a line here is the optional polish.
 */

export const LABELS: Record<string, string> = {
  blocks: "Blocos da mensagem",
  // Its own line, because the humanised fallback spells the brand "Whatsapp".
  whatsapp_template: "Modelo do WhatsApp",
  buttons: "Botões",
  quick_replies: "Respostas rápidas",
  followup: "Se ninguém responder",
  retry_unmatched: "Tentar novamente se responderem outra coisa",
  actions: "Ações",
  flow_id: "Fluxo",
  match: "Correspondência",
  rules: "Regras",
  mode: "Modo",
  duration: "Duração",
  continue_window: "Janela de envio",
  paths: "Caminhos",
  sticky: "Lembrar o caminho por contato",
  method: "Método",
  url: "URL",
  headers: "Cabeçalhos",
  body: "Corpo",
  timeout_s: "Tempo limite (segundos)",
  response_mappings: "Salvar resposta em",
  fallback_handle_on_error: "Seguir a saída de erro em caso de falha",
  question: "Pergunta",
  reply_type: "Resposta esperada",
  target: "Salvar em",
  retry: "Tentar novamente",
  timeout: "Tempo limite",
  text: "Texto",
  media_url: "URL da mídia",
  subject: "Assunto",
  html_body: "Corpo (HTML)",
  from_override: "Endereço do remetente",
  media_id: "Arquivo da biblioteca",
  caption: "Legenda",
  cards: "Cartões",
  image: "Imagem",
  title: "Título",
  subtitle: "Subtítulo",
  url_button: "Botão de link",
  label: "Rótulo",
  action: "Ação",
  enabled: "Ativado",
  delay: "Atraso",
  unit: "Unidade",
  max: "Máximo",
  invalid_text: "Mensagem para resposta inválida",
  days: "Dias",
  from: "De",
  to: "Até",
  use_contact_timezone: "Usar o fuso horário do contato",
  weight: "Peso (%)",
  name: "Nome",
  value: "Valor",
  json_path: "Caminho JSON",
  target_type: "Salvar como",
  verb: "Ação",
  tag: "Etiqueta",
  field: "Campo",
  sequence: "Sequência",
  member: "Membro",
  member_ids: "Membros",
  via: "Enviar por",
  source: "Origem",
  op: "Operador",
  key: "Chave",
  type: "Tipo",
  id: "ID",
  datetime: "Data e hora",
  date: "Data",
};

/** `html_body` -> `Html body`, as a last resort. */
export function humanize(name: string): string {
  const words = name.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function labelFor(name: string, title?: string): string {
  return title ?? LABELS[name] ?? humanize(name);
}

/** Tag copy for the discriminated unions a person actually picks from. */
export const VARIANT_LABELS: Record<string, string> = {
  text: "Texto",
  image: "Imagem",
  audio: "Áudio",
  video: "Vídeo",
  file: "Arquivo",
  card: "Cartão",
  gallery: "Galeria",
  url: "Link",
  postback: "Continuar o fluxo",
  duration: "Aguardar um período fixo",
  date: "Aguardar até uma data",
  add_tag: "Adicionar etiqueta",
  remove_tag: "Remover etiqueta",
  set_field: "Definir um campo",
  clear_field: "Limpar um campo",
  subscribe_sequence: "Inscrever em uma sequência",
  unsubscribe_sequence: "Remover inscrição da sequência",
  open_conversation: "Abrir a conversa",
  close_conversation: "Fechar a conversa",
  assign_conversation: "Atribuir a conversa",
  notify_members: "Notificar membros",
};

export function variantLabel(tag: string): string {
  return VARIANT_LABELS[tag] ?? ENUM_LABELS[tag] ?? humanize(tag);
}

/**
 * Enum values, as a reader should see them.
 *
 * Every `enum` in the artefact used to render its options verbatim, so a select
 * offered `system_field`, `has_no_value`, `any_word` and `in_app`. Those are
 * wire values; the schema is the contract and these are the words.
 *
 * Deliberately not merged into VARIANT_LABELS: that table names the branches of
 * a tagged union, which a reader picks a *shape* from ("Wait a fixed time"),
 * and this one names a value inside a field. Several keys would collide with
 * different right answers — `date` is "Wait until a date" as a delay's mode and
 * "A date" as an expected reply.
 *
 * Anything missing still falls through to `humanize`, which gives "System
 * field" rather than `system_field` — serviceable, and the reason this is
 * polish rather than a correctness fix.
 */
export const ENUM_LABELS: Record<string, string> = {
  // What a question saves into, and what it will accept.
  system_field: "Um campo disponível para todos os contatos",
  variable: "Um valor apenas para esta execução",
  text: "Qualquer texto",
  number: "Um número",
  url: "Um link",
  has: "tem",
  has_not: "não tem",
  has_value: "tem algum valor",
  no_value: "está vazio",
  is: "é",
  is_not: "não é",
  in: "é um destes valores",
  not_in: "não é nenhum destes valores",
  not: "não é",
  contains: "contém",
  before: "é anterior a",
  after: "é posterior a",
  on: "é em",
  subscribed: "está inscrito em",
  inside: "está aberta",
  outside: "está fechada",
  all: "todos",
  any: "qualquer um",
  minutes: "minutos",
  hours: "horas",
  days: "dias",
  in_app: "No aplicativo",
  mon: "Seg", tue: "Ter", wed: "Qua", thu: "Qui", fri: "Sex", sat: "Sáb", sun: "Dom",
  first_name: "Nome",
  last_name: "Sobrenome",
  created_at: "Adicionado em",
  last_interaction_at: "Última interação",
  locale: "Idioma",
  timezone: "Fuso horário",
  instagram: "Instagram",
  messenger: "Facebook Messenger",
  whatsapp: "WhatsApp",
  telegram: "Telegram",
  sms: "SMS",
};


/**
 * What one item of a list is called, for the button that appends one.
 *
 * The adder used to read "Add", with "Add to Buttons" as its accessible name —
 * so a screen reader was told what it added and a reader was not. These are the
 * visible half, and they name the *thing*, not the list: you add a button, not
 * a Buttons.
 *
 * A list with no entry here falls back to "Add to <list label>", which is
 * serviceable and still says what it adds. Adding a line here is the polish.
 */
export const ADD_ONE: Record<string, string> = {
  blocks: "Adicionar parte à mensagem",
  buttons: "Adicionar botão",
  quick_replies: "Adicionar resposta rápida",
  cards: "Adicionar cartão",
  actions: "Adicionar ação",
  rules: "Adicionar regra",
  paths: "Adicionar caminho",
  headers: "Adicionar cabeçalho",
  response_mappings: "Adicionar valor para salvar",
  keywords: "Adicionar palavra-chave",
  texts: "Adicionar versão",
};

/**
 * How the "Add to this step" chips are grouped, and in what order.
 *
 * The headings answer "what is this for?" without opening anything, which a
 * flat row of four cannot: two of a send_message step's options are about
 * somebody going quiet and one is WhatsApp-only, and nothing said so.
 *
 * Keys, not node types, because the same property means the same thing
 * wherever it appears — `followup` is a wait on send_message and on
 * data_collection alike. A key in no group falls into the last one, so a
 * property added by a later layer is never silently dropped off the panel.
 */
export const ADD_GROUPS: readonly { label: string; keys: readonly string[] }[] = [
  { label: "Opções para tocar", keys: ["buttons", "quick_replies"] },
  { label: "Se não responderem", keys: ["followup", "retry_unmatched", "retry", "timeout"] },
  { label: "Somente WhatsApp", keys: ["whatsapp_template", "template"] },
  { label: "Mais", keys: [] },
];
