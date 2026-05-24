from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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

    def log(self, message: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(strip_ansi(message))
            if not message.endswith("\n"):
                handle.write("\n")

    def log_json(self, payload: dict[str, Any]) -> None:
        self.log(json.dumps(payload, ensure_ascii=True))


class RunLogManager:
    def __init__(self, root: str = "logs") -> None:
        self.session_dir = Path(root) / utc_timestamp()
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.run_log = TaskLogger(self.session_dir / "run.log")

    def task_logger(self, task_id: str) -> TaskLogger:
        safe_task_id = "".join(char if char.isalnum() or char in "-_." else "_" for char in task_id)
        return TaskLogger(self.session_dir / f"{safe_task_id}.log")
