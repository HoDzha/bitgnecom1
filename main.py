from __future__ import annotations

import os
import textwrap

from bitgn.harness_connect import HarnessServiceClientSync
from bitgn.harness_pb2 import (
    EndTrialRequest,
    EvalPolicy,
    GetBenchmarkRequest,
    StartRunRequest,
    StartTrialRequest,
    StatusRequest,
    SubmitRunRequest,
)
from connectrpc.errors import ConnectError

from ecom_agent import CLI_BLUE, CLI_CLR, CLI_GREEN, CLI_RED, run_agent
from env_utils import load_dotenv
from openai_client import describe_openai_auth_source, has_openai_credentials
from runtime_logging import RunLogManager

load_dotenv()

BITGN_URL = os.getenv("BITGN_HOST") or os.getenv("BENCHMARK_HOST") or "https://api.bitgn.com"
BITGN_API_KEY = os.getenv("BITGN_API_KEY") or ""
BENCH_ID = os.getenv("BENCH_ID") or os.getenv("BENCHMARK_ID") or "bitgn/ecom1-dev"
MODEL_ID = os.getenv("MODEL_ID") or "gpt-5.4"
RUN_NAME = os.getenv("RUN_NAME") or "ECOM1 Rails Agent"


def main() -> None:
    task_filter = os.sys.argv[1:]
    scores: list[tuple[str, float]] = []
    log_manager = RunLogManager()

    if not BITGN_API_KEY:
        print(f"{CLI_RED}BITGN_API_KEY is missing{CLI_CLR}")
        return

    if not has_openai_credentials():
        print(
            f"{CLI_RED}OpenAI credentials are missing. "
            "Set OPENAI_ACCESS_TOKEN or OPENAI_API_KEY, or store one in Windows Credential Manager."
            f"{CLI_CLR}"
        )
        return

    try:
        client = HarnessServiceClientSync(BITGN_URL)
        print("Connecting to BitGN", client.status(StatusRequest()))
        print(f"OpenAI auth source: {describe_openai_auth_source()}")
        log_manager.run_log.log(f"OpenAI auth source: {describe_openai_auth_source()}")

        benchmark = client.get_benchmark(GetBenchmarkRequest(benchmark_id=BENCH_ID))
        benchmark_line = (
            f"{EvalPolicy.Name(benchmark.policy)} benchmark: {benchmark.benchmark_id} "
            f"with {len(benchmark.tasks)} tasks.\n{CLI_GREEN}{benchmark.description}{CLI_CLR}"
        )
        print(benchmark_line)
        log_manager.run_log.log(benchmark_line)

        run = client.start_run(
            StartRunRequest(
                name=RUN_NAME,
                benchmark_id=BENCH_ID,
                api_key=BITGN_API_KEY,
            )
        )

        try:
            for trial_id in run.trial_ids:
                trial = client.start_trial(StartTrialRequest(trial_id=trial_id))
                if task_filter and trial.task_id not in task_filter:
                    continue

                task_header = f"{'=' * 28} Starting task: {trial.task_id} {'=' * 28}"
                task_body = f"{CLI_BLUE}{trial.instruction}{CLI_CLR}\n{'-' * 80}"
                print(task_header)
                print(task_body)
                task_logger = log_manager.task_logger(trial.task_id)
                task_logger.log(task_header)
                task_logger.log(task_body)

                try:
                    run_agent(MODEL_ID, trial.harness_url, trial.instruction, logger=task_logger)
                except Exception as exc:
                    print(f"{CLI_RED}{exc}{CLI_CLR}")
                    task_logger.log(f"{CLI_RED}{exc}{CLI_CLR}")

                result = client.end_trial(EndTrialRequest(trial_id=trial.trial_id))
                if result.score_available:
                    scores.append((trial.task_id, result.score))
                    style = CLI_GREEN if result.score == 1 else CLI_RED
                    explain = textwrap.indent("\n".join(result.score_detail), " ")
                    score_text = f"\n{style}Score: {result.score:0.2f}\n{explain}\n{CLI_CLR}"
                    print(score_text)
                    task_logger.log(score_text)
                    log_manager.run_log.log(f"{trial.task_id}: {result.score:0.2f}")
                else:
                    print(f"\n{CLI_BLUE}Score: not available{CLI_CLR}\n")
                    task_logger.log(f"\n{CLI_BLUE}Score: not available{CLI_CLR}\n")
        finally:
            client.submit_run(SubmitRunRequest(run_id=run.run_id, force=True))

    except ConnectError as exc:
        print(f"{exc.code}: {exc.message}")
    except KeyboardInterrupt:
        print(f"{CLI_RED}Interrupted{CLI_CLR}")

    if scores:
        for task_id, score in scores:
            style = CLI_GREEN if score == 1 else CLI_RED
            print(f"{task_id}: {style}{score:0.2f}{CLI_CLR}")
            log_manager.run_log.log(f"{task_id}: {score:0.2f}")
        total = sum(score for _, score in scores) / len(scores) * 100.0
        print(f"FINAL: {total:0.2f}%")
        log_manager.run_log.log(f"FINAL: {total:0.2f}%")


if __name__ == "__main__":
    main()
