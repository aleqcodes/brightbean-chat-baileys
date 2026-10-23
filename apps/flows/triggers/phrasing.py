"""Frases para leitura sobre os gatilhos de um fluxo.

O vocabulário da SPEC §10 é preciso e voltado a desenvolvedores: ``ref_url``,
``default_reply``, ``story_mention``. Os rótulos de :class:`TriggerType` são
melhores ("Novo seguidor"), mas ainda nomeiam o *mecanismo*, não o momento —
e uma lista de fluxos que diz "Palavra-chave · Comentário" informa como o
produto chama as coisas, não quando o fluxo é executado.

Este módulo responde, nas palavras de quem usa o produto: **quando este fluxo
começa?** "Quando alguém comenta em uma publicação." "Quando uma mensagem contém
'horário' ou 'devoluções'."

**Por que aqui, e não em TriggerType.** Esses rótulos são para administração e
desenvolvimento; aparecem em formulários, na API e em mensagens de erro, e devem
permanecer estáveis e literais. Esta é a cópia da interface, revisada no ritmo
do produto, não do schema. Uma segunda frase no enum misturaria os registros e
facilitaria escolher a frase errada.

**Por que há uma alternativa em vez de um erro.** Um tipo de gatilho sem frase
aqui — incluído por uma camada posterior — usa como alternativa o rótulo do
enum. A lista de fluxos não é o lugar para descobrir que uma migração chegou
sem texto de interface.
"""

from typing import Any

from apps.flows.triggers.types import TriggerType

__all__ = ["CAVEATS", "MAX_QUOTED_KEYWORDS", "describe_trigger", "describe_triggers", "sentence_case"]

#: How many keywords a sentence quotes before it gives up and counts.
#: Three is the point at which "a, b or c" stops reading as a phrase and starts
#: reading as a list.
MAX_QUOTED_KEYWORDS = 3

#: One phrase per trigger type, written to follow "This flow runs…".
_PHRASES: dict[str, str] = {
    TriggerType.KEYWORD: "quando alguém envia uma palavra-chave",
    TriggerType.COMMENT: "quando alguém comenta em uma publicação",
    TriggerType.STORY_MENTION: "quando alguém menciona você em um story",
    TriggerType.STORY_REPLY: "quando alguém responde ao seu story",
    TriggerType.FOLLOW: "quando alguém começa a seguir você",
    TriggerType.REF_URL: "quando alguém abre seu link ou escaneia seu QR code",
    TriggerType.DEFAULT_REPLY: "quando nenhuma outra regra corresponde",
    TriggerType.WELCOME: "quando alguém envia uma mensagem pela primeira vez",
    TriggerType.RULE: "quando uma mensagem corresponde às suas regras",
    TriggerType.API: "quando outro sistema solicita a execução",
}


#: Trigger types that cannot fire today, as a sentence of their own.
#:
#: A sentence rather than a clause, because it has to sit after a join it does
#: not control. As a clause it read "When someone follows you, which Instagram
#: does not support yet, so it will not run, or when someone comments" — three
#: commas and a dangling "or" — the moment a flow had a second trigger.
#:
#: Worded to fit both: "it" is the trigger just named when a flow has one, and
#: the new-follower trigger among several when it has more.
#:
#: ``TriggerSpec.unavailable`` says the same thing at the length a form can
#: afford. This one has to survive a truncated meta line beside "edited 2 hours
#: ago", and must still stop a reader, because the pill above it says "Live".
CAVEATS: dict[str, str] = {
    TriggerType.FOLLOW: "O Instagram ainda não oferece gatilhos para novos seguidores, então este fluxo não será executado.",
}


def _quoted_keywords(config: dict[str, Any]) -> str:
    """Palavras monitoradas por um gatilho de palavra-chave, em uma frase legível.

    Dois formatos chegam aqui. O gatilho de palavra-chave da SPEC §10 armazena
    ``{"keywords": [{"text": ..., "mode": ...}]}``; um gatilho de comentário
    armazena uma lista simples em ``include_keywords``. Ambos são lidos porque
    representam "palavras que iniciam este fluxo" para quem usa o produto, e não
    justificam uma ramificação no ponto de chamada.
    """
    words = [
        str(entry.get("text", "")).strip() if isinstance(entry, dict) else str(entry).strip()
        for entry in (config.get("keywords") or config.get("include_keywords") or [])
    ]
    words = [word for word in words if word]
    if not words:
        return ""
    if len(words) > MAX_QUOTED_KEYWORDS:
        return f"“{words[0]}” e mais {len(words) - 1}"
    if len(words) == 1:
        return f"“{words[0]}”"
    return ", ".join(f"“{word}”" for word in words[:-1]) + f" ou “{words[-1]}”"


def describe_trigger(trigger: Any) -> str:
    """Um gatilho, como fragmento de frase iniciado por "quando".

    Indica quando seria executado, nunca se pode ser executado: um gatilho que
    a plataforma nunca entrega é descrito aqui como qualquer outro, e
    :func:`describe_triggers` acrescenta :data:`CAVEATS` uma vez para o fluxo.
    """
    phrase = _PHRASES.get(trigger.type)
    if phrase is None:
        # A type added without copy. Its enum label is wrong in register but
        # right in substance, which beats an empty line on a list page.
        return f"quando um gatilho de {trigger.get_type_display().lower()} é acionado"

    config = trigger.config_json if isinstance(trigger.config_json, dict) else {}
    quoted = _quoted_keywords(config)
    if quoted and trigger.type == TriggerType.KEYWORD:
        phrase = f"quando alguém envia {quoted}"
    elif quoted and trigger.type == TriggerType.COMMENT:
        phrase = f"quando alguém comenta {quoted}"

    return phrase


def sentence_case(phrase: str) -> str:
    """Coloca em maiúscula a primeira letra sem alterar o restante.

    Não usa ``str.capitalize()``, que converte todo o restante para minúsculas:
    um gatilho de palavra-chave que exibe "Black Friday" viraria
    "black friday", alterando silenciosamente um termo escolhido pelo espaço de
    trabalho; o mesmo aconteceria com qualquer nome de marca citado.
    """
    return phrase[:1].upper() + phrase[1:]

def describe_triggers(triggers: list[Any]) -> str:
    """Todos os gatilhos de um fluxo em uma única frase.

    A ausência de gatilhos não significa "sem descrição", mas é um aviso que
    vale a pena ler: um fluxo sem gatilho nunca será executado. Informar isso na
    lista permite perceber o problema antes de se perguntar por que nada ocorreu.

    Com mais de dois gatilhos, a frase deixa de listá-los e passa a contá-los —
    três orações iniciadas por "quando", unidas por "ou", formariam um parágrafo,
    não uma linha.
    """
    enabled = [t for t in triggers if getattr(t, "enabled", True)]
    if not enabled:
        return "Nenhum gatilho foi configurado; adicione um para executar este fluxo"
    if len(enabled) == 1:
        sentence = sentence_case(describe_trigger(enabled[0]))
    elif len(enabled) == 2:
        sentence = f"{sentence_case(describe_trigger(enabled[0]))}, ou {describe_trigger(enabled[1])}"
    else:
        sentence = f"{sentence_case(describe_trigger(enabled[0]))} e mais {len(enabled) - 1} gatilhos"

    # Appended once, however many triggers there are, and de-duplicated: two
    # trigger types blocked for the same reason should say it once.
    notes = dict.fromkeys(note for t in enabled if (note := CAVEATS.get(t.type)))
    return " ".join([sentence + "." if notes else sentence, *notes])
