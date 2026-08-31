"""Explicit configuration for supported Responses API inference providers."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from personal_os.config import ConfigurationError

CAPTURE_PROVIDER_ENV_VAR = "PERSONAL_OS_CAPTURE_PROVIDER"
RECOMMEND_PROVIDER_ENV_VAR = "PERSONAL_OS_RECOMMEND_PROVIDER"
CAPTURE_MODEL_ENV_VAR = "PERSONAL_OS_CAPTURE_MODEL"
RECOMMEND_MODEL_ENV_VAR = "PERSONAL_OS_RECOMMEND_MODEL"
OPENAI_API_KEY_ENV_VAR = "OPENAI_API_KEY"
GROQ_API_KEY_ENV_VAR = "GROQ_API_KEY"
GROQ_BASE_URL_ENV_VAR = "PERSONAL_OS_GROQ_BASE_URL"
DEFAULT_GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class InferenceProvider(StrEnum):
    OPENAI = "openai"
    GROQ = "groq"


@dataclass(frozen=True, slots=True)
class ResponsesProviderConfig:
    provider: InferenceProvider
    model: str
    api_key: str = field(repr=False)
    base_url: str | None = None


def resolve_capture_provider(
    environ: Mapping[str, str] | None = None,
) -> ResponsesProviderConfig:
    return _resolve_provider(
        CAPTURE_PROVIDER_ENV_VAR, CAPTURE_MODEL_ENV_VAR, environ
    )


def resolve_recommendation_provider(
    environ: Mapping[str, str] | None = None,
) -> ResponsesProviderConfig:
    return _resolve_provider(
        RECOMMEND_PROVIDER_ENV_VAR, RECOMMEND_MODEL_ENV_VAR, environ
    )


def _resolve_provider(
    provider_variable: str,
    model_variable: str,
    environ: Mapping[str, str] | None,
) -> ResponsesProviderConfig:
    environment = os.environ if environ is None else environ
    raw_provider = environment.get(provider_variable)
    if raw_provider is None or not raw_provider.strip():
        raise ConfigurationError(f"{provider_variable} is not configured")
    try:
        provider = InferenceProvider(raw_provider)
    except ValueError as exc:
        raise ConfigurationError(
            f"{provider_variable} must be 'openai' or 'groq'"
        ) from exc

    model = environment.get(model_variable)
    if model is None or not model.strip():
        raise ConfigurationError(f"{model_variable} is not configured")

    key_variable = (
        OPENAI_API_KEY_ENV_VAR
        if provider is InferenceProvider.OPENAI
        else GROQ_API_KEY_ENV_VAR
    )
    api_key = environment.get(key_variable)
    if api_key is None or not api_key.strip():
        raise ConfigurationError(f"{key_variable} is not configured")

    base_url = None
    if provider is InferenceProvider.GROQ:
        base_url = environment.get(GROQ_BASE_URL_ENV_VAR, DEFAULT_GROQ_BASE_URL)
        if not base_url.strip():
            raise ConfigurationError(f"{GROQ_BASE_URL_ENV_VAR} must not be empty")
        if not base_url.startswith(("https://", "http://")):
            raise ConfigurationError(
                f"{GROQ_BASE_URL_ENV_VAR} must be an HTTP(S) URL"
            )
    return ResponsesProviderConfig(provider, model, api_key, base_url)


def build_responses_client(config: ResponsesProviderConfig) -> object:
    """Construct the configured OpenAI SDK client only at inference time."""

    from openai import OpenAI

    kwargs: dict[str, str] = {"api_key": config.api_key}
    if config.base_url is not None:
        kwargs["base_url"] = config.base_url
    return OpenAI(**kwargs)
