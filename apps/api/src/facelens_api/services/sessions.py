"""Session lifecycle: create (sanitized upload), authorize, delete, and retention sweep."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import Result, delete, select, update
from sqlalchemy.orm import Session

from facelens_api.container import Container
from facelens_api.db.models import JobRecord, SessionRecord
from facelens_api.domain.enums import JobStatus, SessionStatus
from facelens_api.domain.errors import AppError, ErrorCode
from facelens_api.imaging.sanitize import ImageLimits, SanitizedImage, sanitize_image
from facelens_api.log import get_logger
from facelens_api.ml.pipeline import prepare_face
from facelens_api.schemas.api import CONSENT_VERSION
from facelens_api.services.security import (
    hash_token,
    new_id,
    new_session_token,
    token_matches,
)
from facelens_api.storage.base import session_prefix, session_upload_key

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CreatedSession:
    record: SessionRecord
    token: str
    image: SanitizedImage
    face_checked: bool


def create_session(c: Container, raw: bytes) -> CreatedSession:
    s = c.settings
    image = sanitize_image(raw, ImageLimits(s.max_upload_bytes, s.min_image_side, s.max_image_side))
    # Face policy is enforced before anything is stored: rejected images never persist.
    prepare_face(c.registry.detector, image.pixels, s.min_face_side)
    now = c.clock()
    session_id = new_id("s")
    token = new_session_token()
    key = session_upload_key(session_id)
    c.blobs.put(key, image.data, image.content_type)
    record = SessionRecord(
        id=session_id,
        token_hash=hash_token(token),
        status=SessionStatus.ACTIVE,
        created_at=now,
        expires_at=now + timedelta(seconds=s.session_ttl_seconds),
        image_key=key,
        image_width=image.width,
        image_height=image.height,
        source_format=image.source_format,
        consent_version=CONSENT_VERSION,
    )
    try:
        with c.db.begin() as db:
            db.add(record)
    except Exception:
        c.blobs.delete_prefix(session_prefix(session_id))
        raise
    log.info(
        "session.created",
        session_id=session_id,
        image_width=image.width,
        image_height=image.height,
        file_size_bytes=len(raw),
    )
    return CreatedSession(
        record=record, token=token, image=image, face_checked=c.registry.detector is not None
    )


def load_active_session(
    db: Session,
    c: Container,
    session_id: str,
    token: str | None,
    *,
    allow_expired: bool = False,
) -> SessionRecord:
    """Return the session only if it exists, is active, unexpired, and the token matches.

    ``allow_expired`` is for deletion only: a session past its TTL that the sweeper
    hasn't reached yet must still be deletable on request.
    Every failure returns the same error so IDs can't be probed.
    """
    record = db.get(SessionRecord, session_id)
    if (
        record is None
        or record.status != SessionStatus.ACTIVE
        or (record.expires_at <= c.clock() and not allow_expired)
        or not token_matches(token, record.token_hash)
    ):
        raise AppError(ErrorCode.SESSION_NOT_FOUND)
    return record


def end_session(c: Container, session_id: str, status: SessionStatus) -> int:
    """Delete all blobs for a session and scrub user-visible results. Idempotent."""
    removed = c.blobs.delete_prefix(session_prefix(session_id))
    now = c.clock()
    with c.db.begin() as db:
        db.execute(
            update(SessionRecord)
            .where(SessionRecord.id == session_id)
            .values(status=status, ended_at=now, image_key=None)
        )
        db.execute(
            update(JobRecord)
            .where(JobRecord.session_id == session_id)
            .values(result=None, result_key=None)
        )
        db.execute(
            update(JobRecord)
            .where(
                JobRecord.session_id == session_id,
                JobRecord.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
            )
            .values(status=JobStatus.CANCELLED, finished_at=now, stage=None)
        )
    log.info("session.ended", session_id=session_id, reason=status.value, blobs_removed=removed)
    return removed


def _rowcount(result: Result[Any]) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


@dataclass(frozen=True, slots=True)
class SweepReport:
    expired_sessions: int
    stale_jobs_failed: int
    metadata_rows_purged: int


def sweep(c: Container) -> SweepReport:
    """Retention enforcement. Safe to run concurrently from several processes."""
    now = c.clock()
    with c.db() as db:
        expired_ids = list(
            db.scalars(
                select(SessionRecord.id).where(
                    SessionRecord.status == SessionStatus.ACTIVE,
                    SessionRecord.expires_at <= now,
                )
            )
        )
    for session_id in expired_ids:
        end_session(c, session_id, SessionStatus.EXPIRED)

    stale_cutoff = now - timedelta(seconds=c.settings.inference_timeout_seconds * 3 + 60)
    purge_cutoff = now - timedelta(days=c.settings.metadata_retention_days)
    with c.db.begin() as db:
        stale = _rowcount(
            db.execute(
                update(JobRecord)
                .where(
                    JobRecord.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
                    JobRecord.created_at <= stale_cutoff,
                )
                .values(
                    status=JobStatus.FAILED,
                    error_code=ErrorCode.INFERENCE_TIMEOUT,
                    finished_at=now,
                    stage=None,
                )
            )
        )
        # Ended sessions past the metadata window are removed entirely (jobs cascade).
        old_ids = select(SessionRecord.id).where(
            SessionRecord.status != SessionStatus.ACTIVE,
            SessionRecord.created_at <= purge_cutoff,
        )
        db.execute(delete(JobRecord).where(JobRecord.session_id.in_(old_ids)))
        purged = _rowcount(
            db.execute(
                delete(SessionRecord).where(
                    SessionRecord.status != SessionStatus.ACTIVE,
                    SessionRecord.created_at <= purge_cutoff,
                )
            )
        )
    c.sweeper_last_run = now
    report = SweepReport(len(expired_ids), stale, purged)
    if any((report.expired_sessions, report.stale_jobs_failed, report.metadata_rows_purged)):
        log.info(
            "retention.sweep",
            expired_sessions=report.expired_sessions,
            stale_jobs_failed=report.stale_jobs_failed,
            metadata_rows_purged=report.metadata_rows_purged,
        )
    return report
