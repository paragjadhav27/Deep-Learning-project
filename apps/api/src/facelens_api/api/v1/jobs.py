from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Query, Request, Response
from sqlalchemy.orm import Session

from facelens_api.api.deps import ContainerDep, DbDep, SessionToken, rate_limit
from facelens_api.db.models import JobRecord
from facelens_api.domain.enums import SessionStatus
from facelens_api.domain.errors import AppError, ErrorCode
from facelens_api.schemas.api import ErrorResponse, JobCreate, JobView
from facelens_api.services import jobs as svc
from facelens_api.services.sessions import load_active_session
from facelens_api.storage.base import BlobNotFoundError

router = APIRouter(prefix="/v1", tags=["jobs"])

_ERRORS: dict[int | str, dict[str, object]] = {
    s: {"model": ErrorResponse} for s in (403, 404, 409, 422, 429)
}


@router.post(
    "/sessions/{session_id}/jobs", status_code=202, response_model=JobView, responses=_ERRORS
)
def create_job(
    session_id: str,
    request: Request,
    c: ContainerDep,
    body: Annotated[JobCreate, Body()],
    token: SessionToken = None,
) -> JobView:
    rate_limit(c, request, "jobs", c.settings.rate_limit_jobs_per_minute)
    with c.db.begin() as db:
        session = load_active_session(db, c, session_id, token)
        job = svc.create_job(c, db, session, body)
        job_id = job.id
    # Committed before submit so a worker can always see the job row.
    c.job_runner.submit(job_id)
    with c.db() as db:
        return svc.to_view(c, _get(db, job_id))


@router.get("/jobs/{job_id}", response_model=JobView, responses=_ERRORS)
def get_job(job_id: str, c: ContainerDep, db: DbDep, token: SessionToken = None) -> JobView:
    return svc.to_view(c, svc.load_job_for_token(db, c, job_id, token))


@router.delete("/jobs/{job_id}", response_model=JobView, responses=_ERRORS)
def cancel_job(job_id: str, c: ContainerDep, db: DbDep, token: SessionToken = None) -> JobView:
    """Best-effort cancel. A running model call finishes, but its output is discarded."""
    job = svc.load_job_for_token(db, c, job_id, token)
    svc.cancel_job(c, job)
    db.flush()
    return svc.to_view(c, job)


@router.get(
    "/results/{job_id}/image",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}, 404: {"model": ErrorResponse}},
)
def get_result_image(
    job_id: str,
    c: ContainerDep,
    db: DbDep,
    exp: Annotated[int, Query()],
    sig: Annotated[str, Query(max_length=128)],
) -> Response:
    """Short-lived signed URL, so the URL itself is the credential and <img> tags work."""
    now = c.clock()
    svc.verify_signed_url(c, "result", job_id, exp, sig)
    job = db.get(JobRecord, job_id)
    if (
        job is None
        or job.result_key is None
        or job.session.status != SessionStatus.ACTIVE
        or job.session.expires_at <= now
    ):
        raise AppError(ErrorCode.RESULT_NOT_FOUND)
    try:
        data = c.blobs.get(job.result_key)
    except BlobNotFoundError:
        raise AppError(ErrorCode.RESULT_NOT_FOUND) from None
    ttl = max(0, exp - int(now.timestamp()))
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={
            "Cache-Control": f"private, max-age={min(ttl, 300)}",
            "Content-Disposition": 'inline; filename="facelens-synthetic-preview.jpg"',
        },
    )


def _get(db: Session, job_id: str) -> JobRecord:
    job = db.get(JobRecord, job_id)
    if job is None:
        raise AppError(ErrorCode.JOB_NOT_FOUND)
    return job
