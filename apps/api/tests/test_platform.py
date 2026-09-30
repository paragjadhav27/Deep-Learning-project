"""Health, config validation, migrations, rate limiting and log hygiene."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine

from facelens_api.config import Settings
from facelens_api.db.migrate import upgrade_to_head
from facelens_api.db.models import Base
from facelens_api.log import REDACTED, redact_sensitive
from facelens_api.services.ratelimit import InMemoryRateLimiter

from conftest import make_image, new_session, upload


def test_health_and_readiness(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok", "checks": {}}
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["checks"] == {"database": True, "storage": True}


def test_request_id_is_propagated(client: TestClient) -> None:
    r = client.get("/healthz", headers={"X-Request-ID": "abc12345-trace"})
    assert r.headers["x-request-id"] == "abc12345-trace"
    r = client.get("/healthz", headers={"X-Request-ID": "bad id\nwith newline"})
    assert r.headers["x-request-id"] != "bad id\nwith newline"


def test_unknown_route_uses_error_shape(client: TestClient) -> None:
    r = client.get("/v1/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "environment": "production",
            "database_url": "postgresql://x/y",
            "allow_mock_models": True,
            "signing_secret": "x" * 40,
        },
        {
            "environment": "production",
            "database_url": "sqlite:///x.db",
            "allow_mock_models": False,
            "signing_secret": "x" * 40,
        },
        {"environment": "staging"},  # default dev signing secret
        {"environment": "staging", "signing_secret": ""},  # empty is treated as unset
        {"environment": "staging", "signing_secret": "x" * 40, "job_backend": "sync"},
        {"storage_backend": "s3"},  # no bucket
        {"job_backend": "celery"},  # no redis_url
        {"s3_sse": "aws:kms", "storage_backend": "s3", "s3_bucket": "b"},  # no key id
        {"session_ttl_seconds": 10},
        {"min_image_side": 5000},
    ],
    ids=[
        "prod-mocks",
        "prod-sqlite",
        "staging-dev-secret",
        "staging-empty-secret",
        "staging-sync",
        "s3-no-bucket",
        "celery-no-redis",
        "kms-no-key",
        "ttl",
        "dims",
    ],
)
def test_unsafe_config_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_valid_production_config() -> None:
    s = Settings(  # type: ignore[call-arg]
        _env_file=None,
        environment="production",
        database_url="postgresql+psycopg://u@db/facelens",
        allow_mock_models=False,
        signing_secret="s" * 48,
        storage_backend="s3",
        s3_bucket="facelens-prod",
        job_backend="celery",
        rate_limit_backend="redis",
        redis_url="redis://cache:6379/0",
    )
    assert s.environment == "production"


def test_migrations_match_models(tmp_path: Path) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    upgrade_to_head(url)
    engine = create_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == []


def test_upload_rate_limit(app_factory) -> None:  # type: ignore[no-untyped-def]
    with TestClient(app_factory(rate_limit_uploads_per_minute=2)) as client:
        assert upload(client).status_code == 201
        assert upload(client).status_code == 201
        r = upload(client)
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited"
    assert r.json()["error"]["retryable"] is True
    assert int(r.headers["retry-after"]) >= 1


def test_rate_limiter_window_resets() -> None:
    now = [0.0]
    rl = InMemoryRateLimiter(now=lambda: now[0])
    assert rl.hit("k", 1) is None
    assert rl.hit("k", 1) == 60
    now[0] = 45
    assert rl.hit("k", 1) == 15
    now[0] = 61
    assert rl.hit("k", 1) is None


def test_redaction_processor() -> None:
    event = {
        "event": "x",
        "image": b"\xff\xd8",
        "filename": "me.jpg",
        "result": {"estimate_years": 30},
        "scores": [0.1],
        "session_token": "t",
        "blob": b"raw",
        "image_width": 10,
        "job_id": "j_1",
    }
    out = redact_sensitive(None, "info", event)
    for key in ("image", "filename", "result", "scores", "session_token", "blob"):
        assert out[key] == REDACTED
    assert out["image_width"] == 10
    assert out["job_id"] == "j_1"


def test_logs_never_contain_image_data_or_results(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    raw = make_image()
    r = upload(client, raw, filename="john_smith_passport.jpg")
    sid, token = r.json()["session_id"], r.json()["session_token"]
    h = {"X-Session-Token": token}
    job = client.post(f"/v1/sessions/{sid}/jobs", json={"task": "age_estimation"}, headers=h)
    estimate = str(job.json()["result"]["estimate_years"])
    img_job = client.post(
        f"/v1/sessions/{sid}/jobs",
        json={"task": "age_transformation", "params": {"target_age_group": "older_adult"}},
        headers=h,
    ).json()
    client.get(img_job["result"]["image_url"])
    out = capsys.readouterr().out

    lines = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    assert lines, "expected structured JSON logs"
    assert all("request_id" in ln for ln in lines if ln["event"] == "http.request")
    assert "john_smith_passport" not in out
    assert token not in out
    assert "sig=" not in out
    assert "estimate_years" not in out
    assert f'"{estimate}"' not in out
    assert f": {estimate}," not in out
    assert raw[:32].hex() not in out


def test_cors_allows_configured_origin_only(client: TestClient) -> None:
    ok = client.options(
        "/v1/models",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    bad = client.options(
        "/v1/models",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in bad.headers


def test_session_view(client: TestClient) -> None:
    sid, h = new_session(client)
    body = client.get(f"/v1/sessions/{sid}", headers=h).json()
    assert body["session_id"] == sid
    assert body["job_ids"] == []


def test_starts_with_missing_data_directories(
    settings_factory,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    from facelens_api.main import create_app

    nested = tmp_path / "does" / "not" / "exist"
    settings = settings_factory(
        database_url=f"sqlite:///{(nested / 'db' / 'f.db').as_posix()}",
        storage_dir=nested / "blobs",
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/readyz").status_code == 200


def test_empty_signing_secret_never_used_as_key() -> None:
    s = Settings(_env_file=None, signing_secret="")  # type: ignore[call-arg]
    assert len(s.signing_secret.get_secret_value()) >= 32


def test_root_is_a_signpost_not_an_error(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "FaceLens API"
    assert body["links"]["docs"] == "/docs"  # dev/test only
