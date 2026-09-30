"""Process-wide dependencies, built once in the app lifespan."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from facelens_api.config import Settings
from facelens_api.jobs.runner import JobRunner
from facelens_api.ml.registry import ModelRegistry
from facelens_api.services.ratelimit import RateLimiter
from facelens_api.storage.base import BlobStore

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class Container:
    settings: Settings
    engine: Engine
    db: sessionmaker[Session]
    blobs: BlobStore
    registry: ModelRegistry
    limiter: RateLimiter
    inference_pool: ThreadPoolExecutor
    clock: Clock = utc_now
    runner: JobRunner | None = None
    started_at: datetime = field(default_factory=utc_now)
    sweeper_last_run: datetime | None = None
    # Extra readiness probes for optional backends (e.g. the Celery broker).
    readiness: dict[str, Callable[[], bool]] = field(default_factory=dict)
    celery: Any = None  # Celery app when job_backend=celery (tests toggle eager mode)

    @property
    def job_runner(self) -> JobRunner:
        if self.runner is None:
            raise RuntimeError("job runner not initialised")
        return self.runner
