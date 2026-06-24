from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any


class JsonlRunLogger:
    def __init__(self, log_dir: Path, run_id: str):
        self.log_dir = log_dir
        self.run_id = run_id
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = self.log_dir / f"{run_id}.jsonl"
        self.text_path = self.log_dir / f"{run_id}.log"

        self.logger = logging.getLogger(run_id)
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()
        handler = logging.FileHandler(self.text_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        self.logger.addHandler(handler)

    def event(self, step: str, status: str = "info", **data: Any) -> None:
        payload = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "run_id": self.run_id,
            "step": step,
            "status": status,
            **data,
        }
        with self.jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.logger.info("%s %s %s", step, status, json.dumps(data, ensure_ascii=False, default=str))

    def error(self, step: str, exc: Exception, **data: Any) -> None:
        self.event(step, "error", error=str(exc), **data)
        self.logger.exception("%s failed", step)
