"""The machine-readable codes an outbound message can carry.

``Message.error`` holds one of these and nothing else. A provider's own error
text routinely quotes the request that caused it — including an access token in
a query string — and this column is rendered in the inbox (SECURITY-BASELINE
§5), so the sentence a human reads is looked up from :data:`REASON_COPY` at
render time rather than stored per row. That is the same "registered copy, not
an f-string at the call site" shape ``apps.notifications.events`` uses.

Four vocabularies, kept apart because they answer different questions:

``Grant``   why a send was allowed — which is not decoration. ``human_agent``
            and ``tag_supplied`` are the difference between a compliant Meta
            send and one that can get a page disabled, and an operator asking
            "why did this go out?" is asking for exactly this word.
``Denial``  why compliance refused. Lands on the message row.
``Failure`` why the provider call did not produce a sent message.
``Limit``   why the organization's own plan refused. Optional: on a
            deployment with no billing configured nothing can produce one.
"""

from enum import StrEnum

__all__ = ["Denial", "Failure", "Grant", "Limit", "REASON_COPY", "describe"]


class Grant(StrEnum):
    """Why :func:`apps.messaging.compliance.can_send` said yes."""

    NO_WINDOW = "no_window"
    IN_WINDOW = "in_window"
    HUMAN_AGENT = "human_agent"
    TAG_SUPPLIED = "tag_supplied"
    TEMPLATE_SUPPLIED = "template_supplied"


class Denial(StrEnum):
    """Why compliance refused. Every one of these ends up on a failed row."""

    OPTED_OUT = "opted_out"
    CONTACT_DELETED = "contact_deleted"
    NO_OPT_IN = "no_opt_in"
    NO_IDENTITY = "no_identity"
    NO_CONNECTION = "no_connection"
    BROADCAST_NOT_ALLOWED = "broadcast_not_allowed"
    OUTSIDE_WINDOW = "outside_window"
    NEEDS_TEMPLATE = "needs_template"
    NEEDS_TAG = "needs_tag"


class Failure(StrEnum):
    """Why the provider call did not produce a sent message."""

    NO_ADAPTER = "no_adapter"
    PROVIDER_REJECTED = "provider_rejected"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    RATE_LIMITED = "rate_limited"
    RATE_DEFERRED = "rate_deferred"
    RETRIES_EXHAUSTED = "retries_exhausted"
    RETRY_UNSCHEDULABLE = "retry_unschedulable"
    # The one code here that is not the platform's doing: the caller retracted a
    # send it had already been given a row for. It belongs with the failures
    # anyway, because `failed` is the only terminal status a never-sent message
    # can hold and an operator reading the thread needs to know it will not go.
    WITHDRAWN = "withdrawn"


class Limit(StrEnum):
    """Why the organization's own plan refused the send.

    **A fourth vocabulary rather than a new ``Denial`` member**, and the
    distinction is not tidiness. ``Denial``'s members are consumed *set-wise*:
    ``apps.messaging.compliance`` gives each of them a ``Q`` and a callable, and
    ``apps.broadcasts.audience`` compiles them into a ``Case``/``When`` over
    identity rows. A plan limit is not a per-identity predicate — it is a
    property of the organization — so a ``Denial`` member with no ``Q`` spelling
    would be a landmine for whoever next writes ``for code in Denial``.

    It is also the only vocabulary here that is **optional**: on a deployment
    with no Stripe configuration nothing can ever produce one of these.
    """

    ACTIVE_CONTACTS = "plan_active_contacts"


#: One sentence per code, for the inbox and the flow-run log. Keyed by the raw
#: string so a stored value from an older release still resolves.
REASON_COPY: dict[str, str] = {
    Grant.NO_WINDOW: "Este canal não oferece uma janela de mensagens.",
    Grant.IN_WINDOW: "O contato enviou uma mensagem recentemente; a janela está aberta.",
    Grant.HUMAN_AGENT: "Enviada pela permissão de atendimento humano, disponível apenas para respostas no inbox.",
    Grant.TAG_SUPPLIED: "Enviada fora da janela com uma etiqueta de mensagem aprovada.",
    Grant.TEMPLATE_SUPPLIED: "Enviada fora da janela usando um modelo aprovado.",
    Denial.OPTED_OUT: "Este contato recusou receber mensagens neste canal.",
    Denial.CONTACT_DELETED: "Este contato foi excluído.",
    Denial.NO_OPT_IN: "Este contato nunca autorizou o envio de mensagens por este canal.",
    Denial.NO_IDENTITY: "Não há um endereço deste contato neste canal.",
    Denial.NO_CONNECTION: "Este endereço foi capturado antes de existir uma conexão com o canal.",
    Denial.BROADCAST_NOT_ALLOWED: "A plataforma não permite disparos.",
    Denial.OUTSIDE_WINDOW: "A janela de mensagens fechou e esta plataforma não oferece uma forma de reabri-la.",
    Limit.ACTIVE_CONTACTS: "O limite mensal de contatos do seu plano foi atingido; a mensagem não foi enviada.",
    Denial.NEEDS_TEMPLATE: "Fora da janela de mensagens, esta plataforma exige um modelo aprovado.",
    Denial.NEEDS_TAG: "Fora da janela de mensagens, esta plataforma exige uma etiqueta de mensagem aprovada.",
    Failure.NO_ADAPTER: "Não há um adaptador instalado para esta plataforma.",
    Failure.PROVIDER_REJECTED: "A plataforma rejeitou a mensagem.",
    Failure.PROVIDER_UNAVAILABLE: "Não foi possível acessar a plataforma.",
    Failure.RATE_LIMITED: "A plataforma está limitando o ritmo de envio desta conexão.",
    Failure.RATE_DEFERRED: "Aguardando a liberação do limite de envio desta conexão para enviar outra mensagem.",
    Failure.RETRIES_EXHAUSTED: "Não foi possível enviar a mensagem após várias tentativas.",
    Failure.RETRY_UNSCHEDULABLE: "O envio falhou e não foi possível agendar outra tentativa.",
    Failure.WITHDRAWN: "O trabalho que colocou esta mensagem na fila foi cancelado antes do envio.",
}


def describe(code: str) -> str:
    """The sentence for ``code``, or the code itself when nothing is registered.

    Falls back rather than raising: this runs on a render path, and a code from
    a newer worker than the web process is not a reason to 500 an inbox.
    """
    if not code:
        return ""
    # A provider code is appended after a colon (``provider_rejected:131047``);
    # the copy belongs to the part before it.
    return REASON_COPY.get(code.split(":", 1)[0], code)
