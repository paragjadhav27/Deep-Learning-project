"""Model policy: license scope, evaluation gates, calibration, and the real MiVOLO provider."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from facelens_api.config import Settings
from facelens_api.domain.enums import Task
from facelens_api.ml.interfaces import AgeEstimate, FaceInput, InferenceError, ModelInfo
from facelens_api.ml.registry import ModelPolicyError, ModelRegistry

from conftest import MODEL_DIR, portrait


def _real(scope: str = "non_commercial", passed: bool = True) -> Any:
    class _Model:
        info = ModelInfo(
            id="real-age",
            version="1",
            task=Task.AGE_ESTIMATION,
            is_mock=False,
            license="research",
            license_approved=True,
            license_scope=scope,  # type: ignore[arg-type]
            source_url=None,
            intended_use="test",
            limitations=(),
            eval_report="eval/results/x.json",
            eval_passed=passed,
        )

        def estimate(self, face: FaceInput) -> AgeEstimate:
            return AgeEstimate(40, 35, 45, 0.8)

    return _Model()


def _registry(**kw: Any) -> ModelRegistry:
    base: dict[str, Any] = {"presentation": None, "aging": None, "allow_young_targets": False}
    return ModelRegistry(**(base | kw))


def test_non_commercial_model_refused_in_commercial_deployment() -> None:
    with pytest.raises(ModelPolicyError, match="non-commercial use only"):
        _registry(age=_real("non_commercial"), license_scope="commercial")
    _registry(age=_real("non_commercial"), license_scope="non_commercial")  # allowed
    _registry(age=_real("commercial"), license_scope="commercial")  # allowed


def test_model_that_failed_gates_is_refused() -> None:
    with pytest.raises(ModelPolicyError, match="release gates"):
        _registry(age=_real(passed=False), license_scope="non_commercial")
    # Dev-only override for local experiments.
    _registry(age=_real(passed=False), license_scope="non_commercial", allow_ungated_models=True)


def test_ungated_override_refused_outside_dev() -> None:
    with pytest.raises(ValidationError, match="local experiments only"):
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            environment="staging",
            signing_secret="s" * 40,
            allow_ungated_models=True,
        )


def test_commercial_is_the_default_scope() -> None:
    assert Settings(_env_file=None).license_scope == "commercial"  # type: ignore[call-arg]


torch_missing = (
    importlib.util.find_spec("torch") is None or importlib.util.find_spec("timm") is None
)


@pytest.mark.skipif(torch_missing, reason="ml extra (torch, timm) not installed")
def test_calibration_is_required(tmp_path: Path) -> None:
    from facelens_api.ml.providers.mivolo import Calibration

    with pytest.raises(InferenceError, match="calibration"):
        Calibration.load(tmp_path / "missing.json")
    path = tmp_path / "cal.json"
    path.write_text(
        json.dumps(
            {
                "half_width_years": 7.5,
                "coverage_target": 0.8,
                "dataset": "d",
                "n_calibration": 10,
                "eval_report": "r.json",
                "gates": {"age_estimation": True, "presentation_estimation": False},
            }
        )
    )
    cal = Calibration.load(path)
    assert cal.gates == {"age_estimation": True, "presentation_estimation": False}


@pytest.mark.skipif(torch_missing, reason="ml extra (torch, timm) not installed")
def test_mivolo_provider_on_real_face(require_models: None) -> None:
    from facelens_api.ml.artifacts import MIVOLO_V2, YUNET_2026MAY, resolve
    from facelens_api.ml.face import YuNetDetector
    from facelens_api.ml.pipeline import prepare_face
    from facelens_api.ml.providers.mivolo import (
        Calibration,
        MiVOLOAgeEstimator,
        MiVOLOPresentationEstimator,
        MiVOLORunner,
    )

    if not (MODEL_DIR / MIVOLO_V2.filename).is_file():
        pytest.skip("MiVOLO weights not fetched")
    cal = Calibration(7.5, 0.8, "test", 10, "r.json", {"age_estimation": True})
    runner = MiVOLORunner(MODEL_DIR, num_threads=2)
    detector = YuNetDetector(resolve(YUNET_2026MAY, MODEL_DIR), 0.7)
    face = prepare_face(detector, portrait(512), 64)

    age = MiVOLOAgeEstimator(runner, cal)
    est = age.estimate(face)
    assert age.info.is_mock is False
    assert age.info.license_scope == "non_commercial"
    assert est.range_high_years - est.range_low_years == pytest.approx(15.0)
    assert 18 < est.estimate_years < 80  # adult; we assert plausibility, not a specific age
    assert est.interval_coverage == 0.8

    pres = MiVOLOPresentationEstimator(runner, cal)
    p = pres.estimate(face)
    assert p.feminine_presenting + p.masculine_presenting == pytest.approx(1.0, abs=1e-4)
    # No calibration gate for presentation in this fixture: it must report not-passed.
    assert pres.info.eval_passed is False

    # Deterministic and stable under a horizontal flip of the input.
    from PIL import ImageOps

    flipped = FaceInput(image=ImageOps.mirror(face.image), aligned=face.aligned, face=None)
    again = age.estimate(face).estimate_years
    assert again == pytest.approx(est.estimate_years, abs=1e-4)
    assert abs(age.estimate(flipped).estimate_years - est.estimate_years) < 10
