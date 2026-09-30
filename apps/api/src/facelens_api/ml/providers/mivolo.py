"""MiVOLO v2 (face-only mode) for age estimation and perceived-presentation estimation.

One network serves both tools. Outputs are post-processed here into FaceLens semantics:

* Age: the point estimate plus a *conformal* interval, whose half-width comes from a
  calibration file produced by ``eval/run_eval.py`` on held-out data. Without a
  calibration file the provider refuses to load: we never show an uncalibrated range.
* Presentation: the model's binary "gender" head is exposed only as scores for
  *perceived presentation* (index 0 → masculine-presenting, 1 → feminine-presenting,
  per the upstream config). It is never described as identity.

Requires the optional ``ml`` extra (torch, timm, safetensors).
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from facelens_api.domain.enums import Task
from facelens_api.ml.artifacts import MIVOLO_V2, resolve
from facelens_api.ml.interfaces import (
    AgeEstimate,
    FaceInput,
    InferenceError,
    ModelInfo,
    PresentationEstimate,
)

CALIBRATION_DIR = Path(__file__).resolve().parent.parent / "calibration"
INPUT_SIZE = 384
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
# From the upstream config.json: age = raw * (max_age - min_age) + avg_age
_MIN_AGE, _MAX_AGE, _AVG_AGE = 0.0, 122.0, 61.0

SOURCE_URL = "https://huggingface.co/iitolstykh/mivolo_v2"
LIMITATIONS_COMMON = (
    "Trained on proprietary and open-source datasets whose composition is not fully "
    "documented; see the evaluation report for measured differences between groups.",
    "Face-only mode: the upstream model can also use a body crop, which FaceLens never sends.",
    "Released for research use; FaceLens is deployed non-commercially.",
)


@dataclass(frozen=True, slots=True)
class Calibration:
    """Conformal half-width for the age interval, from a held-out calibration split."""

    half_width_years: float
    coverage_target: float
    dataset: str
    n_calibration: int
    eval_report: str
    # Release gates per task (docs/PLAN.md section 7.3), e.g. {"age_estimation": true}.
    gates: dict[str, bool]

    @classmethod
    def load(cls, path: Path) -> Calibration:
        if not path.is_file():
            raise InferenceError(
                f"Missing calibration file {path.name}: run eval/run_eval.py --write-calibration"
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            half_width_years=float(data["half_width_years"]),
            coverage_target=float(data["coverage_target"]),
            dataset=str(data["dataset"]),
            n_calibration=int(data["n_calibration"]),
            eval_report=str(data["eval_report"]),
            gates={str(k): bool(v) for k, v in data["gates"].items()},
        )


@dataclass(frozen=True, slots=True)
class MiVOLOOutput:
    age_years: float
    masculine_presenting: float
    feminine_presenting: float


def letterbox(img: Image.Image, size: int = INPUT_SIZE) -> Image.Image:
    """Resize keeping aspect ratio and pad with black, as upstream `class_letterbox` does."""
    w, h = img.size
    r = min(size / w, size / h)
    nw, nh = max(1, round(w * r)), max(1, round(h * r))
    canvas = Image.new("RGB", (size, size))
    canvas.paste(
        img.resize((nw, nh), Image.Resampling.BILINEAR), ((size - nw) // 2, (size - nh) // 2)
    )
    return canvas


def tight_face_crop(face: FaceInput) -> Image.Image:
    """Upstream crops the detector's face box without padding; do the same."""
    if face.face is None:
        return face.image
    f = face.face
    w, h = face.image.size
    box = (
        max(0, round(f.x)),
        max(0, round(f.y)),
        min(w, round(f.x + f.w)),
        min(h, round(f.y + f.h)),
    )
    return face.image.crop(box)


class MiVOLORunner:
    """Loads the network once; thread-safe inference shared by both providers."""

    def __init__(self, model_dir: Path, num_threads: int = 2) -> None:
        import torch
        from safetensors.torch import load_file

        from facelens_api.ml.vendor.mivolo.model import mivolo_d1_384

        self._torch = torch
        torch.set_num_threads(num_threads)
        path = resolve(MIVOLO_V2, model_dir)  # verifies the pinned SHA-256
        prefix = "mivolo.model."
        state = {k[len(prefix) :]: v.float() for k, v in load_file(str(path)).items()}
        model = mivolo_d1_384()
        model.load_state_dict(state, strict=True)
        model.eval()
        self._model = model
        self._lock = threading.Lock()
        # Face-only mode: the body stream gets a normalised all-zeros image, as upstream does
        # when no person crop is available.
        empty = (np.zeros((INPUT_SIZE, INPUT_SIZE, 3), np.float32) - _MEAN) / _STD
        self._empty_body = torch.from_numpy(empty.transpose(2, 0, 1).copy())

    def _tensor(self, img: Image.Image) -> Any:
        arr = (np.asarray(letterbox(img.convert("RGB")), dtype=np.float32) / 255.0 - _MEAN) / _STD
        return self._torch.from_numpy(arr.transpose(2, 0, 1).copy())

    def predict(self, face: FaceInput) -> MiVOLOOutput:
        return self.predict_batch([face])[0]

    def predict_batch(self, faces: list[FaceInput]) -> list[MiVOLOOutput]:
        torch = self._torch
        x = torch.stack(
            [torch.cat([self._tensor(tight_face_crop(f)), self._empty_body], 0) for f in faces]
        )
        try:
            with self._lock, torch.inference_mode():
                out = self._model(x)
        except Exception as exc:  # never leak tensor contents into messages
            raise InferenceError(type(exc).__name__) from None
        gender = out[:, :2].softmax(-1)
        ages = out[:, 2] * (_MAX_AGE - _MIN_AGE) + _AVG_AGE
        return [
            MiVOLOOutput(
                age_years=float(ages[i]),
                masculine_presenting=float(gender[i, 0]),
                feminine_presenting=float(gender[i, 1]),
            )
            for i in range(len(faces))
        ]


def _info(task: Task, calibration: Calibration | None) -> ModelInfo:
    intended = (
        "Illustrative estimate of apparent age in a single adult face photo."
        if task is Task.AGE_ESTIMATION
        else "Illustrative estimate of how a model perceives gender presentation in one photo. "
        "Not identity, not sex."
    )
    specific = (
        (
            "Point estimates are shown with a conformal interval calibrated on held-out FaceLens "
            "evaluation data; coverage can differ between groups.",
        )
        if task is Task.AGE_ESTIMATION
        else (
            "The underlying head was trained on binary labels; FaceLens reports 'uncertain' "
            "below a confidence threshold rather than forcing a label.",
        )
    )
    return ModelInfo(
        id="mivolo-v2-face",
        version="53393526",
        task=task,
        is_mock=False,
        license="Apache-2.0 (weights tag); research release, see vendor NOTICE",
        license_approved=True,
        license_scope="non_commercial",
        source_url=SOURCE_URL,
        intended_use=intended,
        limitations=(*specific, *LIMITATIONS_COMMON),
        sha256=MIVOLO_V2.sha256,
        eval_report=calibration.eval_report if calibration else None,
        eval_passed=bool(calibration and calibration.gates.get(task.value, False)),
    )


class MiVOLOAgeEstimator:
    def __init__(self, runner: MiVOLORunner, calibration: Calibration) -> None:
        self._runner = runner
        self._cal = calibration
        self.info = _info(Task.AGE_ESTIMATION, calibration)

    def estimate(self, face: FaceInput) -> AgeEstimate:
        age = self._runner.predict(face).age_years
        q = self._cal.half_width_years
        return AgeEstimate(
            estimate_years=age,
            range_low_years=max(0.0, age - q),
            range_high_years=age + q,
            interval_coverage=self._cal.coverage_target,
        )


class MiVOLOPresentationEstimator:
    def __init__(self, runner: MiVOLORunner, calibration: Calibration | None) -> None:
        self._runner = runner
        self.info = _info(Task.PRESENTATION_ESTIMATION, calibration)

    def estimate(self, face: FaceInput) -> PresentationEstimate:
        out = self._runner.predict(face)
        return PresentationEstimate(
            feminine_presenting=out.feminine_presenting,
            masculine_presenting=out.masculine_presenting,
        )
