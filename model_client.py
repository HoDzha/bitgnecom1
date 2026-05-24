from __future__ import annotations

import os
from typing import Protocol

from pydantic import BaseModel

from codex_oauth_client import (
    CodexOAuthClient,
    DEFAULT_CODEX_MODEL,
    get_codex_auth_source,
    has_codex_oauth_session,
)
from openai_client import create_openai_client, describe_openai_auth_source, has_openai_credentials


class StructuredModelClient(Protocol):
    def parse_structured(
        self,
        messages: list[dict],
        response_model: type[BaseModel],
        model: str,
        max_completion_tokens: int = 16384,
    ) -> BaseModel: ...


class OpenAIChatClient:
    def __init__(self) -> None:
        self.client = create_openai_client()

    def parse_structured(
        self,
        messages: list[dict],
        response_model: type[BaseModel],
        model: str,
        max_completion_tokens: int = 16384,
    ) -> BaseModel:
        response = self.client.beta.chat.completions.parse(
            model=model or os.getenv("MODEL_ID") or "gpt-5.4",
            response_format=response_model,
            messages=messages,
            max_completion_tokens=max_completion_tokens,
        )
        return response.choices[0].message.parsed


def get_model_adapter() -> str:
    adapter = (os.getenv("MODEL_ADAPTER") or "api_key").strip().lower()
    if adapter == "openai_sdk":
        return "api_key"
    return adapter


def get_model_id() -> str:
    adapter = get_model_adapter()
    if adapter == "codex_oauth":
        return (os.getenv("CODEX_MODEL_ID") or DEFAULT_CODEX_MODEL).strip()
    return (os.getenv("MODEL_ID") or "gpt-5.4").strip()


def validate_model_configuration() -> None:
    adapter = get_model_adapter()
    model_id = get_model_id()

    if adapter == "codex_oauth":
        allowed_prefixes = (
            "gpt-5",
            "gpt-5.3-codex",
            "gpt-5.4",
            "gpt-5.5",
            "codex-",
        )
        if not model_id.startswith(allowed_prefixes):
            raise RuntimeError(
                "MODEL_ADAPTER=codex_oauth requires an OpenAI/Codex model that "
                "works with the local Codex CLI ChatGPT session. "
                f"Current CODEX_MODEL_ID='{model_id}' is not compatible. "
                "Use something like 'gpt-5.3-codex' or switch MODEL_ADAPTER back to 'api_key'."
            )

    if adapter not in {"codex_oauth", "api_key"}:
        raise RuntimeError(
            f"Unsupported MODEL_ADAPTER='{adapter}'. Use 'codex_oauth' or 'api_key'."
        )


def create_structured_model_client() -> StructuredModelClient:
    adapter = get_model_adapter()
    if adapter == "codex_oauth":
        return CodexOAuthClient()
    return OpenAIChatClient()


def has_model_credentials() -> bool:
    adapter = get_model_adapter()
    if adapter == "codex_oauth":
        return has_codex_oauth_session()
    return has_openai_credentials()


def describe_model_auth_source() -> str:
    adapter = get_model_adapter()
    if adapter == "codex_oauth":
        return get_codex_auth_source()
    return describe_openai_auth_source()
