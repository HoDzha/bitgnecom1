from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel

DEFAULT_CODEX_MODEL = "gpt-5.3-codex"


def _candidate_bins() -> list[Path]:
    candidates: list[Path] = []
    env_bin = os.getenv("CODEX_CLI_BIN")
    if env_bin:
        candidates.append(Path(env_bin))

    home = Path.home()
    candidates.extend(
        [
            home / ".codex" / ".sandbox-bin" / "codex.exe",
            home / "AppData" / "Roaming" / "npm" / "codex.cmd",
            home / "AppData" / "Roaming" / "npm" / "codex.exe",
        ]
    )
    return candidates


def resolve_codex_cli_bin() -> str:
    for candidate in _candidate_bins():
        if candidate.exists():
            return str(candidate)

    for name in ("codex.cmd", "codex.exe", "codex"):
        path = shutil.which(name)
        if path:
            return path

    raise RuntimeError(
        "Codex CLI was not found. Install it with `npm i -g @openai/codex` "
        "or set CODEX_CLI_BIN."
    )


def has_codex_cli() -> bool:
    try:
        resolve_codex_cli_bin()
    except RuntimeError:
        return False
    return True


def get_codex_auth_source() -> str:
    return "codex-cli:chatgpt-oauth"


def has_codex_oauth_session() -> bool:
    if not has_codex_cli():
        return False

    try:
        completed = subprocess.run(
            [resolve_codex_cli_bin(), "login", "status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
    except OSError:
        return False

    combined = f"{completed.stdout}\n{completed.stderr}"
    return completed.returncode == 0 and "Logged in using ChatGPT" in combined


def _make_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return schema

    schema = dict(schema)
    for key in ("properties", "$defs", "definitions", "patternProperties"):
        if key in schema and isinstance(schema[key], dict):
            schema[key] = {
                child_key: _make_strict_schema(child_value)
                for child_key, child_value in schema[key].items()
            }

    for key in ("items", "additionalProperties", "contains", "if", "then", "else", "not"):
        if key in schema and isinstance(schema[key], dict):
            schema[key] = _make_strict_schema(schema[key])

    for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
        if key in schema and isinstance(schema[key], list):
            schema[key] = [_make_strict_schema(item) for item in schema[key]]

    if schema.get("type") == "object" and "properties" in schema:
        schema["required"] = list(schema["properties"].keys())
        schema["additionalProperties"] = False

    return schema


def _messages_to_prompt(messages: list[dict[str, Any]]) -> str:
    return (
        "You are a structured-output reasoning backend for a Python ecommerce agent.\n"
        "Read the conversation messages below and produce the next assistant response.\n"
        "Your final response must satisfy the provided JSON schema exactly.\n"
        "Do not include markdown fences or commentary outside the schema output.\n\n"
        "Conversation messages as JSON:\n"
        f"{json.dumps(messages, ensure_ascii=False, indent=2)}\n"
    )


def _codex_subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in (
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_ACCESS_TOKEN",
        "OPENAI_ORG_ID",
        "OPENAI_PROJECT_ID",
    ):
        env.pop(key, None)
    return env


class CodexOAuthClient:
    def __init__(self) -> None:
        self.cli_bin = resolve_codex_cli_bin()
        self.timeout_s = int(os.getenv("CODEX_TIMEOUT_S") or "240")

    def parse_structured(
        self,
        messages: list[dict[str, Any]],
        response_model: type[BaseModel],
        model: str,
        max_completion_tokens: int = 16384,
    ) -> BaseModel:
        del max_completion_tokens

        prompt = _messages_to_prompt(messages)
        schema = _make_strict_schema(response_model.model_json_schema())

        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".json") as schema_file:
            json.dump(schema, schema_file, ensure_ascii=False)
            schema_path = schema_file.name

        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".txt") as output_file:
            output_path = output_file.name

        args = [
            self.cli_bin,
            "exec",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "-c",
            'approval_policy="never"',
            "-m",
            model or os.getenv("MODEL_ID") or DEFAULT_CODEX_MODEL,
            "--output-schema",
            schema_path,
            "--output-last-message",
            output_path,
            "--color",
            "never",
            "-",
        ]

        completed = subprocess.run(
            args,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout_s,
            check=False,
            env=_codex_subprocess_env(),
        )
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout).strip())

        raw = Path(output_path).read_text(encoding="utf-8").strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:].strip()

        return response_model.model_validate_json(raw)
