from django.conf import settings
from django.http import HttpResponse
from django.test import RequestFactory
from django.utils import translation
from django.middleware.locale import LocaleMiddleware


def test_browser_english_does_not_override_the_pt_br_app_locale() -> None:
    assert settings.LANGUAGE_CODE == "pt-br"
    assert settings.LANGUAGES == [("pt-br", "Português (Brasil)")]

    request = RequestFactory().get("/", HTTP_ACCEPT_LANGUAGE="en-US,en;q=0.9")
    with translation.override(None):
        response = LocaleMiddleware(lambda _request: HttpResponse())(request)
        assert request.LANGUAGE_CODE == "pt-br"
        assert translation.get_language() == "pt-br"
        assert response["Content-Language"] == "pt-br"
