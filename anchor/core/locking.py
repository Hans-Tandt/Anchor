"""Per-profile run lock.

Two concurrent runs of the same profile — e.g. a manual *Run now* while a
scheduled task fires — would race against the shared state DB and the
destination tree. SQLite's WAL mode protects against on-disk corruption but
not against logical races (one run skipping a file because the other already
recorded it before actually copying it). The lock here guarantees a single
active runner per profile.

Cross-platform: `msvcrt.locking` on Windows, `fcntl.flock` elsewhere. The
lock is non-blocking — acquisition fails fast with `AlreadyLockedError` so
the GUI can show a clear message instead of hanging.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from ..app_config import APP_DIR, ensure_dirs


class AlreadyLockedError(RuntimeError):
    """Raised when another process already holds the profile lock."""


def _locks_dir() -> Path:
    ensure_dirs()
    d = APP_DIR / "locks"
    d.mkdir(parents=True, exist_ok=True)
    return d


class RunLock:
    """Non-blocking advisory lock keyed by profile id.

    Used as a context manager:

        with RunLock(profile_id):
            ...

    Raises AlreadyLockedError on entry if another process holds it. The lock
    is released when the file handle closes (explicitly on __exit__, and by
    the OS if the process dies).
    """

    def __init__(self, profile_id: str):
        self.path: Path = _locks_dir() / f"{profile_id}.lock"
        self._fd: Optional[int] = None

    def __enter__(self) -> "RunLock":
        # Open with O_RDWR | O_CREAT so we have a stable fd to lock against.
        self._fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if os.name == "nt":
                import msvcrt
                # Lock the first byte; non-blocking via LK_NBLCK.
                try:
                    msvcrt.locking(self._fd, msvcrt.LK_NBLCK, 1)
                except OSError as e:
                    raise AlreadyLockedError(
                        f"Another Anchor run for this profile is already in progress "
                        f"(lock: {self.path})."
                    ) from e
            else:
                import fcntl
                try:
                    fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as e:
                    raise AlreadyLockedError(
                        f"Another Anchor run for this profile is already in progress "
                        f"(lock: {self.path})."
                    ) from e
        except Exception:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
            raise
        return self

    def __exit__(self, *exc) -> None:
        if self._fd is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                try:
                    # LK_UNLCK releases the byte we locked at offset 0.
                    os.lseek(self._fd, 0, os.SEEK_SET)
                    msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl
                try:
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
