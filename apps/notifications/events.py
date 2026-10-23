"""The event-type registry — this app's whole vocabulary.

Studio spells its event types as a ``TextChoices`` enum on an indexed
``CharField``. That works while one team owns every event, and stops working
here: issue #7 ships eight types for consumers that land in Layers 3 to 6, and
each of those layers will want its own. With ``choices=`` on the column, every
one of them is a schema migration in *this* app authored by *another* agent —
for a constraint Django enforces in forms and not in the database.

So the column is a plain ``CharField`` and this module is the vocabulary. It is
**additive**: a later app registers from its own ``AppConfig.ready()`` and never
edits this file.

Registration also carries the *copy*. :func:`~apps.notifications.engine.notify`
takes only a ``context`` dict — no title, no body — so the wording of an event
lives in one place instead of being retyped at every call site, and rewording an
alert is an edit here rather than a hunt through Layer 3.

Copy templates are :meth:`str.format_map` strings rather than Django templates,
which sidesteps a trap: a Django template renders with autoescaping *on*, so
``Ben & Jerry's`` would be stored in the ``title`` column as
``Ben &amp; Jerry&#x27;s`` and then escaped a second time by ``{{ n.title }}``
at display time. These columns hold plain text and are escaped once, where they
are shown. The format strings are first-party Python; only the substituted
values come from the world, and they are inert.
"""

import logging
from dataclasses import dataclass, field

from django.conf import settings

logger = logging.getLogger(__name__)

__all__ = [
    "REGISTRY",
    "NotificationCopyError",
    "NotificationEvent",
    "UnknownEventTypeError",
    "get_event",
    "register_event",
    "registered_choices",
    "render",
]


class NotificationCopyError(LookupError):
    """The registry cannot produce a notification: unknown type, or missing context.

    ``LookupError`` rather than ``KeyError``, so an ``except KeyError`` further
    up the stack cannot swallow it. Not a ``ValueError`` either: ``apps.members``
    already uses a ``ValueError`` subclass (``MembershipError``) as its "the
    caller may not do that" channel, and this is a programming error rather than
    a refusal.
    """


#: The name the issue's acceptance criterion uses ("unknown event type raises
#: in DEBUG"). Same class; both spellings are exported so either reads naturally.
UnknownEventTypeError = NotificationCopyError


def _fail(message: str, *args: object) -> None:
    """Raise in DEBUG, log in production.

    The issue asks for this split for unknown event types, and the same
    reasoning covers missing context keys, so both go through here. It is the
    right shape either way: both are always programming errors, but the call
    sites are webhook handlers and queue workers. Failing loudly in development
    is how the typo gets found; failing loudly in production would turn a
    mis-typed notification into a failed inbound message.

    ``settings.DEBUG`` is read here, per call — never captured at import.
    ``config/settings/test.py`` forces ``DEBUG=False``, so the suite runs the
    production branch by default and reaches the other one with
    ``override_settings(DEBUG=True)``.
    """
    if settings.DEBUG:
        raise NotificationCopyError(message % args)
    logger.error(message, *args)


@dataclass(frozen=True)
class NotificationEvent:
    """One registered event type.

    ``emails_by_default`` is the per-event half of the email decision; the
    per-user half is :class:`~apps.notifications.models.NotificationSetting`.
    Keeping both is the one good idea salvaged from Studio's preference matrix:
    **the product decides which events deserve an email, the person decides
    whether they get any email at all.** Zero tables, zero UI.

    An event nobody can act on from their inbox does not earn an email, and
    neither does one that can fire in a burst — see ``flow_execution_failed``.
    """

    key: str
    label: str
    icon: str
    title: str
    body: str = ""
    email_subject: str = ""
    emails_by_default: bool = True
    # Maps to the alert-* / --success-* / --error-* vocabulary in
    # apps/theme/static_src/src/styles.css.
    tone: str = "info"
    #: Keys the copy needs. A caller who omits one gets the DEBUG/log policy
    #: rather than a sentence with a hole in it that nobody notices.
    required_context: tuple[str, ...] = field(default_factory=tuple)


REGISTRY: dict[str, NotificationEvent] = {}


def register_event(event: NotificationEvent) -> NotificationEvent:
    """Add an event type. Refuses to shadow a *different* event on the same key.

    Silently overwriting would let a later app retarget another app's
    notifications by picking the same string, and the symptom would be wrong
    copy in someone else's feature. Re-registering the identical event is a
    no-op, so a module re-imported under the autoreloader is harmless.

    This raises in every environment, DEBUG or not: two layers fighting over one
    key is worse than a crash, and it surfaces at import rather than at dispatch.
    """
    existing = REGISTRY.get(event.key)
    if existing is not None and existing != event:
        raise ValueError(
            f"Notification event {event.key!r} is already registered as something else. "
            f"Event keys are global; pick a name that says which feature owns it."
        )
    REGISTRY[event.key] = event
    return event


def get_event(key: str) -> NotificationEvent | None:
    """Look up an event type. ``None`` when it is unknown and we are not in DEBUG."""
    event = REGISTRY.get(key)
    if event is not None:
        return event
    _fail(
        "Unknown notification event type %r; notification dropped. Register it with "
        "apps.notifications.events.register_event() before calling notify(). Known types: %r",
        key,
        sorted(REGISTRY),
    )
    return None


def registered_choices() -> list[tuple[str, str]]:
    """``(key, label)`` pairs for the history page's type filter and the admin."""
    return sorted(((event.key, event.label) for event in REGISTRY.values()), key=lambda pair: pair[1])


class _Blanks(dict):
    """A format mapping where a missing key is a blank rather than a ``KeyError``.

    Anything genuinely required is declared in ``required_context`` and checked
    before rendering, so reaching ``__missing__`` means an optional key — a gap
    in the sentence beats an exception thrown from inside a webhook.
    """

    def __missing__(self, key: str) -> str:
        return ""


def render(event: NotificationEvent, context: dict[str, object]) -> tuple[str, str]:
    """Fill an event's title and body from a notify() context."""
    missing = [key for key in event.required_context if key not in context]
    if missing:
        _fail("Notification %r is missing required context key(s) %r.", event.key, missing)
    mapping = _Blanks(context)
    return _format(event.title, mapping), _format(event.body, mapping)


def _format(template: str, mapping: _Blanks) -> str:
    if not template:
        return ""
    try:
        return template.format_map(mapping)
    except (IndexError, ValueError) as exc:
        # A malformed template is ours, not the caller's; do not take the
        # notification down with it.
        logger.error("Malformed notification copy template %r: %s", template, exc)
        return template


# ---------------------------------------------------------------------------
# The types this product needs
# ---------------------------------------------------------------------------
# Named by the #7 trigger in docs/agent-prompts/layer-2.md. The issue body lists
# seven; the trigger adds whatsapp_template_reviewed. Each names the consumer
# that will call it — none of which exists yet, because this issue ships no
# callers.

register_event(
    NotificationEvent(
        key="flow_loop_cap_hit",
        label="Fluxo excedeu o limite de repetição",
        icon="flows",
        tone="error",
        # SPEC §9.2: 30 blocks since the last pause fails the run and notifies
        # workspace admins. The loop-cap consumer is L3-B.
        title='Fluxo "{flow_name}" excedeu o limite de repetição',
        body=(
            "A execução passou por 30 etapas sem pausa para {contact_name} e foi interrompida. "
            "Abra o fluxo e procure um ciclo sem nenhuma espera."
        ),
        required_context=("flow_name",),
    )
)

register_event(
    NotificationEvent(
        key="flow_execution_failed",
        label="Execução do fluxo falhou",
        icon="flows",
        tone="error",
        title='A execução do fluxo "{flow_name}" falhou',
        body="A execução de {contact_name} parou em {node_label}: {error}",
        required_context=("flow_name",),
        # In-app only. This fires once per *execution*, so one broken flow in a
        # busy workspace is a mail storm. The in-app rows still pile up — see
        # the fan-out note in the PR — but they pile up somewhere survivable.
        emails_by_default=False,
    )
)

register_event(
    NotificationEvent(
        key="channel_needs_reauth",
        label="Canal precisa ser reconectado",
        icon="channels",
        tone="warn",
        title="{channel_name} precisa ser reconectado",
        body=(
            "{platform_label} deixou de aceitar as credenciais armazenadas. "
            "Este canal não poderá enviar nem receber mensagens até ser reconectado."
        ),
        required_context=("channel_name",),
    )
)

register_event(
    NotificationEvent(
        key="outbound_webhook_disabled",
        label="Webhook de saída desativado",
        icon="channels",
        tone="error",
        # SPEC §17: auto-disable after 100 consecutive failures, with an admin
        # notification. The consumer is L5-F (#25).
        title="Webhook desativado após falhas repetidas",
        body=(
            "{url} falhou {failure_count} vezes seguidas e foi desativado. "
            "Ative-o novamente quando o endpoint estiver funcionando."
        ),
        required_context=("url",),
    )
)

register_event(
    NotificationEvent(
        key="inbox_reminder",
        label="Lembrete da caixa de entrada",
        icon="inbox",
        tone="info",
        # SPEC §14: a scheduled_action that becomes an in-app notification.
        # In-app is the whole point of a reminder you set for yourself, so it
        # does not also earn an email.
        title="Lembrete: {contact_name}",
        body="{note}",
        emails_by_default=False,
    )
)

register_event(
    NotificationEvent(
        key="member_mentioned",
        label="Menção de uma pessoa da equipe",
        icon="users",
        tone="info",
        # SPEC §11.2: the action node's notify_members.
        title="{actor_name} mencionou você",
        body="{message}",
        required_context=("actor_name",),
    )
)

register_event(
    NotificationEvent(
        key="broadcast_finished",
        label="Disparo concluído",
        icon="broadcasts",
        tone="success",
        title='Disparo "{broadcast_name}" concluído',
        body="{sent} enviados, {failed} com falha, {skipped} ignorados.",
        required_context=("broadcast_name",),
        emails_by_default=False,
    )
)

register_event(
    NotificationEvent(
        key="whatsapp_template_reviewed",
        label="Modelo do WhatsApp atualizado",
        icon="channels",
        tone="info",
        title='O modelo do WhatsApp "{template_name}" foi revisado',
        body="{reason}",
        required_context=("template_name", "status"),
    )
)
