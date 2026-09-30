"""Celery worker entrypoint: ``celery -A facelens_api.jobs.worker worker -Q inference``.

Each worker process builds its own container (DB pool, blob store, models) after
fork, so no connections or model sessions are shared across processes.
"""

from __future__ import annotations

from typing import Any

from celery.signals import worker_process_init, worker_process_shutdown

from facelens_api.config import get_settings
from facelens_api.container import Container
from facelens_api.jobs.celery_app import make_celery, register_run_job
from facelens_api.log import configure_logging, get_logger

settings = get_settings()
configure_logging(settings.log_level, settings.log_json)
log = get_logger(__name__)

celery_app = make_celery(settings)
_container: Container | None = None


def _get_container() -> Container:
    global _container
    if _container is None:
        from facelens_api.main import build_container

        # The API runs migrations; workers must not race it.
        _container = build_container(settings.model_copy(update={"auto_migrate": False}))
    return _container


run_job = register_run_job(celery_app, _get_container)


@worker_process_init.connect  # type: ignore[untyped-decorator]
def _init(**_: Any) -> None:
    _get_container()
    log.info("worker.ready")


@worker_process_shutdown.connect  # type: ignore[untyped-decorator]
def _shutdown(**_: Any) -> None:
    if _container is not None:
        _container.inference_pool.shutdown(wait=True)
        _container.engine.dispose()
