"""Template cards, as the two surfaces that show them render them.

``library.TemplateCard`` says what a shipped template *is* — a name, a summary,
the requirement kinds it walks out to. This module says how one *reads*: labels
resolved against the registries that already own them, a start URL reversed, and
the one per-workspace fact a card carries, which is whether the channel it needs
is connected.

It lives beside ``library`` rather than in a view because two views want it —
the gallery page and the flows-list empty state — and because ``library`` must
stay workspace-free: its cards are ``lru_cache``d on file content, so nothing
about a particular workspace may reach them.
"""

from collections.abc import Sequence
from typing import Any

from django.urls import reverse

__all__ = ["REQUIREMENT_KIND_HELP", "REQUIREMENT_KIND_LABELS", "card_contexts"]


#: What each requirement kind is called, everywhere it is named. Shared by the
#: cards and by the import review page's sections, so the same thing cannot be
#: called two different names one page apart.
REQUIREMENT_KIND_LABELS: dict[str, str] = {
    "tag": "Tags",
    "custom_field": "Campos personalizados",
    "sequence": "Sequências",
    "segment": "Segmentos",
    "member": "Membros",
    "flow": "Outros fluxos",
    "media": "Mídia",
    "platform": "Canais",
    "request_header": "Cabeçalhos de requisição",
    "whatsapp_template": "Modelos do WhatsApp",
    "link_handle": "Identificadores de links de referência",
    "from_override": "Endereços de remetente de e-mail",
    "comment_posts": "Publicações para monitorar nos comentários",
}


#:
REQUIREMENT_KIND_HELP: dict[str, str] = {
    "tag": "Crie estas tags ou associe-as às que você já usa.",
    "custom_field": "Crie estes campos ou associe-os aos existentes. Não é possível alterar os tipos dos campos depois.",
    "sequence": "As novas sequências chegam vazias. Adicione as mensagens depois da importação.",
    "segment": "Escolha um filtro de contatos salvo existente.",
    "member": "Escolha quem será atribuído ou notificado. O padrão é você.",
    "flow": "Escolha para quais fluxos este fluxo encaminha.",
    "media": "Escolha uma imagem ou arquivo da sua biblioteca, ou cole um link para usar.",
    "platform": "Escolha uma conta para cada gatilho. Cada conta pode incluir outros canais compatíveis.",
    "request_header": "Adicione seus próprios cabeçalhos. Os segredos foram removidos da exportação.",
    "whatsapp_template": "Verifique se estes modelos aprovados existem na sua conta do WhatsApp.",
    "link_handle": "O identificador público @ usado para criar o link foi removido ao gerar o arquivo.",
    "from_override": "O endereço de envio foi removido ao gerar o arquivo.",
    "comment_posts": "Informe as publicações que deseja monitorar. Se deixar em branco, o gatilho não será executado.",
}


#: The sentence under each section heading on the import review page. Beside the
#: labels deliberately: the two are keyed by the same requirement kinds, and a
#: new kind that got one and not the other would render a bare slug as a heading
#: or a heading with nothing under it.
REQUIREMENT_KIND_HELP: dict[str, str] = {
    "tag": ("Create these tags or match them to tags you already use."),
    "custom_field": ("Create these fields or match them to existing ones. Field types cannot be changed later."),
    "sequence": ("New sequences arrive empty. Add their messages after importing."),
    "segment": "Choose an existing saved contact filter.",
    "member": "Choose who gets assigned or notified. Defaults to you.",
    "flow": "Choose the flows this one hands over to.",
    "media": "Pick an image or file from your library, or paste a link to use instead.",
    "platform": ("Choose an account for each trigger. Every account may include other supported channels."),
    "request_header": "Add your own headers. The export removed any secrets.",
    "whatsapp_template": "Make sure these approved templates exist in your WhatsApp account.",
    "link_handle": "The public @handle a link was built from was stripped when the file was made.",
    "from_override": "The sending address was stripped when the file was made.",
    "comment_posts": ("Enter the posts to watch. Blank means no posts, so the trigger will not run."),
}


def card_contexts(workspace: Any, cards: Sequence[Any]) -> list[dict[str, Any]]:
    """Render-ready contexts for ``cards``, in the order given.

    The connections query runs once for the batch rather than once per card, so
    pass the slice you are going to show — the empty state shows four of the
    twenty-one, and reversing twenty-one URLs to throw seventeen away is work
    nobody asked for. No cards, no query: a deployment that ships none renders
    this page too.
    """
    from apps.flows.capabilities import connected_platforms

    if not cards:
        return []
    connected = frozenset(connected_platforms(workspace))
    return [_card_context(workspace.pk, card, connected) for card in cards]


def _card_context(workspace_id: Any, card: Any, connected: frozenset[str]) -> dict[str, Any]:
    """One card with its labels resolved and its start URL reversed.

    Labels come from the registries that already own them —
    ``REQUIREMENT_KIND_LABELS``, ``Platform``'s choices, and each trigger type's
    own ``TriggerSpec.label`` — rather than from a second table: the review step
    and the trigger panel already name these things, and a gallery that called a
    channel or a trigger something else would be the same feature speaking with
    two voices.

    Each platform carries its key as well as its label, because the card says
    whether that channel is connected and the template that renders it needs the
    key for the icon. ``connected`` is baked in here rather than passed to the
    template as an ambient variable: this partial is included from two different
    pages, and one of them would have had to remember to carry it.
    """
    from apps.common.platforms import Platform
    from apps.flows.triggers.registry import spec_for

    def platform_label(key: str) -> str:
        try:
            return str(Platform(key).label)
        except ValueError:
            return key

    def trigger_label(trigger_type: str) -> str:
        spec = spec_for(trigger_type)
        return spec.label if spec is not None else trigger_type

    return {
        "card": card,
        "platforms": [
            {"key": key, "label": platform_label(key), "connected": key in connected} for key in card.platforms
        ],
        "needs": [REQUIREMENT_KIND_LABELS.get(kind, kind) for kind in card.needs],
        "triggers": [trigger_label(trigger_type) for trigger_type in card.trigger_types],
        "start_url": reverse(
            "flows:template_start",
            kwargs={"workspace_id": workspace_id, "template_slug": card.slug},
        ),
    }
