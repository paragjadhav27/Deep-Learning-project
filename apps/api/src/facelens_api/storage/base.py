"""Blob storage abstraction. Implementations: local filesystem (dev); S3-compatible (Phase 2)."""

from __future__ import annotations

import re
from typing import Protocol

# Keys are generated server-side only; this pattern also blocks path traversal.
_KEY_RE = re.compile(r"^[A-Za-z0-9_\-]+(/[A-Za-z0-9_\-]+)*(\.[a-z0-9]{2,5})?$")


class BlobNotFoundError(KeyError):
    pass


def validate_key(key: str) -> str:
    if not _KEY_RE.fullmatch(key) or ".." in key:
        raise ValueError("invalid blob key")
    return key


class BlobStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def delete_prefix(self, prefix: str) -> int:
        """Delete every blob under ``prefix``; return the count removed."""
        ...

    def exists(self, key: str) -> bool: ...

    def healthcheck(self) -> bool: ...


def session_prefix(session_id: str) -> str:
    return validate_key(f"sessions/{session_id}")


def session_upload_key(session_id: str) -> str:
    return validate_key(f"sessions/{session_id}/upload.jpg")


def job_result_key(session_id: str, job_id: str) -> str:
    return validate_key(f"sessions/{session_id}/results/{job_id}.jpg")
