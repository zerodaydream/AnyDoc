"""Storage boundary. Local disk now; an S3 implementation keeps the same methods."""

import hashlib
import os
import tempfile
from collections.abc import AsyncIterator
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from backend.core.errors import InvalidFile


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    sha256: str
    size: int


class Storage(Protocol):
    async def put_stream(self, chunks: AsyncIterator[bytes], max_bytes: int) -> StoredObject: ...
    def local_path(self, key: str) -> AbstractContextManager[Path]: ...
    def delete(self, key: str) -> None: ...


class LocalDiskStorage:
    """Content-addressed, immutable files under DATA_DIR/objects/ab/abcdef..."""

    def __init__(self, root: Path) -> None:
        self.root = root / "objects"
        self.tmp = root / "tmp"
        self.root.mkdir(parents=True, exist_ok=True)
        self.tmp.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if len(key) != 64 or not all(c in "0123456789abcdef" for c in key):
            raise ValueError("invalid storage key")
        return self.root / key[:2] / key

    async def put_stream(self, chunks: AsyncIterator[bytes], max_bytes: int) -> StoredObject:
        digest, size = hashlib.sha256(), 0
        fd, tmp_name = tempfile.mkstemp(dir=self.tmp)
        try:
            # shortcut: sync writes of small chunks on local disk; move to a thread if uploads get large/slow.
            with os.fdopen(fd, "wb") as f:
                async for chunk in chunks:
                    size += len(chunk)
                    if size > max_bytes:
                        raise InvalidFile("too_large", f"File is larger than {max_bytes // 2**20} MB.")
                    digest.update(chunk)
                    f.write(chunk)
            if size == 0:
                raise InvalidFile("empty_file", "The file is empty.")
            key = digest.hexdigest()
            dest = self._path(key)
            dest.parent.mkdir(exist_ok=True)
            if dest.exists():  # same bytes already stored: originals are immutable, keep the first copy
                os.unlink(tmp_name)
            else:
                os.replace(tmp_name, dest)
                os.chmod(dest, 0o444)
            return StoredObject(key, key, size)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)  # noqa: ASYNC240 - cleanup path, tiny syscall
            raise

    def local_path(self, key: str) -> AbstractContextManager[Path]:
        return nullcontext(self._path(key))

    def delete(self, key: str) -> None:
        """Remove a stored original. Only for admin deletion, and only once no version references the key."""
        self._path(key).unlink(missing_ok=True)


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        from backend.core.config import get_settings

        _storage = LocalDiskStorage(get_settings().data_dir)
    return _storage
