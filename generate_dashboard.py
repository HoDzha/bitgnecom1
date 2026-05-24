from __future__ import annotations

import html
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LOGS_DIR = ROOT / "logs"
OUTPUT_PATH = ROOT / "dashboard.html"

TASK_SCORE_RE = re.compile(r"^(t\d+):\s+([01]\.00)$")
FINAL_RE = re.compile(r"^FINAL:\s+([0-9.]+)%$")
BENCH_RE = re.compile(r"with\s+(\d+)\s+tasks")
FAILED_RE = re.compile(r"^Failed tasks:\s*(.*)$")


@dataclass
class RunSummary:
    name: str
    task_count: int
    benchmark_size: int
    passed: int
    failed: list[str]
    final_pct: float
    model_auth_source: str
    model_id: str


def parse_run_log(path: Path) -> RunSummary | None:
    if not path.exists():
        return None

    lines = path.read_text(encoding="utf-8").splitlines()
    benchmark_size = 0
    model_auth_source = "unknown"
    model_id = "unknown"
    scores: dict[str, float] = {}
    failed: list[str] = []
    final_pct = 0.0

    for line in lines:
        if line.startswith("Model auth source:"):
            model_auth_source = line.split(":", 1)[1].strip()
        elif line.startswith("Resolved model id:"):
            model_id = line.split(":", 1)[1].strip()
        elif "benchmark:" in line:
            match = BENCH_RE.search(line)
            if match:
                benchmark_size = int(match.group(1))
        else:
            task_match = TASK_SCORE_RE.match(line.strip())
            if task_match:
                scores[task_match.group(1)] = float(task_match.group(2))
                continue
            final_match = FINAL_RE.match(line.strip())
            if final_match:
                final_pct = float(final_match.group(1))
                continue
            failed_match = FAILED_RE.match(line.strip())
            if failed_match:
                payload = failed_match.group(1).strip()
                failed = [] if payload == "none" else [item.strip() for item in payload.split(",")]

    if not scores:
        return None

    return RunSummary(
        name=path.parent.name,
        task_count=len(scores),
        benchmark_size=benchmark_size or len(scores),
        passed=sum(1 for score in scores.values() if score == 1.0),
        failed=failed,
        final_pct=final_pct,
        model_auth_source=model_auth_source,
        model_id=model_id,
    )


def classify_failure_reason(task_log: Path) -> str:
    if not task_log.exists():
        return "missing log"
    text = task_log.read_text(encoding="utf-8", errors="replace")
    if "answer missing required reference" in text:
        return "required refs"
    if "answer contains invalid reference" in text:
        return "invalid refs"
    if "expected outcome OUTCOME_NONE_CLARIFICATION, got OUTCOME_OK" in text:
        return "unsupported vs ok"
    if "expected outcome OUTCOME_NONE_UNSUPPORTED" in text:
        return "unsupported routing"
    if "expected outcome OUTCOME_DENIED_SECURITY" in text:
        return "security routing"
    if "expected outcome OUTCOME_OK, got OUTCOME_NONE_CLARIFICATION" in text:
        return "early clarification"
    if "expected outcome OUTCOME_OK" in text:
        return "outcome mismatch"
    return "other"


def pipeline_cards() -> list[dict[str, str]]:
    return [
        {
            "label": "A1",
            "title": "Bootstrap",
            "body": "Читает /AGENTS.MD, дерево root и docs, список tools, date/id. Дальше поднимает контекст перед первым reasoning step.",
        },
        {
            "label": "A2",
            "title": "Evidence",
            "body": "Собирает grounded evidence через read/list/tree и SQL. Автоматически вытаскивает refs из путей, ids и SKU.",
        },
        {
            "label": "A3",
            "title": "Catalogue SQL",
            "body": "Для shopper/count/availability вопросов форсирует реальный lookup вместо ленивого clarification.",
        },
        {
            "label": "A4",
            "title": "Policy Rails",
            "body": "Нормализует security, privacy и unsupported outcomes. Подмешивает security, checkout, returns и 3DS policy refs.",
        },
        {
            "label": "A5",
            "title": "Action Gate",
            "body": "Не даёт обходить ownership, payment safety, manager claims и handbook overrides. Снимает чувствительные refs в denial-ответах.",
        },
        {
            "label": "A6",
            "title": "Final Answer",
            "body": "Собирает completion refs, валидирует существующие file paths и оформляет финальный outcome для BitGN scoring.",
        },
    ]


def next_steps() -> list[str]:
    return [
        "Добить shopper SQL-поиск на узких product-properties, когда первая выборка ошибочно возвращает 0 строк.",
        "Добавить более жёсткий recovery-flow для basket/payment задач: auto-read basket, payment и /docs/payments/3ds.md до clarification.",
        "Развести security denial и unsupported на support/returns кейсах, где объект уже paid или closed.",
        "Сделать targeted reruns по failing tasks и отдельно показывать gain после каждого пакета правок.",
    ]


def render_dashboard(runs: list[RunSummary]) -> str:
    full_runs = [run for run in runs if run.task_count >= 40]
    latest = full_runs[-1] if full_runs else runs[-1]
    best = max(full_runs or runs, key=lambda run: run.passed)
    benchmark_size = latest.benchmark_size
    failure_counter = Counter(
        classify_failure_reason(LOGS_DIR / latest.name / f"{task_id}.log")
        for task_id in latest.failed
    )
    top_failures = ", ".join(latest.failed[:8]) if latest.failed else "none"
    failure_mix = ", ".join(f"{name}: {count}" for name, count in failure_counter.most_common(4)) or "none"

    history_rows = []
    for run in reversed(full_runs[-5:] or runs[-5:]):
        local_counter = Counter(
            classify_failure_reason(LOGS_DIR / run.name / f"{task_id}.log")
            for task_id in run.failed
        )
        history_rows.append(
            {
                "name": run.name,
                "result": f"{run.passed}/{run.task_count}",
                "failures": ", ".join(run.failed[:6]) if run.failed else "none",
                "note": ", ".join(f"{key}: {value}" for key, value in local_counter.most_common(3)) or "clean run",
            }
        )

    cards_html = "\n".join(
        f"""
        <article class="pipeline-card">
          <div class="pipeline-label">{html.escape(card["label"])}</div>
          <h3>{html.escape(card["title"])}</h3>
          <p>{html.escape(card["body"])}</p>
        </article>
        """
        for card in pipeline_cards()
    )

    rows_html = "\n".join(
        f"""
        <tr>
          <td>{html.escape(row["name"])}</td>
          <td>{html.escape(row["result"])}</td>
          <td>{html.escape(row["failures"])}</td>
          <td>{html.escape(row["note"])}</td>
        </tr>
        """
        for row in history_rows
    )

    next_html = "\n".join(f"<li>{html.escape(item)}</li>" for item in next_steps())

    latest_progress = (latest.passed / max(latest.benchmark_size, 1)) * 100
    best_progress = (best.passed / max(best.benchmark_size, 1)) * 100

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ECOM Agent Dashboard</title>
  <style>
    :root {{
      --bg: #eef3f7;
      --ink: #172231;
      --muted: #60758d;
      --panel: rgba(255,255,255,.92);
      --hero: linear-gradient(135deg, #152232 0%, #1d3148 45%, #21455b 100%);
      --accent: #18a36f;
      --accent-soft: #c8f0df;
      --line: rgba(28, 50, 73, .12);
      --shadow: 0 18px 48px rgba(22, 35, 51, .08);
      --radius: 22px;
    }}

    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Trebuchet MS", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(24,163,111,.14), transparent 32%),
        linear-gradient(180deg, #f4f7fa 0%, var(--bg) 100%);
      color: var(--ink);
    }}

    .shell {{
      width: min(1240px, calc(100vw - 32px));
      margin: 24px auto 48px;
    }}

    .hero {{
      background: var(--hero);
      color: #f5fbff;
      border-radius: 28px;
      padding: 28px 30px 26px;
      box-shadow: 0 24px 60px rgba(13, 21, 34, .24);
      position: relative;
      overflow: hidden;
    }}

    .hero::after {{
      content: "";
      position: absolute;
      inset: auto -8% -25% auto;
      width: 320px;
      height: 320px;
      background: radial-gradient(circle, rgba(255,255,255,.18), transparent 62%);
      transform: rotate(14deg);
    }}

    .eyebrow {{
      letter-spacing: .12em;
      text-transform: uppercase;
      font-size: 12px;
      opacity: .78;
      margin-bottom: 10px;
    }}

    h1 {{
      margin: 0;
      font-size: clamp(30px, 4vw, 44px);
      line-height: 1.04;
      font-weight: 800;
    }}

    .subtitle {{
      margin-top: 10px;
      max-width: 860px;
      color: rgba(245,251,255,.82);
      line-height: 1.55;
      font-size: 15px;
    }}

    .meta {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 18px;
    }}

    .meta-chip {{
      border: 1px solid rgba(255,255,255,.16);
      color: rgba(245,251,255,.88);
      background: rgba(255,255,255,.08);
      padding: 8px 12px;
      border-radius: 999px;
      font-size: 13px;
      backdrop-filter: blur(10px);
    }}

    .stats {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
      margin-top: 18px;
    }}

    .stat {{
      background: var(--panel);
      border: 1px solid rgba(255,255,255,.24);
      border-radius: var(--radius);
      padding: 18px 18px 16px;
      box-shadow: var(--shadow);
    }}

    .stat-label {{
      text-transform: uppercase;
      letter-spacing: .08em;
      font-size: 11px;
      color: var(--muted);
      margin-bottom: 10px;
    }}

    .stat-value {{
      font-size: 38px;
      line-height: 1;
      font-weight: 800;
      color: #16324a;
    }}

    .stat-note {{
      margin-top: 8px;
      font-size: 13px;
      color: var(--muted);
      line-height: 1.4;
    }}

    .bar {{
      height: 10px;
      background: #dfe7ee;
      border-radius: 999px;
      overflow: hidden;
      margin-top: 14px;
    }}

    .bar > span {{
      display: block;
      height: 100%;
      border-radius: 999px;
      background: linear-gradient(90deg, #12875c 0%, #1db27a 100%);
    }}

    .section {{
      margin-top: 22px;
      background: rgba(255,255,255,.66);
      border: 1px solid rgba(255,255,255,.5);
      border-radius: 26px;
      padding: 22px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
    }}

    .section h2 {{
      margin: 0 0 14px;
      font-size: 27px;
      line-height: 1.1;
    }}

    .pipeline-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
    }}

    .pipeline-card {{
      background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(247,251,253,.9));
      border-radius: 22px;
      padding: 18px;
      border: 1px solid var(--line);
      box-shadow: 0 12px 30px rgba(22, 35, 51, .05);
      min-height: 164px;
      position: relative;
      overflow: hidden;
    }}

    .pipeline-card::before {{
      content: "";
      position: absolute;
      inset: 0 auto 0 0;
      width: 4px;
      background: linear-gradient(180deg, #0f6fbe 0%, #18a36f 100%);
    }}

    .pipeline-label {{
      color: #0f6fbe;
      text-transform: uppercase;
      font-size: 12px;
      letter-spacing: .08em;
      margin-bottom: 10px;
      font-weight: 700;
    }}

    .pipeline-card h3 {{
      margin: 0 0 10px;
      font-size: 22px;
    }}

    .pipeline-card p {{
      margin: 0;
      color: var(--muted);
      line-height: 1.55;
      font-size: 14px;
    }}

    .two-col {{
      display: grid;
      grid-template-columns: 1.35fr .95fr;
      gap: 16px;
      align-items: start;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      overflow: hidden;
      border-radius: 18px;
      background: rgba(255,255,255,.92);
    }}

    thead th {{
      text-align: left;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .08em;
      color: var(--muted);
      padding: 14px 16px;
      background: #edf3f8;
    }}

    tbody td {{
      padding: 14px 16px;
      border-top: 1px solid var(--line);
      vertical-align: top;
      font-size: 14px;
      line-height: 1.45;
    }}

    .notes {{
      background: linear-gradient(180deg, #132335 0%, #182d42 100%);
      color: #edf8ff;
      border-radius: 22px;
      padding: 18px 18px 18px 20px;
    }}

    .notes h3 {{
      margin: 0 0 12px;
      font-size: 22px;
    }}

    .notes p {{
      margin: 0 0 12px;
      color: rgba(237,248,255,.78);
      line-height: 1.55;
      font-size: 14px;
    }}

    .notes ul {{
      margin: 12px 0 0;
      padding-left: 18px;
    }}

    .notes li {{
      margin: 0 0 10px;
      line-height: 1.45;
    }}

    .tag-row {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 12px;
    }}

    .tag {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: rgba(24,163,111,.12);
      color: #0e6846;
      border: 1px solid rgba(24,163,111,.18);
      border-radius: 999px;
      padding: 8px 12px;
      font-size: 13px;
      font-weight: 600;
    }}

    @media (max-width: 1100px) {{
      .stats,
      .pipeline-grid,
      .two-col {{
        grid-template-columns: 1fr 1fr;
      }}
    }}

    @media (max-width: 760px) {{
      .shell {{
        width: min(100vw - 18px, 100%);
        margin: 10px auto 26px;
      }}

      .hero,
      .section {{
        border-radius: 22px;
        padding: 18px;
      }}

      .stats,
      .pipeline-grid,
      .two-col {{
        grid-template-columns: 1fr;
      }}

      .stat-value {{
        font-size: 32px;
      }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <div class="eyebrow">BitGN ECOM1 Agent Session Dashboard</div>
      <h1>ECOM Agent: pipeline, результаты и план стабилизации</h1>
      <div class="subtitle">
        Автогенерируемый дашборд по локальным логам. Показывает текущий статус benchmark, структуру рантайма агента, динамику full-runs и ближайшие инженерные шаги.
      </div>
      <div class="meta">
        <div class="meta-chip">Latest full run: {html.escape(latest.name)}</div>
        <div class="meta-chip">Model: {html.escape(latest.model_id)}</div>
        <div class="meta-chip">Auth: {html.escape(latest.model_auth_source)}</div>
        <div class="meta-chip">Benchmark size: {benchmark_size}</div>
      </div>
      <div class="stats">
        <article class="stat">
          <div class="stat-label">Best Full Pass</div>
          <div class="stat-value">{best.passed}/{best.benchmark_size}</div>
          <div class="bar"><span style="width:{best_progress:.2f}%"></span></div>
          <div class="stat-note">Лучший зафиксированный full-run в локальных логах.</div>
        </article>
        <article class="stat">
          <div class="stat-label">Latest Full Pass</div>
          <div class="stat-value">{latest.passed}/{latest.benchmark_size}</div>
          <div class="bar"><span style="width:{latest_progress:.2f}%"></span></div>
          <div class="stat-note">Последний завершённый полный прогон benchmark.</div>
        </article>
        <article class="stat">
          <div class="stat-label">Open Failures</div>
          <div class="stat-value">{len(latest.failed)}</div>
          <div class="stat-note">Неуспешные задачи в последнем full-run. Top list: {html.escape(top_failures)}</div>
        </article>
        <article class="stat">
          <div class="stat-label">Failure Mix</div>
          <div class="stat-value">{len(failure_counter)}</div>
          <div class="stat-note">Ключевые паттерны: {html.escape(failure_mix)}</div>
        </article>
      </div>
    </section>

    <section class="section">
      <h2>Pipeline агента сейчас</h2>
      <div class="pipeline-grid">
        {cards_html}
      </div>
    </section>

    <section class="section">
      <h2>Динамика прогонов</h2>
      <div class="two-col">
        <div>
          <table>
            <thead>
              <tr>
                <th>Прогон</th>
                <th>Результат</th>
                <th>Главные failures</th>
                <th>Вывод</th>
              </tr>
            </thead>
            <tbody>
              {rows_html}
            </tbody>
          </table>
        </div>
        <aside class="notes">
          <h3>Что делать дальше</h3>
          <p>Сейчас агент уверенно проходит только часть ECOM1. Основной резерв лежит не в одном месте, а в стыке shopper SQL discovery, refs hardening и outcome routing для support/checkout сценариев.</p>
          <div class="tag-row">
            <div class="tag">Latest full score: {latest.final_pct:.2f}%</div>
            <div class="tag">Passed: {latest.passed}</div>
            <div class="tag">Failed: {len(latest.failed)}</div>
          </div>
          <ul>
            {next_html}
          </ul>
        </aside>
      </div>
    </section>
  </main>
</body>
</html>
"""


def main() -> None:
    runs = []
    for session_dir in sorted(LOGS_DIR.iterdir()):
        if not session_dir.is_dir():
            continue
        summary = parse_run_log(session_dir / "run.log")
        if summary is not None:
            runs.append(summary)
    if not runs:
        raise SystemExit("No run logs found in ./logs")

    OUTPUT_PATH.write_text(render_dashboard(runs), encoding="utf-8")
    print(f"dashboard written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
