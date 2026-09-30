"""Responsible-use controls: adults-only guard and synthetic-image marking."""

from __future__ import annotations

import io
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from facelens_api.domain.enums import Task
from facelens_api.imaging.watermark import IPTC_SYNTHETIC, JPEG_COMMENT
from facelens_api.ml.interfaces import AgeEstimate, FaceInput, ModelInfo

from conftest import container_of, new_session


def _real_age_model(low: float, high: float) -> Any:
    class _Model:
        # Stand-in for a future approved (non-mock) estimator.
        info = ModelInfo(
            id="stub-real-age",
            version="1",
            task=Task.AGE_ESTIMATION,
            is_mock=False,
            license="test",
            license_approved=True,
            source_url=None,
            intended_use="test",
            limitations=(),
        )

        def estimate(self, face: FaceInput) -> AgeEstimate:
            return AgeEstimate((low + high) / 2, low, high, 0.8)

    return _Model()


BODIES = {
    "age_estimation": {"task": "age_estimation"},
    "presentation_estimation": {"task": "presentation_estimation"},
    "age_transformation": {
        "task": "age_transformation",
        "params": {"target_age_group": "older_adult"},
    },
}


@pytest.mark.parametrize("task", list(BODIES))
def test_minor_estimate_blocks_every_tool(client: TestClient, task: str) -> None:
    container_of(client).registry.age = _real_age_model(9, 15)
    sid, h = new_session(client)
    job = client.post(f"/v1/sessions/{sid}/jobs", json=BODIES[task], headers=h).json()
    assert job["status"] == "failed"
    assert job["error"]["code"] == "adults_only"
    assert job["result"] is None
    # No generated image may be left behind.
    root = container_of(client).blobs.root  # type: ignore[attr-defined]
    assert not (root / "sessions" / sid / "results").exists()


@pytest.mark.parametrize("task", list(BODIES))
def test_uncertain_range_reaching_adulthood_is_allowed(client: TestClient, task: str) -> None:
    # Upper bound >= 18: uncertainty must not push adults out.
    container_of(client).registry.age = _real_age_model(14, 22)
    sid, h = new_session(client)
    job = client.post(f"/v1/sessions/{sid}/jobs", json=BODIES[task], headers=h).json()
    assert job["status"] == "succeeded", job


def test_generated_images_are_marked_synthetic(client: TestClient) -> None:
    sid, h = new_session(client)
    job = client.post(
        f"/v1/sessions/{sid}/jobs", json=BODIES["age_transformation"], headers=h
    ).json()
    assert job["result"]["synthetic"] is True
    assert job["result"]["watermarked"] is True
    img_bytes = client.get(job["result"]["image_url"]).content
    with Image.open(io.BytesIO(img_bytes)) as img:
        assert img.info.get("comment") == JPEG_COMMENT
        # Machine-readable AI-generated marker (IPTC digital source type, in XMP).
        assert IPTC_SYNTHETIC.encode() in img.info["xmp"]
        # Visible band along the bottom edge: dark background with light text.
        band = img.convert("L").crop((0, img.height - 8, img.width, img.height))
        lo, hi = band.getextrema()
        assert lo < 30
        assert hi > 200
