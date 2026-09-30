from __future__ import annotations

import io
import json
import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from facelens_api.config import Settings
from facelens_api.container import Container
from facelens_api.main import create_app

API_ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = API_ROOT / "models"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
FULL_CONSENT = json.dumps({"has_permission": True, "is_adult": True, "accepts_limitations": True})


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now += timedelta(**kw)


def make_image(
    fmt: str = "JPEG",
    size: tuple[int, int] = (256, 256),
    mode: str = "RGB",
    **save_kw: Any,
) -> bytes:
    img = Image.new(mode, size, (120, 90, 60) if mode == "RGB" else None)
    buf = io.BytesIO()
    img.save(buf, format=fmt, **save_kw)
    return buf.getvalue()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def settings_factory(tmp_path: Path) -> Callable[..., Settings]:
    def factory(**overrides: Any) -> Settings:
        base: dict[str, Any] = {
            "environment": "test",
            "database_url": f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
            "storage_dir": tmp_path / "blobs",
            "job_backend": "sync",
            "sweeper_enabled": False,
            "log_json": True,
            # Most tests use flat-colour images; face tests opt in via `face_app_factory`.
            "face_detector": "none",
            "model_dir": MODEL_DIR,
        }
        base.update(overrides)
        return Settings(_env_file=None, **base)  # type: ignore[call-arg]

    return factory


@pytest.fixture
def app_factory(
    settings_factory: Callable[..., Settings], clock: FakeClock
) -> Callable[..., FastAPI]:
    def factory(**overrides: Any) -> FastAPI:
        return create_app(settings_factory(**overrides), clock=clock)

    return factory


@pytest.fixture
def client(app_factory: Callable[..., FastAPI]) -> Iterator[TestClient]:
    with TestClient(app_factory()) as c:
        yield c


def container_of(client: TestClient) -> Container:
    app: Any = client.app
    c: Container = app.state.container
    return c


def upload(
    client: TestClient,
    data: bytes | None = None,
    *,
    consent: str | None = FULL_CONSENT,
    content_type: str = "image/jpeg",
    filename: str = "photo.jpg",
) -> Any:
    form = {"consent": consent} if consent is not None else {}
    return client.post(
        "/v1/sessions",
        files={"image": (filename, data if data is not None else make_image(), content_type)},
        data=form,
    )


def new_session(client: TestClient) -> tuple[str, dict[str, str]]:
    r = upload(client)
    assert r.status_code == 201, r.text
    body = r.json()
    return body["session_id"], {"X-Session-Token": body["session_token"]}


def portrait(size: int = 256) -> Image.Image:
    """256 px: face is ~45 px wide (below the 64 px policy). 512 px: ~90 px wide."""
    img = Image.open(FIXTURES / "portrait.jpg").convert("RGB")
    return img if size == 256 else img.resize((size, size), Image.Resampling.LANCZOS)


def to_bytes(img: Image.Image, fmt: str = "JPEG") -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture
def require_models() -> None:
    """Skip locally when weights aren't fetched; CI sets FACELENS_TEST_REQUIRE_MODELS=1
    so a missing model is a failure there, never a silent skip."""
    from facelens_api.ml.artifacts import YUNET_2026MAY

    if not (MODEL_DIR / YUNET_2026MAY.filename).is_file():
        if os.environ.get("FACELENS_TEST_REQUIRE_MODELS") == "1":
            pytest.fail("model files missing: run `facelens-api fetch-models`")
        pytest.skip("model files not fetched (run `facelens-api fetch-models`)")


@pytest.fixture
def face_app_factory(
    app_factory: Callable[..., FastAPI], require_models: None
) -> Callable[..., FastAPI]:
    def factory(**overrides: Any) -> FastAPI:
        return app_factory(face_detector="yunet", **overrides)

    return factory
