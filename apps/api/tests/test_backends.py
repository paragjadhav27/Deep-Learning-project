"""Production backends: S3 storage (moto), Redis rate limiting (fakeredis), Celery jobs
(eager mode), and PostgreSQL migrations (only when FACELENS_TEST_POSTGRES_URL is set)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import boto3
import fakeredis
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from facelens_api.services.ratelimit import RedisRateLimiter
from facelens_api.storage.base import BlobNotFoundError
from facelens_api.storage.s3 import S3BlobStore

from conftest import container_of, new_session

BUCKET = "facelens-test"


@pytest.fixture
def aws(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def test_s3_store_roundtrip_and_prefix_delete(aws: Any) -> None:
    store = S3BlobStore(BUCKET, prefix="env1", client=aws)
    store.put("sessions/s_1/upload.jpg", b"a", "image/jpeg")
    store.put("sessions/s_1/results/j_1.jpg", b"b", "image/jpeg")
    store.put("sessions/s_2/upload.jpg", b"c", "image/jpeg")
    assert store.get("sessions/s_1/upload.jpg") == b"a"
    assert store.exists("sessions/s_1/results/j_1.jpg")

    head = aws.head_object(Bucket=BUCKET, Key="env1/sessions/s_1/upload.jpg")
    assert head["ServerSideEncryption"] == "AES256"
    assert head["CacheControl"] == "no-store"

    assert store.delete_prefix("sessions/s_1") == 2
    assert not store.exists("sessions/s_1/upload.jpg")
    assert store.exists("sessions/s_2/upload.jpg")  # prefix delete is scoped
    with pytest.raises(BlobNotFoundError):
        store.get("sessions/s_1/upload.jpg")
    assert store.healthcheck()
    assert not S3BlobStore("missing-bucket", client=aws).healthcheck()


def test_s3_store_rejects_traversal(aws: Any) -> None:
    store = S3BlobStore(BUCKET, client=aws)
    with pytest.raises(ValueError, match="invalid blob key"):
        store.put("../other-tenant/x.jpg", b"x", "image/jpeg")


def test_full_flow_on_s3_backend(app_factory, aws: Any) -> None:  # type: ignore[no-untyped-def]
    with TestClient(app_factory(storage_backend="s3", s3_bucket=BUCKET)) as client:
        sid, h = new_session(client)
        body = {"task": "age_transformation", "params": {"target_age_group": "older_adult"}}
        job = client.post(f"/v1/sessions/{sid}/jobs", json=body, headers=h).json()
        assert client.get(job["result"]["image_url"]).status_code == 200
        keys = [o["Key"] for o in aws.list_objects_v2(Bucket=BUCKET)["Contents"]]
        assert len(keys) == 2
        assert client.delete(f"/v1/sessions/{sid}", headers=h).status_code == 204
        assert aws.list_objects_v2(Bucket=BUCKET).get("KeyCount") == 0
        assert client.get("/readyz").json()["checks"]["storage"] is True


def test_redis_rate_limiter_is_shared_across_instances() -> None:
    server = fakeredis.FakeServer()
    now = [1_000_040.0]
    a = RedisRateLimiter(fakeredis.FakeRedis(server=server), now=lambda: now[0])
    b = RedisRateLimiter(fakeredis.FakeRedis(server=server), now=lambda: now[0])
    assert a.hit("upload:1.2.3.4", 2) is None
    assert b.hit("upload:1.2.3.4", 2) is None  # a second replica sees the same count
    retry = a.hit("upload:1.2.3.4", 2)
    assert retry == 40  # window [1_000_020, 1_000_080) -> 40 s left
    assert b.hit("upload:5.6.7.8", 2) is None  # other clients unaffected
    now[0] += 60
    assert a.hit("upload:1.2.3.4", 2) is None


def test_celery_runner_executes_jobs(app_factory) -> None:  # type: ignore[no-untyped-def]
    app = app_factory(job_backend="celery", redis_url="redis://127.0.0.1:1/0")
    with TestClient(app) as client:
        c = container_of(client)
        c.celery.conf.task_always_eager = True  # run in-process; no broker needed
        sid, h = new_session(client)
        job = client.post(
            f"/v1/sessions/{sid}/jobs", json={"task": "age_estimation"}, headers=h
        ).json()
        assert job["status"] == "succeeded"
        # Readiness reports the unreachable broker instead of pretending to be healthy.
        ready = client.get("/readyz")
        assert ready.status_code == 503
        assert ready.json()["checks"]["redis"] is False


def test_celery_messages_carry_only_the_job_id(app_factory) -> None:  # type: ignore[no-untyped-def]
    sent: list[dict[str, Any]] = []
    app = app_factory(job_backend="celery", redis_url="redis://127.0.0.1:1/0")
    with TestClient(app) as client:
        runner = container_of(client).job_runner
        task = runner._task  # type: ignore[attr-defined]
        task.apply_async = lambda **kw: sent.append(kw)
        sid, h = new_session(client)
        client.post(f"/v1/sessions/{sid}/jobs", json={"task": "age_estimation"}, headers=h)
    assert len(sent) == 1
    assert sent[0]["queue"] == "inference"
    (job_id,) = sent[0]["args"]
    assert job_id.startswith("j_")


@pytest.mark.skipif(
    not os.environ.get("FACELENS_TEST_POSTGRES_URL"), reason="FACELENS_TEST_POSTGRES_URL not set"
)
def test_postgres_migrations_and_flow(app_factory) -> None:  # type: ignore[no-untyped-def]
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine

    from facelens_api.db.models import Base

    url = os.environ["FACELENS_TEST_POSTGRES_URL"]
    with TestClient(app_factory(database_url=url)) as client:
        sid, h = new_session(client)
        job = client.post(
            f"/v1/sessions/{sid}/jobs", json={"task": "age_estimation"}, headers=h
        ).json()
        assert job["status"] == "succeeded"
        assert client.delete(f"/v1/sessions/{sid}", headers=h).status_code == 204
    engine = create_engine(url)
    with engine.connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
    engine.dispose()
