"""Application errors with stable, client-safe codes and messages.

Messages are written for end users and never include internal details.
"""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_FILE_TYPE = "invalid_file_type"
    FILE_TOO_LARGE = "file_too_large"
    IMAGE_TOO_SMALL = "image_too_small"
    IMAGE_TOO_LARGE = "image_too_large"
    CORRUPT_IMAGE = "corrupt_image"
    CONSENT_REQUIRED = "consent_required"
    NO_FACE_DETECTED = "no_face_detected"
    MULTIPLE_FACES_DETECTED = "multiple_faces_detected"
    FACE_TOO_SMALL = "face_too_small"
    UNSUPPORTED_TARGET_AGE_GROUP = "unsupported_target_age_group"
    FEATURE_DISABLED = "feature_disabled"
    RATE_LIMITED = "rate_limited"
    SESSION_NOT_FOUND = "session_not_found"
    JOB_NOT_FOUND = "job_not_found"
    RESULT_NOT_FOUND = "result_not_found"
    JOB_NOT_CANCELLABLE = "job_not_cancellable"
    ADULTS_ONLY = "adults_only"
    MODEL_ERROR = "model_error"
    INFERENCE_TIMEOUT = "inference_timeout"
    VALIDATION_ERROR = "validation_error"
    INTERNAL_ERROR = "internal_error"


_DEFAULTS: dict[ErrorCode, tuple[int, str, bool]] = {
    ErrorCode.INVALID_FILE_TYPE: (415, "Please upload a JPEG, PNG or WebP image.", False),
    ErrorCode.FILE_TOO_LARGE: (413, "This file is too large. The limit is {limit}.", False),
    ErrorCode.IMAGE_TOO_SMALL: (
        422,
        "This image is too small. Use one at least {min_side}px on each side.",
        False,
    ),
    ErrorCode.IMAGE_TOO_LARGE: (
        422,
        "This image's dimensions are too large. The limit is {max_side}px per side.",
        False,
    ),
    ErrorCode.CORRUPT_IMAGE: (422, "We couldn't read this image. Try a different file.", False),
    ErrorCode.CONSENT_REQUIRED: (
        400,
        "Please confirm the consent statements before uploading.",
        False,
    ),
    ErrorCode.NO_FACE_DETECTED: (
        422,
        "We couldn't find a face. Try a clear, front-facing photo with good lighting.",
        False,
    ),
    ErrorCode.MULTIPLE_FACES_DETECTED: (
        422,
        "We found more than one face. Please use a photo of a single person.",
        False,
    ),
    ErrorCode.FACE_TOO_SMALL: (
        422,
        "The face is too small in this photo. Try a closer crop.",
        False,
    ),
    ErrorCode.UNSUPPORTED_TARGET_AGE_GROUP: (
        422,
        "That target age group isn't available.",
        False,
    ),
    ErrorCode.FEATURE_DISABLED: (403, "This tool is currently unavailable.", False),
    ErrorCode.RATE_LIMITED: (429, "Too many requests. Please wait a moment and try again.", True),
    ErrorCode.SESSION_NOT_FOUND: (
        404,
        "This session doesn't exist, has expired, or was deleted.",
        False,
    ),
    ErrorCode.JOB_NOT_FOUND: (404, "This request doesn't exist or has expired.", False),
    ErrorCode.RESULT_NOT_FOUND: (404, "This result doesn't exist or has expired.", False),
    ErrorCode.JOB_NOT_CANCELLABLE: (409, "This request has already finished.", False),
    ErrorCode.ADULTS_ONLY: (
        422,
        "We can't process this photo. These tools only support images of adults.",
        False,
    ),
    ErrorCode.MODEL_ERROR: (502, "The model couldn't process this image. Please try again.", True),
    ErrorCode.INFERENCE_TIMEOUT: (504, "Processing took too long. Please try again.", True),
    ErrorCode.VALIDATION_ERROR: (422, "Some of the request fields are invalid.", False),
    ErrorCode.INTERNAL_ERROR: (500, "Something went wrong on our side. Please try again.", True),
}


class AppError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        *,
        headers: dict[str, str] | None = None,
        details: dict[str, object] | None = None,
        **fmt: object,
    ) -> None:
        status, default_message, retryable = _DEFAULTS[code]
        self.code = code
        self.status_code = status
        self.retryable = retryable
        self.message = message if message is not None else default_message.format(**fmt)
        self.headers = headers or {}
        self.details = details
        super().__init__(code.value)


def default_status(code: ErrorCode) -> int:
    return _DEFAULTS[code][0]
