"""Celery wiring. Only the job id crosses the broker: never image data or results.

API side:     CeleryJobRunner enqueues ``facelens.run_job``.
Worker side:  ``celery -A facelens_api.jobs.worker worker -Q inference``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from celery import Celery

from facelens_api.config import Settings

if TYPE_CHECKING:
    from facelens_api.container import Container

TASK_NAME = "facelens.run_job"
QUEUE = "inference"


def make_celery(settings: Settings) -> Celery:
    app = Celery("facelens", broker=settings.redis_url)
    hard = settings.inference_timeout_seconds * 3 + 30
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        task_ignore_result=True,  # state lives in the database, not a result backend
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_default_queue=QUEUE,
        task_time_limit=hard,
        task_soft_time_limit=hard - 10,
        broker_connection_retry_on_startup=True,
        worker_hijack_root_logger=False,
        broker_transport_options={"visibility_timeout": int(hard * 2)},
    )
    return app


def register_run_job(app: Celery, container: Callable[[], Container]) -> Any:
    from facelens_api.services.jobs import execute_job

    @app.task(name=TASK_NAME, max_retries=0)  # type: ignore[untyped-decorator]
    def run_job(job_id: str) -> None:
        execute_job(container(), job_id)

    return run_job


class CeleryJobRunner:
    def __init__(self, task: Any) -> None:
        self._task = task

    def submit(self, job_id: str) -> None:
        self._task.apply_async(args=[job_id], queue=QUEUE)

    def shutdown(self) -> None:
        return None
