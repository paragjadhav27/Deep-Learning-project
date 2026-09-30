"""Face detection policy (no face / multiple faces / too small), alignment, and model pinning.

Uses the public-domain portrait in tests/fixtures (see PROVENANCE.md). Assertions are
about face *geometry* only; nothing about the person's age or appearance.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from facelens_api.config import Settings
from facelens_api.ml.artifacts import (
    YUNET_2026MAY,
    Artifact,
    ModelArtifactError,
    resolve,
    sha256_file,
)
from facelens_api.ml.face import YuNetDetector, align_crop, eye_tilt_degrees
from facelens_api.ml.registry import build_registry

from conftest import MODEL_DIR, container_of, make_image, portrait, to_bytes, upload


def _no_face() -> Image.Image:
    return Image.open(io.BytesIO(make_image(size=(320, 320))))


def _two_faces() -> Image.Image:
    p = portrait()
    canvas = Image.new("RGB", (512, 256))
    canvas.paste(p, (0, 0))
    canvas.paste(p, (256, 0))
    return canvas


def _small_face() -> Image.Image:
    canvas = Image.new("RGB", (512, 512), (90, 90, 90))
    canvas.paste(portrait().resize((128, 128)), (100, 100))  # face is ~21x25 px
    return canvas


@pytest.fixture
def detector(require_models: None) -> YuNetDetector:
    return YuNetDetector(resolve(YUNET_2026MAY, MODEL_DIR), score_threshold=0.7)


def test_single_face_accepted(face_app_factory) -> None:  # type: ignore[no-untyped-def]
    with TestClient(face_app_factory()) as client:
        r = upload(client, to_bytes(portrait(512)))
        assert r.status_code == 201, r.text
        assert r.json()["face_check"] == {"status": "single_face"}
        caps = client.get("/v1/models").json()["face_detection"]
        assert caps["enabled"] is True
        assert caps["model_id"] == "yunet"
        assert caps["license"] == "MIT"


@pytest.mark.parametrize(
    ("image", "code"),
    [
        (_no_face, "no_face_detected"),
        (_two_faces, "multiple_faces_detected"),
        (_small_face, "face_too_small"),
    ],
    ids=["no-face", "two-faces", "small-face"],
)
def test_face_policy_rejections_store_nothing(
    face_app_factory,  # type: ignore[no-untyped-def]
    image,  # type: ignore[no-untyped-def]
    code: str,
) -> None:
    with TestClient(face_app_factory()) as client:
        r = upload(client, to_bytes(image()))
        assert r.status_code == 422, r.text
        err = r.json()["error"]
        assert err["code"] == code
        assert err["retryable"] is False
        # Rejected images are never persisted.
        root: Path = container_of(client).blobs.root  # type: ignore[attr-defined]
        assert not any(p.is_file() for p in root.rglob("*"))


def test_face_below_policy_size_rejected(face_app_factory) -> None:  # type: ignore[no-untyped-def]
    with TestClient(face_app_factory()) as client:
        r = upload(client, to_bytes(portrait(256)))  # face ~45 px < min_face_side=64
    assert r.json()["error"]["code"] == "face_too_small"


def test_large_image_is_detected_after_downscale(detector: YuNetDetector) -> None:
    # YuNet is trained on ~10-300 px faces; a 2048 px portrait must still work.
    faces = detector.detect(portrait().resize((2048, 2048)))
    assert len(faces) == 1
    assert faces[0].w > 300  # box is reported in original-image coordinates


def test_job_flow_records_detector(face_app_factory) -> None:  # type: ignore[no-untyped-def]
    from facelens_api.db.models import JobRecord

    with TestClient(face_app_factory()) as client:
        r = upload(client, to_bytes(portrait(512)))
        sid, h = r.json()["session_id"], {"X-Session-Token": r.json()["session_token"]}
        for body in (
            {"task": "age_estimation"},
            {"task": "presentation_estimation"},
            {"task": "age_transformation", "params": {"target_age_group": "older_adult"}},
        ):
            job = client.post(f"/v1/sessions/{sid}/jobs", json=body, headers=h).json()
            assert job["status"] == "succeeded", job
            with container_of(client).db() as db:
                rec = db.get(JobRecord, job["job_id"])
                assert rec is not None
                assert rec.detector_model == "yunet@2026may"


@pytest.mark.parametrize("roll", [-20, 30])
def test_alignment_levels_the_eyes(detector: YuNetDetector, roll: int) -> None:
    rotated = portrait().rotate(roll, resample=Image.Resampling.BICUBIC, fillcolor=(90, 90, 90))
    (face,) = detector.detect(rotated)
    single = align_crop(rotated, face, refine_steps=0, detector=detector)
    refined = align_crop(rotated, face, detector=detector)
    assert refined.size == (256, 256)

    def tilt(img: Image.Image) -> float:
        (f,) = detector.detect(img)
        return abs(eye_tilt_degrees(f))

    # Measured on this fixture: single-pass residual ~12 degrees, refined <3 degrees.
    assert tilt(refined) < 5
    assert tilt(refined) < tilt(single)


def test_checksum_mismatch_refuses_to_load(tmp_path: Path) -> None:
    fake = Artifact("x", "x.onnx", "https://example.invalid/x", "0" * 64, "MIT", "")
    (tmp_path / "x.onnx").write_bytes(b"tampered")
    with pytest.raises(ModelArtifactError, match="Checksum mismatch"):
        resolve(fake, tmp_path)
    with pytest.raises(ModelArtifactError, match="missing"):
        resolve(fake, tmp_path / "empty")


def test_missing_detector_model_fails_startup(tmp_path: Path) -> None:
    s = Settings(_env_file=None, face_detector="yunet", model_dir=tmp_path)  # type: ignore[call-arg]
    with pytest.raises(ModelArtifactError):
        build_registry(s)


def test_pinned_checksum_matches_fetched_file(require_models: None) -> None:
    assert sha256_file(MODEL_DIR / YUNET_2026MAY.filename) == YUNET_2026MAY.sha256
