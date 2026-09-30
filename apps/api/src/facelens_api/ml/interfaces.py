"""Versioned inference interfaces.

Each feature is a Protocol so a model can be replaced without touching the API.
Providers receive a ``FaceInput`` (sanitized RGB image plus an aligned face crop)
and return typed outputs; they never see request context, and must never log their
inputs or outputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from PIL import Image

from facelens_api.domain.enums import PresentationOutcome, TargetAgeGroup, Task
from facelens_api.ml.face import DetectedFace


@dataclass(frozen=True, slots=True)
class ModelInfo:
    id: str
    version: str
    task: Task
    is_mock: bool
    license: str
    license_approved: bool
    source_url: str | None
    intended_use: str
    limitations: tuple[str, ...]
    supported_target_age_groups: tuple[TargetAgeGroup, ...] = ()
    sha256: str | None = None
    # "non_commercial" models are refused unless the deployment's license scope allows them.
    license_scope: Literal["commercial", "non_commercial"] = "commercial"
    # Evaluation report (docs/MODEL_CARDS.md) and whether it met the release gates.
    eval_report: str | None = None
    eval_passed: bool = False


@dataclass(frozen=True, slots=True)
class FaceInput:
    image: Image.Image  # full sanitized RGB image
    aligned: Image.Image  # eye-levelled square crop (the whole image if detection is off)
    face: DetectedFace | None  # None only when face detection is disabled (dev)


@dataclass(frozen=True, slots=True)
class AgeEstimate:
    estimate_years: float
    range_low_years: float
    range_high_years: float
    interval_coverage: float  # nominal coverage of the range, e.g. 0.8


@dataclass(frozen=True, slots=True)
class PresentationEstimate:
    feminine_presenting: float
    masculine_presenting: float
    scores_extra: dict[str, float] = field(default_factory=dict)

    def outcome(self, threshold: float) -> PresentationOutcome:
        top = max(self.feminine_presenting, self.masculine_presenting)
        if top < threshold:
            return PresentationOutcome.UNCERTAIN
        if self.feminine_presenting >= self.masculine_presenting:
            return PresentationOutcome.FEMININE_PRESENTING
        return PresentationOutcome.MASCULINE_PRESENTING


class InferenceError(Exception):
    """Raised by providers for model failures. Message must not contain user data."""


class AgeEstimator(Protocol):
    info: ModelInfo

    def estimate(self, face: FaceInput) -> AgeEstimate: ...


class PresentationEstimator(Protocol):
    info: ModelInfo

    def estimate(self, face: FaceInput) -> PresentationEstimate: ...


class AgeTransformer(Protocol):
    info: ModelInfo

    def transform(self, face: FaceInput, target: TargetAgeGroup) -> Image.Image: ...
