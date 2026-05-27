from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ANSI_RED_PATTERN = re.compile(r"\x1b\[(?:0;)?(?:31|91)m", re.IGNORECASE)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def strip_ansi(text: str) -> str:
    result: list[str] = []
    skip = False
    for char in text:
        if char == "\x1b":
            skip = True
            continue
        if skip:
            if char == "m":
                skip = False
            continue
        result.append(char)
    return "".join(result)


@dataclass
class TaskLogger:
    path: Path
    error_path: Path | None = None

    def log(self, message: str) -> None:
        normalized = strip_ansi(message)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(normalized)
            if not message.endswith("\n"):
                handle.write("\n")
        is_red_ansi = bool(ANSI_RED_PATTERN.search(message))
        is_error_text = normalized.lstrip().lower().startswith("error:")
        if self.error_path is not None and (is_red_ansi or is_error_text):
            self.error_path.parent.mkdir(parents=True, exist_ok=True)
            with self.error_path.open("a", encoding="utf-8") as handle:
                handle.write(normalized)
                if not message.endswith("\n"):
                    handle.write("\n")

    def log_json(self, payload: dict[str, Any]) -> None:
        self.log(json.dumps(payload, ensure_ascii=True))


class RunLogManager:
    def __init__(self, root: str = "logs") -> None:
        self.session_dir = Path(root) / utc_timestamp()
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.errors_dir = self.session_dir / "errors"
        self.run_log = TaskLogger(
            self.session_dir / "run.log",
            error_path=self.errors_dir / "run.errors.log",
        )

    def task_logger(self, task_id: str) -> TaskLogger:
        safe_task_id = "".join(char if char.isalnum() or char in "-_." else "_" for char in task_id)
        return TaskLogger(
            self.session_dir / f"{safe_task_id}.log",
            error_path=self.errors_dir / f"{safe_task_id}.errors.log",
        )
