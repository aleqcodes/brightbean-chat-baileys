"""Forms for connecting WhatsApp and authoring its templates (issue #19).

Separate from :mod:`apps.channels.forms`, which ships the platform-agnostic
frame and says in its own docstring that each platform's real connect flow
belongs to that platform's issue — "a BotFather token pasted into a field, a
Meta OAuth round trip, Twilio credentials plus a number" are not one form.

Two things these forms are strict about, both from SECURITY-BASELINE §7:

* **Every field is declared.** The template body is a JSON document at rest, but
  it is never *posted* as one. An operator fills named fields and
  :meth:`WhatsAppTemplateForm.body_structure` assembles the document, so there
  is no path by which a hand-crafted POST can put an unknown key into it.
* **Limits are Meta's, checked here.** A body over 1024 characters or a name
  with a capital letter is refused in the form, where the operator is looking,
  rather than by a Graph error one round trip later.
"""

from decimal import Decimal
from typing import Any

from django import forms

from apps.channels.models import (
    ChannelConnection,
    ConnectionStatus,
    WhatsAppCostHint,
    WhatsAppTemplate,
)
from apps.channels.whatsapp_templates import (
    _SLOT_RE,
    MAX_BODY_CHARS,
    MAX_BUTTON_TEXT_CHARS,
    MAX_FOOTER_CHARS,
    MAX_HEADER_CHARS,
    TEMPLATE_NAME_PATTERN,
)
from apps.common.platforms import Platform

__all__ = ["WhatsAppConnectForm", "WhatsAppCostHintForm", "WhatsAppTemplateForm"]

#: How many quick-reply buttons a template may carry. Meta's own cap, and the
#: same number the adapter can render in a session message.
QUICK_REPLY_SLOTS = 3


class WhatsAppConnectForm(forms.Form):
    """The three values a Cloud API connection needs (SPEC §6.5).

    No OAuth: this is the direct-from-Meta path, so what an operator has is a
    permanent system-user token they generated in Business Manager. That makes
    the form simple and the *verification* the important part — see
    ``views_whatsapp.whatsapp_connect``, which proves the token against Meta
    before anything is written.
    """

    waba_id = forms.CharField(
        label="ID da conta do WhatsApp Business",
        max_length=64,
        help_text="No Business Manager → Contas do WhatsApp. Apenas dígitos.",
    )
    phone_number_id = forms.CharField(
        label="ID do número de telefone",
        max_length=64,
        help_text="ID da API do número, não o próprio número.",
    )
    access_token = forms.CharField(
        label="Token de acesso permanente",
        # A password widget, and autocomplete off: this value is a live
        # credential and must not end up in the browser's saved form data.
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off", "spellcheck": "false"}),
        help_text="Token de usuário do sistema com whatsapp_business_messaging e whatsapp_business_management.",
    )

    def clean_waba_id(self) -> str:
        return self._digits("waba_id")

    def clean_phone_number_id(self) -> str:
        return self._digits("phone_number_id")

    def _digits(self, field: str) -> str:
        value = (self.cleaned_data.get(field) or "").strip()
        if not value.isdigit():
            raise forms.ValidationError("Este é um ID numérico do Business Manager.")
        return value

    def clean_access_token(self) -> str:
        value = (self.cleaned_data.get("access_token") or "").strip()
        if not value:
            raise forms.ValidationError("Cole o token de usuário do sistema.")
        return value


class WhatsAppTemplateForm(forms.ModelForm):
    """Author one template as named fields, not as a JSON blob.

    The ``{{1}}``-style placeholders an operator types are Meta's numbering and
    stay literal here: nothing in this form renders them, and
    :func:`apps.channels.whatsapp_templates.preview` is what shows them filled
    in — through the one shared renderer, never a template engine
    (SECURITY-BASELINE §3).
    """

    header_text = forms.CharField(
        label="Cabeçalho",
        required=False,
        max_length=MAX_HEADER_CHARS,
        help_text=f"Opcional, até {MAX_HEADER_CHARS} caracteres. Pode conter {{{{1}}}}.",
    )
    body_text = forms.CharField(
        label="Corpo",
        widget=forms.Textarea(attrs={"rows": 5}),
        max_length=MAX_BODY_CHARS,
        help_text=f"Até {MAX_BODY_CHARS} caracteres. Use {{{{1}}}}, {{{{2}}}} … para variáveis.",
    )
    footer_text = forms.CharField(
        label="Rodapé",
        required=False,
        max_length=MAX_FOOTER_CHARS,
        help_text=f"Opcional, até {MAX_FOOTER_CHARS} caracteres. Não são permitidas variáveis aqui.",
    )
    url_button_text = forms.CharField(label="Texto do botão de link", required=False, max_length=MAX_BUTTON_TEXT_CHARS)
    url_button_url = forms.URLField(
        label="URL do botão de link",
        required=False,
        assume_scheme="https",
        help_text="Pode terminar com uma variável, por exemplo https://example.com/orders/{{1}}.",
    )

    class Meta:
        model = WhatsAppTemplate
        fields = ["channel_connection", "name", "language", "category"]
        labels = {"channel_connection": "Número do WhatsApp", "name": "Nome do modelo"}
        help_texts = {
            "name": "Use letras minúsculas, números e sublinhados. A Meta exibe este nome na fila de revisão.",
            "language": "Código de idioma da Meta, por exemplo en_US.",
        }

    def __init__(self, *args: Any, workspace: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        # Scoped, not filtered in the template: a ModelChoiceField whose
        # queryset spans every workspace would accept another tenant's
        # connection id from a hand-crafted POST and file the template against
        # it (SECURITY-BASELINE §1).
        self.fields["channel_connection"].queryset = (  # type: ignore[attr-defined]
            ChannelConnection.objects.for_workspace(workspace)
            .filter(platform=Platform.WHATSAPP.value)
            .exclude(status=ConnectionStatus.DISABLED)
            if workspace is not None
            else ChannelConnection.objects.none()
        )
        for index in range(QUICK_REPLY_SLOTS):
            self.fields[f"quick_reply_{index}"] = forms.CharField(
                label=f"Resposta rápida {index + 1}",
                required=False,
                max_length=MAX_BUTTON_TEXT_CHARS,
            )

        if self.instance and self.instance.pk:
            self._fill_from_instance()

    def _fill_from_instance(self) -> None:
        """Populate the flat fields from the stored document.

        Defensive about the shape: ``body_structure`` is a JSON column, and a
        row written by an earlier release or edited in the admin should open in
        the form rather than 500 it.
        """
        structure = self.instance.body_structure if isinstance(self.instance.body_structure, dict) else {}
        for key, field in (("header", "header_text"), ("body", "body_text"), ("footer", "footer_text")):
            part = structure.get(key)
            if isinstance(part, dict):
                self.fields[field].initial = part.get("text") or ""

        buttons = structure.get("buttons")
        quick_index = 0
        for button in buttons if isinstance(buttons, list) else []:
            if not isinstance(button, dict):
                continue
            if button.get("type") == "url":
                self.fields["url_button_text"].initial = button.get("text") or ""
                self.fields["url_button_url"].initial = button.get("url") or ""
            elif quick_index < QUICK_REPLY_SLOTS:
                self.fields[f"quick_reply_{quick_index}"].initial = button.get("text") or ""
                quick_index += 1

    def clean_footer_text(self) -> str:
        """Meta allows no variables in a footer, and the help text says so.

        Enforced rather than only described: without this the form accepted the
        draft, the operator submitted it, and Meta refused the template — one
        round trip later, in a place that does not explain which field was
        wrong.
        """
        value = (self.cleaned_data.get("footer_text") or "").strip()
        if value and _SLOT_RE.search(value):
            raise forms.ValidationError("O rodapé não pode conter variáveis. Mova-as para o corpo.")
        return value

    def clean_name(self) -> str:
        import re

        name = (self.cleaned_data.get("name") or "").strip().lower()
        if not re.match(TEMPLATE_NAME_PATTERN, name):
            raise forms.ValidationError("Use apenas letras minúsculas, números e sublinhados.")
        return name

    def clean(self) -> dict[str, Any]:
        # `super().clean()` is typed as optional because a subclass may return
        # None; ours does not, and `self.cleaned_data` is the same dict.
        super().clean()
        cleaned = self.cleaned_data
        text = cleaned.get("url_button_text") or ""
        url = cleaned.get("url_button_url") or ""
        if bool(text) != bool(url):
            raise forms.ValidationError("Um botão de link precisa de um texto e uma URL.")
        return cleaned

    def body_structure(self) -> dict[str, Any]:
        """Assemble the stored document from the cleaned fields.

        The only place a ``body_structure`` is built from user input. Keys are
        written here rather than copied from the POST, which is what makes the
        mass-assignment guard structural instead of a validation rule someone
        has to remember (SECURITY-BASELINE §7).
        """
        structure: dict[str, Any] = {"body": {"text": self.cleaned_data.get("body_text", "")}}
        header = self.cleaned_data.get("header_text")
        if header:
            structure["header"] = {"format": "text", "text": header}
        footer = self.cleaned_data.get("footer_text")
        if footer:
            structure["footer"] = {"text": footer}

        buttons: list[dict[str, str]] = [
            {"type": "quick_reply", "text": label}
            for label in (self.cleaned_data.get(f"quick_reply_{index}") for index in range(QUICK_REPLY_SLOTS))
            if label
        ]
        if self.cleaned_data.get("url_button_url"):
            buttons.append(
                {
                    "type": "url",
                    "text": self.cleaned_data["url_button_text"],
                    "url": self.cleaned_data["url_button_url"],
                }
            )
        if buttons:
            structure["buttons"] = buttons
        return structure


class WhatsAppCostHintForm(forms.ModelForm):
    """Per-category price estimates, for display only (SPEC §6.5, §22).

    Nothing meters. These numbers are multiplied by a recipient count in a
    composer and shown to a person; the bill still arrives from Meta.
    """

    class Meta:
        model = WhatsAppCostHint
        fields = ["currency", "marketing", "utility", "authentication"]
        labels = {
            "marketing": "Marketing, por mensagem",
            "utility": "Utilidade, por mensagem",
            "authentication": "Autenticação, por mensagem",
        }

    def clean_currency(self) -> str:
        value = (self.cleaned_data.get("currency") or "").strip().upper()
        if len(value) != 3 or not value.isalpha():
            raise forms.ValidationError("Use um código ISO 4217 de três letras, por exemplo USD.")
        return value

    def _clean_amount(self, field: str) -> Decimal:
        value = self.cleaned_data.get(field)
        if value is None:
            return Decimal("0")
        if value < 0:
            raise forms.ValidationError("O preço não pode ser negativo.")
        return value

    def clean_marketing(self) -> Decimal:
        return self._clean_amount("marketing")

    def clean_utility(self) -> Decimal:
        return self._clean_amount("utility")

    def clean_authentication(self) -> Decimal:
        return self._clean_amount("authentication")
