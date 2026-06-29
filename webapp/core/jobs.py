"""Minimal in-memory job runner.

Long operations (mapping, baseline) run in a background thread so the UI stays
responsive and HTTP requests don't time out. State lives in memory only (no
persistence in v1). This is intentionally a thin seam: swap `_registry` + `submit`
for a real queue (Celery/RQ) later without touching callers.
"""
from __future__ import annotations

import threading
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable


@dataclass
class Job:
    id: str
    kind: str                       # "mapping" | "baseline" | ...
    status: str = "running"         # "running" | "done" | "error"
    stage: str = ""                 # human-readable current step
    result: Any = None
    error: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    finished_at: datetime | None = None

    @property
    def is_running(self) -> bool:
        return self.status == "running"


_registry: dict[str, Job] = {}
_lock = threading.Lock()


def submit(kind: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Job:
    """Run `fn(*args, progress=<setter>, **kwargs)` in a daemon thread.

    `fn` must accept a keyword-only `progress` callback (str -> None) to report the
    current stage. Returns the Job immediately.
    """
    job = Job(id=uuid.uuid4().hex[:12], kind=kind)
    with _lock:
        _registry[job.id] = job

    def _set_stage(message: str) -> None:
        job.stage = message

    def _run() -> None:
        try:
            job.result = fn(*args, progress=_set_stage, **kwargs)
            job.status = "done"
        except Exception as exc:  # noqa: BLE001 - capture for the UI, log for the dev
            job.error = str(exc)
            job.status = "error"
            traceback.print_exc()
        finally:
            job.finished_at = datetime.now()

    threading.Thread(target=_run, name=f"job-{kind}-{job.id}", daemon=True).start()
    return job


def get(job_id: str) -> Job | None:
    with _lock:
        return _registry.get(job_id)
