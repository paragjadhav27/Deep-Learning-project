"""Job runners. ``thread`` for single-node dev, ``sync`` for demos/tests; Celery in Phase 2."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

JobFn = Callable[[str], None]


class JobRunner(Protocol):
    def submit(self, job_id: str) -> None: ...

    def shutdown(self) -> None: ...


class SyncJobRunner:
    def __init__(self, fn: JobFn) -> None:
        self._fn = fn

    def submit(self, job_id: str) -> None:
        self._fn(job_id)

    def shutdown(self) -> None:
        return None


class ThreadJobRunner:
    def __init__(self, fn: JobFn, workers: int) -> None:
        self._fn = fn
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="job")

    def submit(self, job_id: str) -> None:
        self._pool.submit(self._fn, job_id)

    def shutdown(self) -> None:
        # Graceful: let running jobs finish, drop queued ones (they stay "queued" and
        # are failed by the next sweep so clients don't poll forever).
        self._pool.shutdown(wait=True, cancel_futures=True)
