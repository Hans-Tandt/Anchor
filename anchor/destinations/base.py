"""Destination interface.

A Destination is a "place files can be put". The engine talks to all
destinations through this interface, whether they're local folders,
network shares, OneDrive (which is just a local folder!), SFTP servers,
or WebDAV endpoints.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Iterable, List, Optional


# Versioned files live under this subtree at the destination root. Each old
# version is moved here as `<rel_path>__<YYYYMMDDTHHMMSS>.bak` so users can
# roll back after accidental edits, ransomware encryption, or mirror-delete.
VERSIONS_PREFIX = "_anchor_versions"


class DestinationError(Exception):
    """Raised when a destination operation fails in a recoverable way."""


def is_safe_name(name: str) -> bool:
    """True if `name` is a single, harmless path component.

    Used to filter names returned by a destination listing (SFTP/WebDAV
    servers and the on-disk versions tree are not trusted). Rejects empty,
    ".", "..", anything with a path separator, a drive/stream colon or a
    control character — none of which a Windows source file can have.
    """
    if not name or name in (".", ".."):
        return False
    if "/" in name or "\\" in name or ":" in name:
        return False
    return not any(ord(c) < 32 for c in name)


def is_safe_rel_path(rel_path: str) -> bool:
    """True if every component of a forward/backslash rel path is safe."""
    if not rel_path:
        return False
    return all(is_safe_name(p) for p in rel_path.replace("\\", "/").split("/"))


def check_rel_path(rel_path: str) -> str:
    """Normalize a destination rel path and refuse traversal.

    Leading slashes are stripped (as the backends always did); a ".."
    component or a NUL byte raises DestinationError so no backend can be
    driven outside its root.
    """
    rel = rel_path.replace("\\", "/").lstrip("/")
    if "\x00" in rel or any(p == ".." for p in rel.split("/")):
        raise DestinationError(f"Unsafe destination path: {rel_path!r}")
    return rel


def safe_local_target(base_dir: str, rel_path: str) -> str:
    """Join `rel_path` under `base_dir`, refusing anything that escapes it.

    Use this when turning a destination rel path into a local restore target:
    raises DestinationError for "..", absolute paths, drive letters, etc.
    """
    import os
    if not is_safe_rel_path(rel_path):
        raise DestinationError(f"Refusing unsafe restore path: {rel_path!r}")
    base = os.path.abspath(base_dir)
    target = os.path.abspath(os.path.join(base, rel_path.replace("/", os.sep)))
    try:
        inside = os.path.commonpath([base, target]) == base
    except ValueError:
        inside = False
    if not inside or target == base:
        raise DestinationError(f"Refusing restore outside {base_dir!r}: {rel_path!r}")
    return target


@dataclass
class RemoteStat:
    size: int
    mtime: Optional[float]  # POSIX timestamp, may be None for some backends


@dataclass
class FileVersion:
    """One archived version of a backed-up file."""
    rel_path: str         # original rel path (without timestamp suffix)
    version_id: str       # the YYYYMMDDTHHMMSS suffix
    archive_rel: str      # full rel path under VERSIONS_PREFIX
    size: int
    mtime: Optional[float]


class Destination(abc.ABC):
    """Abstract destination.

    Implementations must ensure that `put_file()` is atomic enough that a
    crash mid-write doesn't leave a partial file at the final path. The
    simplest approach: write to a `.tmp` sibling, then rename.

    Versioning is opt-in: the engine calls `archive_existing()` before an
    overwrite or a mirror-delete when the profile's `keep_versions > 0`, then
    calls `prune_versions()` afterward to cap retention. Restore reads via
    `list_versions()` and `get_file()`.
    """

    kind: str = "base"

    @abc.abstractmethod
    def connect(self) -> None: ...

    @abc.abstractmethod
    def close(self) -> None: ...

    @abc.abstractmethod
    def exists(self, rel_path: str) -> bool: ...

    @abc.abstractmethod
    def stat(self, rel_path: str) -> Optional[RemoteStat]: ...

    @abc.abstractmethod
    def mkdir_p(self, rel_dir: str) -> None: ...

    @abc.abstractmethod
    def put_file(self, local_path: str, rel_path: str, mtime: Optional[float] = None) -> None: ...

    @abc.abstractmethod
    def remove(self, rel_path: str) -> None: ...

    # --- Read API (used by restore + verify) -----------------------------

    @abc.abstractmethod
    def get_file(self, rel_path: str, local_path: str) -> None:
        """Download/copy a destination file to a local path."""

    def iter_files(self, rel_dir: str = "") -> Iterable[str]:
        """Yield rel_paths of every regular file under rel_dir (recursive).

        Skips the `_anchor_versions` subtree by default. Default
        implementation raises; override per backend.
        """
        raise NotImplementedError

    # --- Versioning (opt-in; default no-op) -------------------------------

    def archive_existing(self, rel_path: str, version_id: str) -> Optional[str]:
        """Move the current file at rel_path into the versions subtree.

        Returns the archive rel_path on success, or None if no current file
        existed (nothing to archive). Default no-op for backends that don't
        support versioning yet — they just lose history.
        """
        return None

    def list_versions(self, rel_path: str) -> List[FileVersion]:
        """List archived versions of rel_path, newest first. Default empty."""
        return []

    def prune_versions(self, rel_path: str, keep: int) -> None:
        """Remove versions of rel_path beyond the `keep` most recent.

        keep <= 0 means "remove all archived versions". Default no-op.
        """
        return None

    # --- Context manager --------------------------------------------------

    def __enter__(self) -> "Destination":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()
