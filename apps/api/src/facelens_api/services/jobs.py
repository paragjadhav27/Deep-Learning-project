"""Job creation, execution and presentation.

Execution never logs image data or inference outputs: only ids, codes and timings.
"""

from __future__ import annotations

import io
import time
from collections.abc import Callable
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timedelta
from typing import Any, Literal, TypeVar

from PIL import Image
from sqlalchemy.orm import Session

from facelens_api.container import Container
from facelens_api.db.models import JobRecord, SessionRecord
from facelens_api.domain.enums import JobStatus, SessionStatus, TargetAgeGroup, Task
from facelens_api.domain.errors import AppError, ErrorCode
from facelens_api.imaging.watermark import encode_synthetic_jpeg
from facelens_api.log import get_logger
from facelens_api.ml.interfaces import AgeEstimate, FaceInput, InferenceError, ModelInfo
from facelens_api.ml.pipeline import prepare_face
from facelens_api.schemas.api import (
    AgeEstimationResult,
    AgeTransformationRequest,
    AgeTransformationResult,
    JobCreate,
    JobError,
    JobResult,
    JobView,
    ModelRef,
    PresentationEstimationResult,
    PresentationScores,
)
from facelens_api.services.security import new_id, sign, token_matches, verify_signature
from facelens_api.storage.base import BlobNotFoundError, job_result_key

log = get_logger(__name__)
T = TypeVar("T")
ADULT_AGE = 18


# ---- create -----------------------------------------------------------------------


def create_job(c: Container, db: Session, session: SessionRecord, req: JobCreate) -> JobRecord:
    task = Task(req.task)
    if c.registry.info_for(task) is None:
        raise AppError(ErrorCode.FEATURE_DISABLED)
    params: dict[str, str] = {}
    if isinstance(req, AgeTransformationRequest):
        group = req.params.target_age_group
        availability = c.registry.is_target_available(group)
        if not availability.available:
            raise AppError(
                ErrorCode.UNSUPPORTED_TARGET_AGE_GROUP,
                message=availability.reason,
                details={"target_age_group": group.value},
            )
        params["target_age_group"] = group.value
    job = JobRecord(
        id=new_id("j"),
        session_id=session.id,
        task=task,
        params=params,
        status=JobStatus.QUEUED,
        progress=0.0,
        created_at=c.clock(),
    )
    db.add(job)
    return job


def load_job_for_token(db: Session, c: Container, job_id: str, token: str | None) -> JobRecord:
    job = db.get(JobRecord, job_id)
    if job is None:
        raise AppError(ErrorCode.JOB_NOT_FOUND)
    session = job.session
    if (
        session.status != SessionStatus.ACTIVE
        or session.expires_at <= c.clock()
        or not token_matches(token, session.token_hash)
    ):
        raise AppError(ErrorCode.JOB_NOT_FOUND)
    return job


def cancel_job(c: Container, job: JobRecord) -> None:
    if JobStatus(job.status).is_terminal:
        raise AppError(ErrorCode.JOB_NOT_CANCELLABLE)
    job.status = JobStatus.CANCELLED
    job.finished_at = c.clock()
    job.stage = None


# ---- execute ----------------------------------------------------------------------


def _set_stage(c: Container, job_id: str, stage: str, progress: float) -> bool:
    """Update progress. Returns False if the job was cancelled meanwhile."""
    with c.db.begin() as db:
        job = db.get(JobRecord, job_id)
        if job is None or job.status != JobStatus.RUNNING:
            return False
        job.stage, job.progress = stage, progress
        return True


def _with_timeout(c: Container, fn: Callable[[], T]) -> T:
    future = c.inference_pool.submit(fn)
    try:
        return future.result(timeout=c.settings.inference_timeout_seconds)
    except FutureTimeout:
        future.cancel()
        raise AppError(ErrorCode.INFERENCE_TIMEOUT) from None


def execute_job(c: Container, job_id: str) -> None:
    with c.db.begin() as db:
        job = db.get(JobRecord, job_id)
        if job is None or job.status != JobStatus.QUEUED:
            return  # cancelled or already handled
        job.status, job.started_at, job.stage, job.progress = (
            JobStatus.RUNNING,
            c.clock(),
            "preparing",
            0.1,
        )
        task, params, session_id = Task(job.task), dict(job.params), job.session_id
        image_key = job.session.image_key

    info = c.registry.info_for(task)
    started = time.perf_counter()
    try:
        if info is None:
            raise AppError(ErrorCode.FEATURE_DISABLED)
        if image_key is None:
            raise AppError(ErrorCode.SESSION_NOT_FOUND)
        try:
            raw = c.blobs.get(image_key)
        except BlobNotFoundError:
            raise AppError(ErrorCode.SESSION_NOT_FOUND) from None
        with Image.open(io.BytesIO(raw)) as im:
            image = im.convert("RGB")
        if not _set_stage(c, job_id, "detecting_face", 0.2):
            return
        face = prepare_face(c.registry.detector, image, c.settings.min_face_side)

        stage = "rendering" if task is Task.AGE_TRANSFORMATION else "estimating"
        if not _set_stage(c, job_id, stage, 0.4):
            return
        result, result_key = _run_task(c, task, params, face, session_id, job_id)
        _finish(c, job_id, info, started, result=result, result_key=result_key)
    except AppError as err:
        _finish(c, job_id, info, started, error=err.code)
    except InferenceError as exc:
        log.warning("job.model_error", job_id=job_id, error_type=type(exc).__name__)
        _finish(c, job_id, info, started, error=ErrorCode.MODEL_ERROR)
    except Exception as exc:
        log.error("job.internal_error", job_id=job_id, error_type=type(exc).__name__)
        _finish(c, job_id, info, started, error=ErrorCode.MODEL_ERROR)


def _enforce_adults_only(c: Container, face: FaceInput, est: AgeEstimate | None = None) -> None:
    """PLAN section 7.4: refuse when the age estimate's *upper* bound is under 18.

    Uses the upper bound so that uncertainty never pushes an adult out, only a
    confident "minor" estimate blocks. A mock estimator can't judge age, so the
    guard is only active when a real (non-mock) estimator is registered. Users
    also attest to being adults, and that attestation is the primary control.
    """
    model = c.registry.age
    if model is None or model.info.is_mock:
        return
    if est is None:
        est = _with_timeout(c, lambda: model.estimate(face))
    if max(est.range_low_years, est.range_high_years) < ADULT_AGE:
        raise AppError(ErrorCode.ADULTS_ONLY)


def _run_task(
    c: Container,
    task: Task,
    params: dict[str, str],
    face: FaceInput,
    session_id: str,
    job_id: str,
) -> tuple[dict[str, Any], str | None]:
    reg = c.registry
    if task is Task.AGE_ESTIMATION and reg.age is not None:
        age_model = reg.age
        est = _with_timeout(c, lambda: age_model.estimate(face))
        _enforce_adults_only(c, face, est)
        low, high = sorted((round(est.range_low_years), round(est.range_high_years)))
        return {
            "estimate_years": round(est.estimate_years),
            "range_years": [max(0, low), high],
            "interval_coverage": est.interval_coverage,
        }, None
    if task is Task.PRESENTATION_ESTIMATION and reg.presentation is not None:
        pres_model = reg.presentation
        _enforce_adults_only(c, face)
        pres = _with_timeout(c, lambda: pres_model.estimate(face))
        threshold = reg.presentation_uncertain_threshold
        return {
            "outcome": pres.outcome(threshold).value,
            "scores": {
                "feminine_presenting": round(pres.feminine_presenting, 3),
                "masculine_presenting": round(pres.masculine_presenting, 3),
            },
            "uncertain_threshold": threshold,
        }, None
    if task is Task.AGE_TRANSFORMATION and reg.aging is not None:
        aging_model = reg.aging
        target = TargetAgeGroup(params["target_age_group"])
        _enforce_adults_only(c, face)
        out = _with_timeout(c, lambda: aging_model.transform(face, target))
        key = job_result_key(session_id, job_id)
        # Marked here, not in the provider, so no model can skip it.
        c.blobs.put(key, encode_synthetic_jpeg(out), "image/jpeg")
        return {"target_age_group": target.value}, key
    raise AppError(ErrorCode.FEATURE_DISABLED)


def _finish(
    c: Container,
    job_id: str,
    info: ModelInfo | None,
    started: float,
    *,
    result: dict[str, Any] | None = None,
    result_key: str | None = None,
    error: ErrorCode | None = None,
) -> None:
    latency_ms = round((time.perf_counter() - started) * 1000)
    with c.db.begin() as db:
        job = db.get(JobRecord, job_id)
        session_live = job is not None and job.session.status == SessionStatus.ACTIVE
        if job is None or job.status != JobStatus.RUNNING or not session_live:
            # Cancelled or session deleted while running: discard any output.
            if result_key:
                c.blobs.delete(result_key)
            return
        job.finished_at = c.clock()
        job.latency_ms = latency_ms
        job.stage = None
        if info is not None:
            job.model_id, job.model_version, job.is_mock = info.id, info.version, info.is_mock
        det = c.registry.detector
        job.detector_model = f"{det.info.id}@{det.info.version}" if det else None
        if error is None:
            job.status, job.progress, job.result, job.result_key = (
                JobStatus.SUCCEEDED,
                1.0,
                result,
                result_key,
            )
        else:
            job.status, job.error_code = JobStatus.FAILED, error
    log.info(
        "job.finished",
        job_id=job_id,
        outcome="failed" if error else "succeeded",
        error_code=error.value if error else None,
        model_id=info.id if info else None,
        model_version=info.version if info else None,
        latency_ms=latency_ms,
    )


# ---- present ----------------------------------------------------------------------


def verify_signed_url(
    c: Container, kind: Literal["result", "upload"], object_id: str, exp: int, sig: str
) -> None:
    secret = c.settings.signing_secret.get_secret_value()
    expired = exp < int(c.clock().timestamp())
    if expired or not verify_signature(secret, sig, kind, object_id, str(exp)):
        raise AppError(ErrorCode.RESULT_NOT_FOUND)


def signed_image_url(
    c: Container, kind: Literal["result", "upload"], object_id: str
) -> tuple[str, datetime]:
    """Short-lived HMAC link so plain <img> tags work without exposing the session token."""
    expires = c.clock() + timedelta(seconds=c.settings.result_url_ttl_seconds)
    exp = str(int(expires.timestamp()))
    sig = sign(c.settings.signing_secret.get_secret_value(), kind, object_id, exp)
    path = (
        f"/v1/results/{object_id}/image" if kind == "result" else f"/v1/sessions/{object_id}/image"
    )
    return f"{path}?exp={exp}&sig={sig}", expires


def to_view(c: Container, job: JobRecord) -> JobView:
    result: JobResult | None = None
    if job.status == JobStatus.SUCCEEDED and job.result is not None:
        data = job.result
        task = Task(job.task)
        if task is Task.AGE_ESTIMATION:
            result = AgeEstimationResult(
                estimate_years=data["estimate_years"],
                range_years=tuple(data["range_years"]),
                interval_coverage=data["interval_coverage"],
            )
        elif task is Task.PRESENTATION_ESTIMATION:
            result = PresentationEstimationResult(
                outcome=data["outcome"],
                scores=PresentationScores(**data["scores"]),
                uncertain_threshold=data["uncertain_threshold"],
            )
        elif job.result_key is not None:
            url, expires = signed_image_url(c, "result", job.id)
            result = AgeTransformationResult(
                target_age_group=data["target_age_group"],
                image_url=url,
                image_url_expires_at=expires,
            )
    error = None
    if job.error_code is not None:
        err = AppError(ErrorCode(job.error_code))
        error = JobError(code=err.code.value, message=err.message, retryable=err.retryable)
    model = None
    if job.model_id is not None and job.model_version is not None:
        model = ModelRef(id=job.model_id, version=job.model_version, is_mock=bool(job.is_mock))
    return JobView(
        job_id=job.id,
        session_id=job.session_id,
        task=Task(job.task),
        params=dict(job.params),
        status=JobStatus(job.status),
        progress=job.progress,
        stage=job.stage,
        created_at=job.created_at,
        finished_at=job.finished_at,
        result=result,
        error=error,
        model=model,
    )
