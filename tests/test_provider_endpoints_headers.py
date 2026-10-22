"""Provider endpoint auth-header tests.

Covers ``build_headers`` for every provider: Anthropic (x-api-key + version
header), OpenAI-style providers (Bearer token), OpenRouter (Bearer + attribution
headers), and the no-key case.
"""
import pytest

from src import endpoint_resolver as er


def test_headers_anthropic_uses_x_api_key():
    h = er.build_headers("secret", "https://api.anthropic.com")
    assert h["x-api-key"] == "secret"
    assert h["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in h


def test_headers_anthropic_without_key_still_sends_version():
    h = er.build_headers(None, "https://api.anthropic.com")
    assert h["anthropic-version"] == "2023-06-01"
    assert "x-api-key" not in h


@pytest.mark.parametrize("base", [
    "https://api.openai.com/v1",
    "https://api.x.ai/v1",
    "https://api.deepseek.com",
    "https://api.groq.com/openai/v1",
    "https://integrate.api.nvidia.com/v1",
    "https://generativelanguage.googleapis.com/v1beta/openai",
])
def test_headers_openai_style_use_bearer(base):
    h = er.build_headers("secret", base)
    assert h["Authorization"] == "Bearer secret"
    assert "HTTP-Referer" not in h
    assert "x-api-key" not in h


def test_headers_openrouter_adds_attribution():
    h = er.build_headers("secret", "https://openrouter.ai/api/v1")
    assert h["Authorization"] == "Bearer secret"
    # OpenRouter ranks/labels apps via these headers.
    assert h["HTTP-Referer"].startswith("https://github.com/")
    assert h["X-OpenRouter-Title"] == "Odysseus"


def test_headers_omit_authorization_when_no_key():
    assert er.build_headers(None, "https://api.openai.com/v1") == {}


def test_headers_strip_quotes_from_pasted_key():
    # Copying a key out of a JSON/env file ("key": "nvapi-...") usually drags
    # the closing quote along; sent verbatim as `Bearer nvapi-..."` the
    # provider answers 403 "Authorization failed" even though the key is valid.
    base = "https://integrate.api.nvidia.com/v1"
    assert er.build_headers('nvapi-abc"', base)["Authorization"] == "Bearer nvapi-abc"
    assert er.build_headers('"nvapi-abc"', base)["Authorization"] == "Bearer nvapi-abc"
    assert er.build_headers("  nvapi-abc  ", base)["Authorization"] == "Bearer nvapi-abc"


@pytest.mark.parametrize("raw,expected", [
    ("nvapi-abc", "nvapi-abc"),
    ('"nvapi-abc"', "nvapi-abc"),
    ("'nvapi-abc'", "nvapi-abc"),
    ("`nvapi-abc`", "nvapi-abc"),
    ('nvapi-abc"', "nvapi-abc"),
    ("  nvapi-abc ", "nvapi-abc"),
    ("", ""),
])
def test_sanitize_api_key(raw, expected):
    assert er.sanitize_api_key(raw) == expected


def test_sanitize_api_key_passes_non_strings_through():
    assert er.sanitize_api_key(None) is None
