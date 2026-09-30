from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from facelens_api.storage.base import BlobNotFoundError, validate_key


class LocalBlobStore:
    """Filesystem store for development. Production uses private, encrypted object storage."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / validate_key(key)).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("invalid blob key")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write so readers never see a partial file.
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError:
            raise BlobNotFoundError(key) from None

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> int:
        path = self._path(prefix)
        if path.is_file():
            path.unlink()
            return 1
        if not path.is_dir():
            return 0
        count = sum(1 for p in path.rglob("*") if p.is_file())
        shutil.rmtree(path)
        return count

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def healthcheck(self) -> bool:
        probe = self.root / ".healthcheck"
        try:
            probe.write_bytes(b"ok")
            probe.unlink()
        except OSError:
            return False
        return True
