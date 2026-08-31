from types import SimpleNamespace

import pytest

from personal_os.ai_provider import (
    CAPTURE_MODEL_ENV_VAR,
    CAPTURE_PROVIDER_ENV_VAR,
    DEFAULT_GROQ_BASE_URL,
    GROQ_API_KEY_ENV_VAR,
    GROQ_BASE_URL_ENV_VAR,
    OPENAI_API_KEY_ENV_VAR,
    RECOMMEND_MODEL_ENV_VAR,
    RECOMMEND_PROVIDER_ENV_VAR,
    InferenceProvider,
    ResponsesProviderConfig,
    build_responses_client,
    resolve_capture_provider,
    resolve_recommendation_provider,
)
from personal_os.config import ConfigurationError


def test_openai_capture_configuration() -> None:
    config = resolve_capture_provider({
        CAPTURE_PROVIDER_ENV_VAR: "openai",
        CAPTURE_MODEL_ENV_VAR: "gpt-test",
        OPENAI_API_KEY_ENV_VAR: "test-openai-key",
    })
    assert config.provider is InferenceProvider.OPENAI
    assert config.model == "gpt-test"
    assert config.api_key == "test-openai-key"
    assert config.base_url is None
    assert "test-openai-key" not in repr(config)


def test_groq_recommendation_configuration_uses_official_base_url() -> None:
    config = resolve_recommendation_provider({
        RECOMMEND_PROVIDER_ENV_VAR: "groq",
        RECOMMEND_MODEL_ENV_VAR: "openai/gpt-oss-20b",
        GROQ_API_KEY_ENV_VAR: "test-groq-key",
    })
    assert config.provider is InferenceProvider.GROQ
    assert config.model == "openai/gpt-oss-20b"
    assert config.api_key == "test-groq-key"
    assert config.base_url == DEFAULT_GROQ_BASE_URL


def test_groq_base_url_override_is_explicit() -> None:
    config = resolve_capture_provider({
        CAPTURE_PROVIDER_ENV_VAR: "groq",
        CAPTURE_MODEL_ENV_VAR: "openai/gpt-oss-120b",
        GROQ_API_KEY_ENV_VAR: "test-groq-key",
        GROQ_BASE_URL_ENV_VAR: "https://groq-proxy.example/v1",
    })
    assert config.base_url == "https://groq-proxy.example/v1"


@pytest.mark.parametrize(
    "environment,match",
    [
        ({}, CAPTURE_PROVIDER_ENV_VAR),
        ({CAPTURE_PROVIDER_ENV_VAR: "other"}, "openai.*groq"),
        ({CAPTURE_PROVIDER_ENV_VAR: "openai"}, CAPTURE_MODEL_ENV_VAR),
        ({CAPTURE_PROVIDER_ENV_VAR: "openai", CAPTURE_MODEL_ENV_VAR: "m"}, OPENAI_API_KEY_ENV_VAR),
        ({CAPTURE_PROVIDER_ENV_VAR: "groq", CAPTURE_MODEL_ENV_VAR: "m"}, GROQ_API_KEY_ENV_VAR),
        ({CAPTURE_PROVIDER_ENV_VAR: "groq", CAPTURE_MODEL_ENV_VAR: "m", GROQ_API_KEY_ENV_VAR: "k", GROQ_BASE_URL_ENV_VAR: " "}, GROQ_BASE_URL_ENV_VAR),
        ({CAPTURE_PROVIDER_ENV_VAR: "groq", CAPTURE_MODEL_ENV_VAR: "m", GROQ_API_KEY_ENV_VAR: "k", GROQ_BASE_URL_ENV_VAR: "file:///tmp/groq"}, "HTTP"),
    ],
)
def test_missing_or_invalid_configuration_fails_closed(
    environment: dict[str, str], match: str
) -> None:
    with pytest.raises(ConfigurationError, match=match):
        resolve_capture_provider(environment)


def test_client_construction_passes_provider_specific_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_openai(**kwargs: str) -> object:
        calls.append(kwargs)
        return SimpleNamespace(marker="client")

    monkeypatch.setattr("openai.OpenAI", fake_openai)
    groq = ResponsesProviderConfig(
        InferenceProvider.GROQ,
        "openai/gpt-oss-20b",
        "test-groq-key",
        DEFAULT_GROQ_BASE_URL,
    )
    openai = ResponsesProviderConfig(
        InferenceProvider.OPENAI, "gpt-test", "test-openai-key"
    )

    assert build_responses_client(groq).marker == "client"
    assert build_responses_client(openai).marker == "client"
    assert calls == [
        {"api_key": "test-groq-key", "base_url": DEFAULT_GROQ_BASE_URL},
        {"api_key": "test-openai-key"},
    ]
