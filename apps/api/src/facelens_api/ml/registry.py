"""Model registry: decides which provider (if any) serves each feature.

Rules enforced here, so they can't be bypassed by a single call site:
  * A feature flag that is off means no provider. Requests get ``feature_disabled``.
  * A mock provider is only registered when ``allow_mock_models`` is true.
  * A non-mock provider is refused unless its license has been approved.
  * A non-commercial-only model is refused in a commercial deployment.
  * A non-mock provider is refused unless its evaluation passed the release gates
    (docs/PLAN.md section 7.3), except with the dev-only ``allow_ungated_models``.
  * A real provider is never silently replaced by a mock at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from facelens_api.config import Settings
from facelens_api.domain.enums import TargetAgeGroup, Task
from facelens_api.ml.artifacts import YUNET_2026MAY, resolve
from facelens_api.ml.face import FaceDetector, YuNetDetector
from facelens_api.ml.interfaces import (
    AgeEstimator,
    AgeTransformer,
    ModelInfo,
    PresentationEstimator,
)
from facelens_api.ml.mock import MockAgeEstimator, MockAgeTransformer, MockPresentationEstimator


class ModelPolicyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TargetAvailability:
    group: TargetAgeGroup
    available: bool
    reason: str | None


@dataclass(slots=True)
class ModelRegistry:
    age: AgeEstimator | None
    presentation: PresentationEstimator | None
    aging: AgeTransformer | None
    allow_young_targets: bool
    detector: FaceDetector | None = None
    presentation_uncertain_threshold: float = 0.75
    license_scope: str = "commercial"
    allow_ungated_models: bool = False

    def __post_init__(self) -> None:
        for provider in (self.age, self.presentation, self.aging):
            if provider is None:
                continue
            info = provider.info
            if info.is_mock:
                continue
            if not info.license_approved:
                raise ModelPolicyError(f"model {info.id} has no approved license")
            if info.license_scope == "non_commercial" and self.license_scope != "non_commercial":
                raise ModelPolicyError(
                    f"model {info.id} is licensed for non-commercial use only; set "
                    "FACELENS_LICENSE_SCOPE=non_commercial if this deployment is non-commercial"
                )
            if not info.eval_passed and not self.allow_ungated_models:
                raise ModelPolicyError(
                    f"model {info.id} has not passed the {info.task.value} release gates "
                    f"(report: {info.eval_report or 'none'})"
                )

    def info_for(self, task: Task) -> ModelInfo | None:
        provider = {
            Task.AGE_ESTIMATION: self.age,
            Task.PRESENTATION_ESTIMATION: self.presentation,
            Task.AGE_TRANSFORMATION: self.aging,
        }[task]
        return provider.info if provider is not None else None

    def target_availability(self) -> list[TargetAvailability]:
        supported = set(self.aging.info.supported_target_age_groups) if self.aging else set()
        out: list[TargetAvailability] = []
        for group in TargetAgeGroup:
            if self.aging is None:
                out.append(TargetAvailability(group, False, "The aging tool is unavailable."))
            elif group not in supported:
                out.append(
                    TargetAvailability(
                        group, False, "The current model doesn't support this group."
                    )
                )
            elif group.is_minor and not self.allow_young_targets:
                out.append(
                    TargetAvailability(
                        group,
                        False,
                        "Child and teen targets are turned off pending a safety and legal review.",
                    )
                )
            else:
                out.append(TargetAvailability(group, True, None))
        return out

    def is_target_available(self, group: TargetAgeGroup) -> TargetAvailability:
        return next(t for t in self.target_availability() if t.group == group)


def build_detector(settings: Settings) -> FaceDetector | None:
    if settings.face_detector == "none":
        return None
    # resolve() verifies the pinned SHA-256 and raises if the file is missing or altered.
    path = resolve(YUNET_2026MAY, settings.model_dir)
    return YuNetDetector(path, settings.face_score_threshold)


def build_registry(settings: Settings) -> ModelRegistry:
    mocks = settings.allow_mock_models
    runner = None  # one MiVOLO network shared by both tools

    def mivolo_runner() -> Any:
        nonlocal runner
        if runner is None:
            from facelens_api.ml.providers.mivolo import MiVOLORunner

            runner = MiVOLORunner(settings.model_dir, settings.torch_threads)
        return runner

    def calibration() -> Any:
        from facelens_api.ml.providers.mivolo import CALIBRATION_DIR, Calibration

        return Calibration.load(CALIBRATION_DIR / "mivolo_v2.json")

    age: AgeEstimator | None = None
    if settings.feature_age_estimation:
        if settings.age_model == "mivolo_v2":
            from facelens_api.ml.providers.mivolo import MiVOLOAgeEstimator

            age = MiVOLOAgeEstimator(mivolo_runner(), calibration())
        elif mocks:
            age = MockAgeEstimator()

    presentation: PresentationEstimator | None = None
    if settings.feature_presentation_estimation:
        if settings.presentation_model == "mivolo_v2":
            from facelens_api.ml.providers.mivolo import MiVOLOPresentationEstimator

            presentation = MiVOLOPresentationEstimator(mivolo_runner(), calibration())
        elif mocks:
            presentation = MockPresentationEstimator()

    aging: AgeTransformer | None = None
    if settings.feature_age_transformation:
        if settings.aging_model == "sam":
            from facelens_api.ml.providers import sam

            aging = sam.build(settings.model_dir, settings.torch_threads)
        elif mocks:
            aging = MockAgeTransformer()

    return ModelRegistry(
        detector=build_detector(settings),
        age=age,
        presentation=presentation,
        aging=aging,
        allow_young_targets=settings.aging_allow_young_targets,
        license_scope=settings.license_scope,
        allow_ungated_models=settings.allow_ungated_models,
    )
