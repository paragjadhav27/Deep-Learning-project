"""Application factory and lifespan (startup validation, migrations, graceful shutdown)."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from facelens_api import __version__
from facelens_api.api.errors import install_error_handlers
from facelens_api.api.middleware import RequestContextMiddleware
from facelens_api.api.v1 import jobs, meta, sessions
from facelens_api.config import Settings, get_settings
from facelens_api.container import Clock, Container, utc_now
from facelens_api.db.engine import make_engine, make_session_factory
from facelens_api.db.migrate import upgrade_to_head
from facelens_api.domain.enums import Task
from facelens_api.jobs.runner import JobRunner, SyncJobRunner, ThreadJobRunner
from facelens_api.log import configure_logging, get_logger
from facelens_api.ml.registry import build_registry
from facelens_api.services.jobs import execute_job
from facelens_api.services.ratelimit import InMemoryRateLimiter, RateLimiter, RedisRateLimiter
from facelens_api.services.sessions import sweep
from facelens_api.storage.base import BlobStore
from facelens_api.storage.local import LocalBlobStore

log = get_logger(__name__)


def build_blob_store(settings: Settings) -> BlobStore:
    if settings.storage_backend == "s3":
        from facelens_api.storage.s3 import S3BlobStore

        assert settings.s3_bucket is not None  # noqa: S101 - enforced by Settings
        return S3BlobStore(
            settings.s3_bucket,
            prefix=settings.s3_prefix,
            region=settings.s3_region,
            endpoint_url=settings.s3_endpoint_url,
            sse=settings.s3_sse,
            kms_key_id=settings.s3_kms_key_id,
        )
    return LocalBlobStore(settings.storage_dir)


def _redis_client(settings: Settings) -> Any:
    import redis

    return redis.Redis.from_url(
        settings.redis_url or "", socket_timeout=2, socket_connect_timeout=2
    )


def build_container(settings: Settings, clock: Clock = utc_now) -> Container:
    engine = make_engine(settings.database_url)  # also creates the SQLite directory
    if settings.auto_migrate:
        upgrade_to_head(settings.database_url)
    redis_client = _redis_client(settings) if settings.redis_url else None
    limiter: RateLimiter = (
        RedisRateLimiter(redis_client)
        if settings.rate_limit_backend == "redis"
        else InMemoryRateLimiter()
    )
    c = Container(
        settings=settings,
        engine=engine,
        db=make_session_factory(engine),
        blobs=build_blob_store(settings),
        registry=build_registry(settings),
        limiter=limiter,
        inference_pool=ThreadPoolExecutor(
            max_workers=settings.job_workers, thread_name_prefix="infer"
        ),
        clock=clock,
        started_at=clock(),
    )
    if redis_client is not None:
        c.readiness["redis"] = lambda: bool(redis_client.ping())
    runner: JobRunner
    if settings.job_backend == "sync":
        runner = SyncJobRunner(lambda job_id: execute_job(c, job_id))
    elif settings.job_backend == "celery":
        from facelens_api.jobs.celery_app import CeleryJobRunner, make_celery, register_run_job

        celery = make_celery(settings)
        runner = CeleryJobRunner(register_run_job(celery, lambda: c))
        c.celery = celery
    else:
        runner = ThreadJobRunner(lambda job_id: execute_job(c, job_id), settings.job_workers)
    c.runner = runner
    return c


async def _sweeper_loop(c: Container) -> None:
    while True:
        try:
            await run_in_threadpool(sweep, c)
        except Exception as exc:
            log.error("retention.sweep_failed", error_type=type(exc).__name__)
        await asyncio.sleep(c.settings.sweep_interval_seconds)


def create_app(settings: Settings | None = None, *, clock: Clock = utc_now) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        c = build_container(settings, clock)
        app.state.container = c
        sweeper = asyncio.create_task(_sweeper_loop(c)) if settings.sweeper_enabled else None
        mocks = [i.id for t in Task if (i := c.registry.info_for(t)) is not None and i.is_mock]
        log.info("app.started", environment=settings.environment, mock_models=mocks)
        try:
            yield
        finally:
            if sweeper is not None:
                sweeper.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await sweeper
            await run_in_threadpool(c.job_runner.shutdown)
            c.inference_pool.shutdown(wait=False, cancel_futures=True)
            c.engine.dispose()
            log.info("app.stopped")

    app = FastAPI(
        title="FaceLens API",
        version=__version__,
        description=(
            "Illustrative, uncertain estimates from a face image. Not for identification or "
            "any consequential decision. See docs/PLAN.md."
        ),
        lifespan=lifespan,
        docs_url="/docs" if settings.is_dev_like else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.environment != "production" else None,
    )
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "X-Session-Token", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    app.add_middleware(RequestContextMiddleware, max_body_bytes=settings.max_upload_bytes)
    app.include_router(meta.router)
    app.include_router(sessions.router)
    app.include_router(jobs.router)
    return app
