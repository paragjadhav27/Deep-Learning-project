from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from facelens_api.api.deps import ContainerDep, DbDep, SessionToken, rate_limit
from facelens_api.db.models import SessionRecord
from facelens_api.domain.enums import FaceCheckStatus, SessionStatus
from facelens_api.domain.errors import AppError, ErrorCode
from facelens_api.schemas.api import (
    Consent,
    ErrorResponse,
    FaceCheck,
    ImageInfo,
    SessionCreated,
    SessionView,
)
from facelens_api.services import sessions as svc
from facelens_api.services.jobs import signed_image_url, verify_signed_url
from facelens_api.storage.base import BlobNotFoundError

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])

_ERRORS: dict[int | str, dict[str, object]] = {
    s: {"model": ErrorResponse} for s in (400, 404, 413, 415, 422, 429)
}


@router.post("", status_code=201, response_model=SessionCreated, responses=_ERRORS)
async def create_session(
    request: Request,
    c: ContainerDep,
    image: Annotated[UploadFile, File(description="JPEG, PNG or WebP. Metadata is removed.")],
    consent: Annotated[str | None, Form(description="JSON-encoded Consent object.")] = None,
) -> SessionCreated:
    rate_limit(c, request, "upload", c.settings.rate_limit_uploads_per_minute)
    try:
        parsed = Consent.model_validate_json(consent or "")
    except ValidationError:
        raise AppError(ErrorCode.CONSENT_REQUIRED) from None
    if not parsed.is_complete:
        raise AppError(ErrorCode.CONSENT_REQUIRED)

    # Read at most limit+1 bytes so oversized uploads are rejected without buffering them all.
    raw = await image.read(c.settings.max_upload_bytes + 1)
    await image.close()
    created = await run_in_threadpool(svc.create_session, c, raw)
    rec = created.record
    return SessionCreated(
        session_id=rec.id,
        session_token=created.token,
        expires_at=rec.expires_at,
        image=_image_info(c, rec.id, created.image.width, created.image.height),
        face_check=FaceCheck(
            status=FaceCheckStatus.SINGLE_FACE
            if created.face_checked
            else FaceCheckStatus.NOT_CHECKED
        ),
    )


@router.get("/{session_id}", response_model=SessionView, responses=_ERRORS)
def get_session(
    session_id: str, c: ContainerDep, db: DbDep, token: SessionToken = None
) -> SessionView:
    rec = svc.load_active_session(db, c, session_id, token)
    return SessionView(
        session_id=rec.id,
        expires_at=rec.expires_at,
        image=_image_info(c, rec.id, rec.image_width or 0, rec.image_height or 0),
        job_ids=[j.id for j in sorted(rec.jobs, key=lambda j: j.created_at)],
    )


@router.delete("/{session_id}", status_code=204, responses=_ERRORS)
def delete_session(session_id: str, c: ContainerDep, token: SessionToken = None) -> Response:
    """Immediately delete the upload, all generated images, and all results."""
    with c.db() as db:
        svc.load_active_session(db, c, session_id, token, allow_expired=True)
    svc.end_session(c, session_id, SessionStatus.DELETED)
    return Response(status_code=204)


@router.get(
    "/{session_id}/image",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}, 404: {"model": ErrorResponse}},
)
def get_session_image(
    session_id: str,
    c: ContainerDep,
    db: DbDep,
    exp: Annotated[int, Query()],
    sig: Annotated[str, Query(max_length=128)],
) -> Response:
    """The sanitized upload (metadata removed, orientation applied), via a signed link."""
    verify_signed_url(c, "upload", session_id, exp, sig)
    rec = db.get(SessionRecord, session_id)
    if rec is None or rec.status != SessionStatus.ACTIVE or rec.expires_at <= c.clock():
        raise AppError(ErrorCode.RESULT_NOT_FOUND)
    if rec.image_key is None:
        raise AppError(ErrorCode.RESULT_NOT_FOUND)
    try:
        data = c.blobs.get(rec.image_key)
    except BlobNotFoundError:
        raise AppError(ErrorCode.RESULT_NOT_FOUND) from None
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=60"},
    )


def _image_info(c: ContainerDep, session_id: str, width: int, height: int) -> ImageInfo:
    url, expires = signed_image_url(c, "upload", session_id)
    return ImageInfo(width=width, height=height, format="jpeg", url=url, url_expires_at=expires)
