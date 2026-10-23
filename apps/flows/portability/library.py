"""The starter templates shipped in the repository, and how they are found.

``flow-templates/`` at the repository root holds flow templates anybody can
import — the seed of the shared library the issue describes, and the directory a
community pull request adds to. A test validates every file in it against the
importer and imports each into a clean workspace, so a template that stops
working is a red build rather than a download that fails for a stranger.

**Not** ``templates/``: that path is Django's own ``TEMPLATES["DIRS"]``
(``config/settings/base.py``), and putting JSON documents inside the HTML
template loader's search path would be a trap for the next person who wonders
why their template name resolves to a flow.

--------------------------------------------------------------------------
Cards, and why the description is not in the file
--------------------------------------------------------------------------

The gallery needs a sentence of English and a category per template, and the
envelope has a field for neither. It does not get one. ``f.obj`` sets
``additionalProperties: false`` on every object it builds and offers no opt-out
(``apps/flows/schema/fields.py``), so a document carrying a ``meta`` key is
refused by **every installation running today's release** — and these files are
downloaded from a repository and uploaded into other people's installs. It would
also break the byte-exact export round trip, since ``export_document`` would
never emit the key back.

So :class:`TemplateCard` **derives** every fact from the validated document —
the name from the entry flow, the platforms from the manifest's ``platform``
keys, the other requirement kinds from the rest of it — and the only
hand-written thing is :data:`TEMPLATE_COPY`, the one part no machine can infer.
Nothing that could drift is duplicated: the name on a card *is* the document's
name, and the badges *are* the manifest. Human copy in a module-level dict is
the house pattern already (``REQUIREMENT_KIND_LABELS`` in
``apps/flows/portability/cards.py``, ``FILTER_ICONS`` in
``apps/common/templatetags/common_extras.py``).

A file with no copy entry still gets a card with an empty summary, so a
self-hoster's drop-in is never invisible; a test asserts the two sets match both
ways so *ours* can never go missing.
"""

import hashlib
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

__all__ = [
    "LIBRARY_RELATIVE_PATH",
    "STARTER_CATEGORY",
    "gallery_entries",
    "SLUG_PATTERN",
    "TEMPLATE_COPY",
    "TemplateCard",
    "TemplateCopy",
    "library_path",
    "read_template",
    "template_card",
    "template_cards",
    "template_for_slug",
    "template_paths",
]

logger = logging.getLogger(__name__)

#: Where the shipped templates live, relative to the repository root.
LIBRARY_RELATIVE_PATH = Path("flow-templates")

#: What a filename's stem has to look like to be addressable as a URL segment.
#: Django's ``<slug:…>`` converter is the first gate and this is the second; a
#: test asserts every shipped filename passes, so a file the URL could never
#: reach is a red build rather than a card whose button 404s.
#:
#: ``\Z`` rather than ``$``: Python's ``$`` also matches immediately *before* a
#: trailing newline, so ``$`` here would accept ``"some-template\n"``. The stem
#: comparison in :func:`template_for_slug` would still refuse it, but a guard
#: whose whole job is refusing what does not belong should not need the next
#: check to cover for it.
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}\Z")


def library_path() -> Path:
    """Absolute path of the shipped template directory."""
    from django.conf import settings

    return Path(settings.BASE_DIR) / LIBRARY_RELATIVE_PATH


def template_paths() -> list[Path]:
    """Every shipped template, in a stable order.

    Sorted rather than in directory order: a test that iterates these reports
    its failures in the same sequence on every machine, and a filesystem's idea
    of order is not one.
    """
    directory = library_path()
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.json"))


def read_template(path: Path) -> tuple[dict[str, Any] | None, list[Any]]:
    """One shipped template, through the same front door an upload uses.

    Deliberately :func:`apps.flows.portability.imports.parse_and_validate` and
    not a shortcut: a file this repository ships gets exactly the scrutiny a
    stranger's does, which is what makes "CI validates the templates against the
    importer" a true statement rather than a weaker one about a different code
    path.
    """
    from apps.flows.portability.imports import parse_and_validate

    return parse_and_validate(path.read_bytes())


@dataclass(frozen=True)
class TemplateCopy:
    """The two things about a template a machine cannot work out for itself."""

    category: str
    summary: str


@dataclass(frozen=True)
class TemplateCard:
    """One shipped template, as the gallery shows it.

    Everything but :attr:`summary` and :attr:`category` is read off the validated
    document, so a card cannot disagree with the file it describes.
    """

    slug: str
    filename: str
    name: str
    summary: str
    category: str
    platforms: tuple[str, ...]
    needs: tuple[str, ...]
    trigger_types: tuple[str, ...]
    flow_count: int
    step_count: int
    #: The template makes an outbound HTTP request when it runs. Worth saying on
    #: the card because it is the one thing installing a template does *on your
    #: behalf, to somebody else* — the rest of it only touches your workspace.
    calls_out: bool


#: The category for the handful of templates a first-time workspace is shown.
#: Named because two places select on it and a bare string in the second would
#: go quietly wrong if this dict were ever re-worded: the gallery's filter chips
#: and ``apps.flows.views._featured``.
STARTER_CATEGORY = "Inícios"

#: Keyed by filename stem. A template with no entry still gets a card; a stale
#: entry and a missing one are both caught by a test that compares this against
#: the directory in both directions.
TEMPLATE_COPY: dict[str, TemplateCopy] = {
    "collect-an-email-address": TemplateCopy(
        category="Crescer",
        summary=("Pede um endereço de e-mail, verifica se parece válido e o salva no contato antes de responder."),
    ),
    "event-reminder": TemplateCopy(
        category="Engajar",
        summary=("Inscreve alguém em um evento pelo Telegram e envia outra mensagem mais perto da data."),
    ),
    "feedback-after-a-purchase": TemplateCopy(
        category="Engajar",
        summary=("Espera o pedido chegar, pergunta como foi e encaminha a resposta conforme o que a pessoa disser."),
    ),
    "first-message-welcome": TemplateCopy(
        category="Inícios",
        summary=("A primeira mensagem que um novo contato do Telegram recebe, com um acompanhamento pouco depois."),
    ),
    "follow-up-an-unanswered-enquiry": TemplateCopy(
        category="Converter",
        summary=("Retoma duas vezes, com intervalos, um pedido de informação sem resposta e marca quem nunca respondeu."),
    ),
    "hand-over-to-a-person": TemplateCopy(
        category="Engajar",
        summary=("Tira a conversa da automação e a atribui a uma pessoa da equipe, com uma nota explicando o motivo."),
    ),
    "instagram-comment-affiliate-picks": TemplateCopy(
        category="Converter",
        summary=(
            "Um comentário na publicação envia uma galeria navegável de recomendações de afiliados, cada cartão com link direto."
        ),
    ),
    "instagram-comment-follow-to-unlock": TemplateCopy(
        category="Crescer",
        summary=("Pede que a pessoa siga o perfil antes de entregar o brinde e marca quem confirmar."),
    ),
    "instagram-comment-link-in-dm": TemplateCopy(
        category="Converter",
        summary=("A pessoa comenta, você responde publicamente e envia o link por DM. O clássico comentário para DM."),
    ),
    "instagram-comment-product-gallery": TemplateCopy(
        category="Converter",
        summary=("Envia toda a seleção em uma galeria e responde às duas perguntas que impedem a venda."),
    ),
    "instagram-comment-reel-to-product": TemplateCopy(
        category="Converter",
        summary=("Um Reel fez as pessoas perguntarem. Envie o produto por DM e marque o interesse."),
    ),
    "instagram-comment-rsvp": TemplateCopy(
        category="Converter",
        summary=(
            "Transforma “comente para participar” em uma confirmação de presença, com link para o calendário e uma etiqueta para futuras campanhas."
        ),
    ),
    "instagram-comment-to-discount-code": TemplateCopy(
        category="Converter",
        summary=("Envia o código de desconto por DM quando alguém comenta e faz um acompanhamento caso não seja usado."),
    ),
    "instagram-comment-to-dm-lead-magnet": TemplateCopy(
        category="Inícios",
        summary=("Uma DM acionada por comentário entrega um guia e coleta um endereço de e-mail."),
    ),
    "instagram-default-reply-autoresponder": TemplateCopy(
        category="Engajar",
        summary=(
            "Responde às DMs que ficaram sem resposta, cumprimenta as pessoas pelo nome e as encaminha para comprar, perguntar ou falar com alguém."
        ),
    ),
    "instagram-keyword-course-early-access": TemplateCopy(
        category="Converter",
        summary=("Uma palavra-chave inclui pessoas na lista de espera do lançamento e as marca para a campanha do dia."),
    ),
    "instagram-keyword-dm-to-sms": TemplateCopy(
        category="Crescer",
        summary=(
            "Transfere a conversa para SMS antes de fechar a janela de 24 horas do Instagram, com uma DM alternativa se a mensagem falhar."
        ),
    ),
    "instagram-keyword-email-capture": TemplateCopy(
        category="Crescer",
        summary=("Troca um download por um endereço de e-mail. A resposta registra o consentimento junto com ele."),
    ),
    "instagram-keyword-faq-hub": TemplateCopy(
        category="Engajar",
        summary=("Uma palavra-chave, um espaço central, quatro respostas e uma forma de falar com alguém."),
    ),
    "instagram-keyword-link-drop": TemplateCopy(
        category="Engajar",
        summary=("O jeito mais simples: uma palavra-chave na DM e o link enviado de volta."),
    ),
    "instagram-keyword-qualify-quiz": TemplateCopy(
        category="Engajar",
        summary=("Duas perguntas marcam as pessoas conforme seu estágio e enviam uma oferta diferente a cada grupo."),
    ),
    "instagram-keyword-sms-list": TemplateCopy(
        category="Crescer",
        summary=("Coleta números de telefone com o texto de consentimento exigido pelas regras de SMS."),
    ),
    "instagram-keyword-where-is-this-from": TemplateCopy(
        category="Engajar",
        summary=("Responde “de onde vem isso?” assim que a mensagem chega, com o produto e um link."),
    ),
    "instagram-keyword-youtube-subscribe": TemplateCopy(
        category="Crescer",
        summary=("Leva seu público do Instagram para o vídeo completo no YouTube."),
    ),
    "instagram-link-in-bio-capture": TemplateCopy(
        category="Crescer",
        summary=("O link na bio abre uma conversa que já sabe de onde a pessoa veio."),
    ),
    "instagram-price-question": TemplateCopy(
        category="Converter",
        summary=("Responde “quanto custa?” nos comentários por DM e pergunta o que a pessoa procura antes de informar o preço."),
    ),
    "instagram-story-collab-requests": TemplateCopy(
        category="Crescer",
        summary=("Organiza respostas sobre parcerias entre marcas e criadores, coleta os detalhes e marca o pedido."),
    ),
    "instagram-story-limited-time-offer": TemplateCopy(
        category="Converter",
        summary=("Envia o código do Story e lembra a pessoa uma vez antes de a oferta expirar."),
    ),
    "instagram-story-mention-thank-you": TemplateCopy(
        category="Engajar",
        summary=("Agradece a quem mencionou você em um story e retorna depois com uma oferta."),
    ),
    "instagram-story-reply-to-conversation": TemplateCopy(
        category="Engajar",
        summary=("Transforma uma resposta ao story em uma conversa de verdade, em vez de uma notificação sem resposta."),
    ),
    "messenger-comment-to-dm": TemplateCopy(
        category="Converter",
        summary=("Responde em particular a um comentário no Facebook, permitindo fazer uma pergunta de verdade."),
    ),
    "messenger-quote-request": TemplateCopy(
        category="Converter",
        summary=("Coleta, uma pergunta por vez, os três dados necessários para preparar um orçamento e salva cada resposta."),
    ),
    "messenger-welcome": TemplateCopy(
        category="Inícios",
        summary=("O que um novo contato no Messenger recebe: quatro mensagens curtas em vez de um texto enorme."),
    ),
    "out-of-hours-reply": TemplateCopy(
        category="Engajar",
        summary=("Responde fora do horário de atendimento informando quando você abrirá novamente, para ninguém ficar esperando."),
    ),
    "sms-appointment-reminder": TemplateCopy(
        category="Engajar",
        summary=("Envia um lembrete por SMS antes do compromisso e outro quando ele estiver próximo."),
    ),
    "sms-keyword-opt-in": TemplateCopy(
        category="Inícios",
        summary=("Inscrição por palavra-chave via SMS que registra o consentimento e marca a pessoa inscrita."),
    ),
    "sms-review-request": TemplateCopy(
        category="Engajar",
        summary=("Espera alguns dias e pede uma avaliação, parando de perguntar a quem já deixou uma."),
    ),
    "telegram-booking-enquiry": TemplateCopy(
        category="Converter",
        summary=("Recebe um pedido de reserva pelo Telegram e salva a data, o tamanho do grupo e o contato."),
    ),
    "telegram-support-triage": TemplateCopy(
        category="Engajar",
        summary=("Encaminha uma mensagem de suporte recebida para a fila certa e a marca para quem for atendê-la."),
    ),
    "telegram-welcome-and-faq": TemplateCopy(
        category="Inícios",
        summary=("Mensagem de boas-vindas no Telegram com menu de perguntas frequentes em três opções de resposta rápida."),
    ),
    "waitlist-signup": TemplateCopy(
        category="Crescer",
        summary=("Coleta um e-mail para a lista de espera e marca a pessoa para você enviar mensagens à lista depois."),
    ),
    "whatsapp-opening-hours": TemplateCopy(
        category="Engajar",
        summary=("Responde “vocês estão abertos?” com a informação correta para o dia da pergunta."),
    ),
    "whatsapp-order-status": TemplateCopy(
        category="Engajar",
        summary=("Pede o número do pedido, consulta o status e informa onde ele está."),
    ),
}


def template_for_slug(slug: str) -> Path | None:
    """The shipped template a URL segment names, or ``None``.

    **Never builds a path from the argument.** The candidate set comes from
    :func:`template_paths`, and ``slug`` is only ever compared for equality
    against a stem this module produced — so ``..``, an absolute path, a URL-
    encoded separator and a symlink all have nothing to act on, rather than being
    sanitised away and hoped about. Django's ``<slug:…>`` converter means most of
    those never reach the view at all; :data:`SLUG_PATTERN` stops the rest before
    the scan.
    """
    if not SLUG_PATTERN.match(slug or ""):
        return None
    return next((path for path in template_paths() if path.stem == slug), None)


def template_card(path: Path) -> TemplateCard | None:
    """One template as a card, or ``None`` if the file cannot be turned into one.

    ``None`` rather than an exception, for **both** halves of "cannot": a file
    that does not validate and a file that does not read. The gallery walks every
    file in a directory a self-hoster can drop things into, so one bad drop-in
    has to cost that template its card and nothing else — guarding only the parse
    would still let a permission bit or a disk error take down the whole page. A
    *shipped* file failing either way is our bug, which is why both are logged.
    """
    try:
        raw = path.read_bytes()
    except OSError as error:
        logger.warning("flow template %s could not be read and has no card: %s", path.name, error)
        return None
    return _card(str(path), hashlib.blake2b(raw, digest_size=16).hexdigest())


def template_cards() -> list[TemplateCard]:
    """Every shipped template as a card, in :func:`template_paths` order."""
    return [card for card in (template_card(path) for path in template_paths()) if card is not None]


@lru_cache(maxsize=256)
def _card(path_str: str, content_digest: str) -> TemplateCard | None:
    """The parse behind :func:`template_card`, memoized on the file's *content*.

    Twenty-odd ``parse_and_validate`` calls per page view is the kind of cost
    that only shows up under load, so the result is cached until the file
    changes. The key is a digest of the bytes rather than ``(mtime, size)``: an
    edit that keeps a file the same length — swapping a placeholder URL for one
    of equal length, fixing a typo — is invisible to mtime granularity on a
    filesystem that rounds it, and a stale card would then outlive the file it
    describes. Hashing costs microseconds against a full schema validation.

    Keyed on the path *string* as well, so a test pointing ``settings.BASE_DIR``
    at a ``tmp_path`` gets its own entries and needs no cache-clearing fixture.

    The re-read here is the price of ``lru_cache`` keying on every argument —
    passing the bytes in would cache up to ``MAX_DOCUMENT_BYTES`` per entry. It
    happens on a miss only, and it is guarded because the file can vanish between
    the digest and the parse.
    """
    path = Path(path_str)
    try:
        document, issues = read_template(path)
    except OSError as error:
        logger.warning("flow template %s could not be read and has no card: %s", path.name, error)
        return None
    if document is None:
        logger.warning(
            "flow template %s does not validate and has no card: %s",
            path.name,
            "; ".join(issue.message for issue in issues[:3]),
        )
        return None

    flows = document["flows"]
    entry = next((flow for flow in flows if flow["key"] == document["entry"]), flows[0])
    requirements = document["requirements"]
    copy = TEMPLATE_COPY.get(path.stem)

    return TemplateCard(
        slug=path.stem,
        filename=path.name,
        name=entry["name"],
        summary=copy.summary if copy else "",
        category=copy.category if copy else entry.get("folder", ""),
        platforms=tuple(item["key"] for item in requirements.get("platform", [])),
        # Sorted for a stable badge order; ``platform`` is dropped because it is
        # already its own row on the card.
        needs=tuple(sorted(kind for kind, items in requirements.items() if items and kind != "platform")),
        trigger_types=tuple(dict.fromkeys(t["type"] for flow in flows for t in flow["triggers"])),
        flow_count=len(flows),
        step_count=sum(_steps_in(flow["graph"]) for flow in flows),
        calls_out=_calls_out(document),
    )


def _calls_out(document: dict[str, Any]) -> bool:
    """Whether running this template makes an outbound HTTP request.

    Both halves are needed. ``request_header`` in the manifest catches a template
    whose call carries a header the importer must ask for, and the node sweep
    catches one that calls out with no header at all — an export strips header
    *values*, so a template can legitimately arrive with an ``external_request``
    node and nothing in ``requirements`` to show for it.
    """
    if document["requirements"].get("request_header"):
        return True
    return any(
        node.get("type") == "external_request" for flow in document["flows"] for node in flow["graph"].get("nodes", [])
    )


def _steps_in(graph: dict[str, Any]) -> int:
    """Nodes that actually run.

    ``note`` nodes are ``annotation=True``: they take no part in routing and are
    excluded from the entry-node count (``_routable`` in
    ``apps/flows/schema/validation.py``). Counting them would tell somebody a
    one-message template is two steps long, which is exactly the templates that
    ship a note — all of them.
    """
    from apps.flows.schema import node_spec

    return sum(1 for node in graph["nodes"] if not (spec := node_spec(node["type"])) or not spec.annotation)


# ---------------------------------------------------------------------------
# The compact tile shape
# ---------------------------------------------------------------------------


def gallery_entries() -> list[dict[str, Any]]:
    """The shipped templates as the Home and flow-list tiles read them.

    A projection of :func:`template_cards`, not a second walk of the directory.
    The tiles want five facts and the gallery card wants nine, but there is only
    one library and only one definition of what a card says about it — deriving
    the smaller shape from the larger is what stops the two pages disagreeing
    about how many templates ship.

    Cached on the directory's own fingerprint rather than recomputed. Home and
    the import review page both call this per render, and ``template_cards()``
    reads and digests every file on disk *before* it can consult the per-card
    cache — so without this the two most-visited pages in the product paid
    forty-odd file reads each time. Keyed on (name, mtime, size) per file rather
    than held for the life of the process, so a template edited on disk still
    shows through, which the library's own cache guarantees and the tests rely
    on.

    Dicts rather than the dataclass because the tile template indexes them and
    a caller may sort or slice, which a shared frozen instance would make
    everybody's business.
    """
    # A fresh dict *and* a fresh platforms list per call: dict() is shallow, so
    # handing back the cached list would let one caller's sort or append reach
    # every later render.
    return [{**entry, "platforms": list(entry["platforms"])} for entry in _gallery_entries(_library_fingerprint())]


def _library_fingerprint() -> tuple[Any, ...]:
    """What the gallery cache keys on: every file's name, mtime and size.

    Cheap next to reading and hashing each file, and it moves for the edits that
    matter — a new template, a deleted one, or a changed one. A same-size
    same-mtime rewrite is invisible here, which is exactly the case
    :func:`_card` keys on a content digest to catch; this cache sits in front of
    that one rather than replacing it.
    """
    entries: list[Any] = []
    for path in template_paths():
        try:
            stat = path.stat()
        except OSError:
            entries.append((path.name, None))
        else:
            entries.append((path.name, stat.st_mtime_ns, stat.st_size))
    return tuple(entries)


@lru_cache(maxsize=4)
def _gallery_entries(fingerprint: tuple[Any, ...]) -> tuple[dict[str, Any], ...]:
    """The projection itself, computed once per state of the directory."""
    return tuple(
        {
            "slug": card.slug,
            "name": card.name,
            "category": card.category,
            "platforms": tuple(card.platforms),
            "platform_label": _platform_label(list(card.platforms)),
            "steps": card.step_count,
        }
        for card in template_cards()
    )


def _platform_label(platforms: list[str]) -> str:
    """ "instagram" -> "Instagram"; two -> "Instagram and Messenger"; none -> "Any channel"."""
    from apps.common.platforms import Platform

    names = []
    for platform in platforms:
        try:
            names.append(str(Platform(platform).label))
        except ValueError:
            names.append(platform)
    if not names:
        return "Any channel"
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + f" and {names[-1]}"
