# Codex OAuth для Python-агента ecom1-bb

Этот референс описывает практический способ подключить OpenAI Codex к Python-агенту через ChatGPT OAuth по текущему паттерну `ecom1-bb`.

## Короткая схема

```text
Python agent
  -> ModelRouter(provider="openai")
  -> CodexOAuthAdapter
  -> codex exec --ephemeral --sandbox read-only ...
  -> локальный OAuth-кэш Codex CLI
  -> OpenAI Codex model
```

Ключевая идея: Python-агент не должен сам обменивать OAuth-код и не должен использовать ChatGPT OAuth token как `OPENAI_API_KEY`. В текущем варианте OAuth принадлежит Codex CLI. Агент вызывает `codex exec`, а CLI сам берет, обновляет и применяет сохраненную ChatGPT-сессию.

## Официальные источники

- [Codex CLI](https://developers.openai.com/codex/cli): установка через `npm i -g @openai/codex`, первый запуск предлагает вход через ChatGPT или API key.
- [Codex Authentication](https://developers.openai.com/codex/auth): Codex поддерживает вход через ChatGPT для subscription-доступа и API key для usage-based доступа; CLI по умолчанию ведет в ChatGPT sign-in, если нет валидной сессии.
- [Codex Non-interactive mode](https://developers.openai.com/codex/noninteractive): `codex exec` предназначен для скриптов, CI и headless-запусков; по умолчанию работает в read-only sandbox, поддерживает `--ephemeral`.
- [Codex exec command](https://www.mintlify.com/openai/codex/cli/exec): справка по `--output-last-message`, `--output-schema`, stdin через `-`.

## Как это сделано в ecom1-bb

Основные файлы:

- `models/model_routes.yaml` выбирает OpenAI-профиль:

```yaml
profiles:
  openai:
    adapter: codex_oauth
    auth: chatgpt_oauth
    solver_model: "gpt-5.3-codex"
```

- `models/router.py` создает `CodexOAuthAdapter`, когда `provider == "openai"` и `adapter == "codex_oauth"`.
- `models/codex_oauth_adapter.py` превращает `messages` в JSON-prompt и запускает `codex exec`.
- `agent/config.py` выбирает провайдера из `ECOM_PROVIDER`.

Текущий runtime-путь:

```python
router = ModelRouter(provider="openai")
solver = router.get_solver()  # CodexOAuthAdapter
result = solver.structured_output(messages, schema)
```

`models/chatgpt_oauth_auth.py` умеет валидировать JWT из `openai_token` или `OPENAI_ACCESS_TOKEN`, но дефолтный `CodexOAuthAdapter` сейчас не передает этот токен напрямую в OpenAI API. Это отдельный guard/helper, а не основной транспорт.

## Подготовка машины

1. Установить Codex CLI:

```powershell
npm i -g @openai/codex
```

2. Авторизоваться через ChatGPT OAuth:

```powershell
codex login
codex login status
```

Для headless/remote среды:

```powershell
codex login --device-auth
```

Для Enterprise automation, если workspace это разрешает, можно передать Codex access token:

```powershell
$env:CODEX_ACCESS_TOKEN | codex login --with-access-token
```

3. Если Python не находит правильный бинарь Codex, задать путь явно:

```powershell
$env:CODEX_CLI_BIN="C:\Users\<user>\AppData\Roaming\npm\codex.cmd"
```

В `ecom1-bb` адаптер также проверяет `~/.codex/.sandbox-bin/codex.exe`, затем `PATH`.

## Минимальный Python-адаптер

Паттерн такой же, как в `CodexOAuthAdapter`: писать prompt во stdin, финальный ответ забирать из файла.

```python
import json
import subprocess
import tempfile
from pathlib import Path


def codex_complete(messages: list[dict], model: str = "gpt-5.3-codex") -> str:
    prompt = json.dumps({"messages": messages}, ensure_ascii=False)
    output = Path(tempfile.NamedTemporaryFile(delete=False, suffix=".txt").name)

    args = [
        "codex",
        "exec",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "-c",
        'approval_policy="never"',
        "-m",
        model,
        "--output-last-message",
        str(output),
        "-",
    ]

    completed = subprocess.run(
        args,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)

    return output.read_text(encoding="utf-8").strip()
```

Для structured output добавить временный JSON Schema-файл и флаг `--output-schema <path>`. В `ecom1-bb` схема дополнительно нормализуется в strict-режим: у object-нод проставляются `required` и `additionalProperties: false`.

## Включение в ecom1-bb

Запуск OpenAI/Codex-профиля:

```powershell
$env:ECOM_PROVIDER="openai"
$env:ECOM_REQUIRE_LLM="1"
python -m agent.main
```

Если нужно поменять модель, обновить `models/model_routes.yaml`:

```yaml
profiles:
  openai:
    adapter: codex_oauth
    auth: chatgpt_oauth
    solver_model: "gpt-5.3-codex"
    verifier_model: "gpt-5.3-codex"
```

## Почему лучше вызывать Codex CLI, а не дергать OAuth token из Python

- Codex CLI официально поддерживает ChatGPT sign-in, token refresh и кэш логина.
- OAuth-кэш может лежать в `~/.codex/auth.json` или OS credential store; формат и refresh-логика не являются стабильным API для вашего Python-кода.
- `codex exec` уже дает нужный automation surface: stdin, `--output-last-message`, `--output-schema`, sandbox/approval flags.
- ChatGPT OAuth и OpenAI Platform API key имеют разные billing/admin/data-handling режимы. Не смешивайте их неявно.

## Безопасность и эксплуатация

- Не коммитить `~/.codex/auth.json`, `.env`, `openai_token`, `CODEX_ACCESS_TOKEN`.
- Для агента, который только анализирует данные, держать `--sandbox read-only`.
- Для задач с записью повышать sandbox точечно до `workspace-write`, а не до `danger-full-access`.
- Для CI по умолчанию официальная рекомендация - API key. ChatGPT/Codex access token уместен только для доверенных private runners или Enterprise-сценариев, где нужны workspace entitlements.
- На Windows, если npm wrapper конфликтует с PowerShell policy, задавать `CODEX_CLI_BIN` на `.cmd` или `.exe`.

## Диагностика

Проверить логин:

```powershell
codex login status
```

Проверить, что `codex exec` работает без Python:

```powershell
"Return OK only" | codex exec --ephemeral --sandbox read-only -m gpt-5.3-codex -
```

Проверить адаптер без реального вызова Codex:

```powershell
python -m pytest tests/unit/test_codex_oauth_adapter.py tests/unit/test_model_router.py
```

Типовые ошибки:

- `codex` не найден: установить CLI или задать `CODEX_CLI_BIN`.
- `not authenticated`: выполнить `codex login`.
- JSON не парсится: использовать `--output-last-message` вместе с `--output-schema`, не читать progress output как финальный ответ.
- Таймауты: увеличить `timeout_s` в `CodexOAuthAdapter`.
