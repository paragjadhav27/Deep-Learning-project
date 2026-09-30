from __future__ import annotations

from enum import StrEnum


class Task(StrEnum):
    AGE_ESTIMATION = "age_estimation"
    PRESENTATION_ESTIMATION = "presentation_estimation"
    AGE_TRANSFORMATION = "age_transformation"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED)


class SessionStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"
    EXPIRED = "expired"


class TargetAgeGroup(StrEnum):
    """Creative targets for the illustrative aging tool. Not predictions."""

    CHILD = "child"
    TEEN = "teen"
    YOUNG_ADULT = "young_adult"
    MIDDLE_AGED_ADULT = "middle_aged_adult"
    OLDER_ADULT = "older_adult"

    @property
    def is_minor(self) -> bool:
        return self in (TargetAgeGroup.CHILD, TargetAgeGroup.TEEN)


class PresentationOutcome(StrEnum):
    FEMININE_PRESENTING = "feminine_presenting"
    MASCULINE_PRESENTING = "masculine_presenting"
    UNCERTAIN = "uncertain"


class FaceCheckStatus(StrEnum):
    NOT_CHECKED = "not_checked"  # face detection disabled (development only)
    SINGLE_FACE = "single_face"
