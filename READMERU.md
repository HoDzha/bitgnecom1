# ECOM1 Agent

Python-агент для бенчмарка BitGN `bitgn/ecom1-dev`.

Проект специально остаётся компактным, но уже содержит несколько важных для
ECOM1 ограничителей:

- одна агентная сессия на один trial
- узкий runtime tool surface
- workflow-aware prompt guidance
- консервативные trust boundaries между policy и недоверенным контентом
- автоматическая очистка grounding refs под scoring BitGN
- подробный вывод в консоль и per-run логи
- опциональный Codex CLI transport через ChatGPT OAuth

## Текущее состояние

Агент подключён к официальному runtime BitGN и уже успешно проходит `t01` на
`bitgn/ecom1-dev`.

## Использованные источники

- ECOM1 docs из `bitgn/challenges`
- BitGN Insights по лучшим практикам PAC1
- официальный sample-agent интерфейс из `bitgn/sample-agents/ecom-py`
- локальный паттерн auth из `pac1-py` для загрузки секрета из Windows Credential Manager

## Настройка

1. Положить `BITGN_API_KEY` в `.env`
2. Положить настройки провайдера в `.env`
3. Сохранить OpenAI-compatible секрет в Windows Credential Manager под именем `ecom1-openai`
4. Установить зависимости через `uv sync`
5. Запустить `uv run python main.py t01`

## Пример `.env`

```env
BITGN_API_KEY=bgn-...
BENCH_ID=bitgn/ecom1-dev
MODEL_ADAPTER=codex_oauth
CODEX_MODEL_ID=gpt-5.3-codex
RUN_NAME=ECOM1 Rails Agent
```

Или для OpenAI-compatible провайдера:

```env
BITGN_API_KEY=bgn-...
BENCH_ID=bitgn/ecom1-dev
MODEL_ADAPTER=api_key
OPENAI_BASE_URL=https://routerai.ru/api/v1
MODEL_ID=mistralai/mistral-medium-3-5
RUN_NAME=ECOM1 Rails Agent
```

## Команды запуска

- Весь benchmark: `uv run python main.py`
- Одна задача: `uv run python main.py t01`
- Несколько задач: `uv run python main.py t01 t02 t03`

## Переменные окружения

- `BITGN_API_KEY`: ключ BitGN
- `BITGN_HOST`: по умолчанию `https://api.bitgn.com`
- `BENCH_ID` или `BENCHMARK_ID`: по умолчанию `bitgn/ecom1-dev`
- `MODEL_ID`: имя модели для пути через API key/OpenAI-compatible provider
- `CODEX_MODEL_ID`: имя модели для пути `codex_oauth`
- `MODEL_ADAPTER`: `codex_oauth` или `api_key`
- `OPENAI_BASE_URL`: base URL провайдера, например `https://routerai.ru/api/v1`
- `OPENAI_CREDENTIAL_TARGET`: имя записи в Windows Credential Manager, по умолчанию `ecom1-openai`
- `RUN_NAME`: имя run в BitGN
- `HINT`: дополнительная системная подсказка

## Codex OAuth

Теперь проект поддерживает тот же ChatGPT OAuth-паттерн, что и в reference:

- Python agent
- `CodexOAuthClient`
- `codex exec --ephemeral --sandbox read-only`
- локальная OAuth-сессия Codex CLI
- Codex model

Как использовать:

1. Установить Codex CLI: `npm i -g @openai/codex`
2. Один раз залогиниться: `codex login`
3. Проверить сессию: `codex login status`
4. Поставить `MODEL_ADAPTER=codex_oauth`
5. Поставить `CODEX_MODEL_ID=gpt-5.3-codex` или другую Codex-capable модель

В этом режиме агенту не нужен `OPENAI_API_KEY` для доступа к модели.

## OpenAI-Compatible Auth

Проект загружает модельный секрет в таком порядке:

1. Windows Credential Manager
2. `OPENAI_ACCESS_TOKEN`
3. `OPENAI_API_KEY`

В текущей схеме используется Windows Credential Manager, чтобы не держать
provider secret в `.env`.

Чтобы посмотреть сохранённые записи:

```powershell
cmdkey /list
```

## Логирование

Каждый запуск создаёт новую папку в `logs/`:

- `logs/<timestamp>/run.log`: общий лог запуска
- `logs/<timestamp>/t01.log`: полный пошаговый лог задачи

В консоль и в task log пишется:

- bootstrap шаги
- краткие summaries шагов модели
- tool calls
- tool outputs
- финальный outcome и score

## Архитектура

Агент работает по простой схеме:

1. Стартует BitGN run и trial.
2. Поднимает стартовый контекст из `/`, `/AGENTS.MD`, `/docs` и `/bin`.
3. Классифицирует задачу по workflow family.
4. Даёт одной модельной сессии управлять tool use.
5. Ведёт evidence и state tracking вне модели.
6. Нормализует grounding refs перед `report_completion`.

## Особенности scoring

BitGN строго проверяет references. Сейчас агент:

- автоматически резолвит SKU в `/proc/catalog/<sku>.json`
- фильтрует grounding refs до валидных file paths
- не отправляет command strings как финальные refs

Это важно даже в тех случаях, когда сам ответ по сути правильный.

## Troubleshooting

- `401 User not found` обычно означает, что ключ не соответствует `OPENAI_BASE_URL`
- `401 Missing Authentication header` обычно означает несовместимую пару provider/key или устаревший секрет в Windows Credential Manager
- `insufficient_quota` означает, что провайдер принял ключ, но у аккаунта нет доступной квоты
- `codex` not found означает, что Codex CLI не установлен или `CODEX_CLI_BIN` настроен неверно
- `not authenticated` в режиме `codex_oauth` означает, что нужно выполнить `codex login`
- `answer missing required reference '/proc/catalog/<sku>.json'` означает, что логика ответа была правильной, но в финальных refs не хватило нужного файла
- `answer contains too many invalid references` означает, что в `grounding_refs` ушли command strings или невалидные ссылки
- Если агент продолжает использовать старый секрет, обнови запись `ecom1-openai` в Windows Credential Manager, потому что она имеет приоритет над `.env`
