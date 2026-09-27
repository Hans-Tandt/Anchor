"""Local destination — covers local drives, USB drives, UNC paths, and the
OneDrive folder (which is just a local path that the OneDrive client syncs).
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Iterable, List, Optional

from .base import Destination, DestinationError, FileVersion, RemoteStat, VERSIONS_PREFIX


_VERSION_SUFFIX_RE = re.compile(r"__(\d{8}T\d{6})\.bak$")


def _long_path(p: str) -> str:
    """On Windows, add the `\\\\?\\` prefix to paths that risk MAX_PATH (260).

    Without the prefix, deep destination trees silently fail with cryptic
    OSError. The prefix bypasses the limit and requires:
      - an absolute path,
      - backslash separators (no forward slashes),
      - and `\\\\?\\UNC\\server\\share\\...` form for UNC paths.

    Paths already prefixed or below the conservative 240-char threshold are
    returned untouched so the prefix doesn't show up in logs needlessly.
    """
    if os.name != "nt" or not p:
        return p
    if p.startswith("\\\\?\\"):
        return p
    if len(p) < 240:
        return p
    p = p.replace("/", "\\")
    if p.startswith("\\\\"):
        # UNC: \\server\share\path  ->  \\?\UNC\server\share\path
        return "\\\\?\\UNC\\" + p.lstrip("\\")
    return "\\\\?\\" + p


def _fsync_path(path: str) -> None:
    """Best-effort flush of a file or directory to its underlying storage.

    Used to make the .tmp file's bytes — and on POSIX the directory entry of
    the subsequent rename — durable before the engine records success in the
    state DB. Errors are swallowed: fsync on some filesystems (notably some
    network filesystems and a few removable-drive filesystems) raises EINVAL
    or simply isn't supported, and we'd rather skip the flush than abort the
    whole copy.
    """
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


class LocalDestination(Destination):
    kind = "local"

    def __init__(self, root: str, preserve_metadata: bool = True):
        self.root = root.rstrip("\\/")
        if not self.root:
            raise DestinationError("Empty destination path")
        self.preserve_metadata = preserve_metadata

    # --- API ---------------------------------------------------------------

    def connect(self) -> None:
        # Create the root if it doesn't exist (best-effort).
        try:
            Path(_long_path(self.root)).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise DestinationError(
                f"Cannot access destination '{self.root}': {e}"
            ) from e

    def close(self) -> None:
        pass

    def _abs(self, rel_path: str) -> str:
        rel = rel_path.replace("/", os.sep).lstrip(os.sep)
        return _long_path(os.path.join(self.root, rel))

    def exists(self, rel_path: str) -> bool:
        return os.path.exists(self._abs(rel_path))

    def stat(self, rel_path: str) -> Optional[RemoteStat]:
        try:
            st = os.stat(self._abs(rel_path))
            return RemoteStat(size=st.st_size, mtime=st.st_mtime)
        except OSError:
            return None

    def mkdir_p(self, rel_dir: str) -> None:
        Path(self._abs(rel_dir)).mkdir(parents=True, exist_ok=True)

    def put_file(self, local_path: str, rel_path: str, mtime: Optional[float] = None) -> None:
        dest = self._abs(rel_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + ".bkp.tmp"
        try:
            if self.preserve_metadata:
                shutil.copy2(local_path, tmp)
            else:
                shutil.copy(local_path, tmp)
            # Force the bytes to disk before committing the rename. Without
            # this, a crash between rename and the next OS flush would leave a
            # renamed-but-empty file at `dest` while the state DB still says
            # "backed up" — silent data loss.
            _fsync_path(tmp)
            os.replace(tmp, dest)
            # On POSIX, fsync the containing directory so the rename itself is
            # durable (NTFS journals rename ops on Windows, so it's a no-op).
            if os.name != "nt":
                _fsync_path(os.path.dirname(dest))
            if mtime is not None and not self.preserve_metadata:
                try:
                    os.utime(dest, (mtime, mtime))
                except OSError:
                    pass
        except Exception as e:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            raise DestinationError(f"Failed to copy to '{dest}': {e}") from e

    def remove(self, rel_path: str) -> None:
        try:
            os.remove(self._abs(rel_path))
        except FileNotFoundError:
            pass
        except OSError as e:
            raise DestinationError(f"Failed to delete '{rel_path}': {e}") from e

    # --- Read API --------------------------------------------------------

    def get_file(self, rel_path: str, local_path: str) -> None:
        src = self._abs(rel_path)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        try:
            shutil.copy2(src, local_path)
        except OSError as e:
            raise DestinationError(f"Failed to read '{rel_path}': {e}") from e

    def iter_files(self, rel_dir: str = "") -> Iterable[str]:
        base = self._abs(rel_dir) if rel_dir else _long_path(self.root)
        root_len = len(_long_path(self.root))
        for here, dirs, files in os.walk(base):
            # Skip the versions subtree so callers don't see archive entries.
            dirs[:] = [d for d in dirs if d != VERSIONS_PREFIX]
            for name in files:
                full = os.path.join(here, name)
                rel = full[root_len:].lstrip("\\/").replace("\\", "/")
                yield rel

    # --- Versioning ------------------------------------------------------

    def _version_dir(self, rel_path: str) -> str:
        """Versions for a file live next to it under _anchor_versions/<rel_dir>."""
        rel_dir, _ = os.path.split(rel_path.replace("\\", "/"))
        return self._abs(f"{VERSIONS_PREFIX}/{rel_dir}" if rel_dir else VERSIONS_PREFIX)

    def _version_basename(self, rel_path: str, version_id: str) -> str:
        base = os.path.basename(rel_path.replace("\\", "/"))
        return f"{base}__{version_id}.bak"

    def archive_existing(self, rel_path: str, version_id: str) -> Optional[str]:
        src = self._abs(rel_path)
        if not os.path.exists(src):
            return None
        vdir = self._version_dir(rel_path)
        os.makedirs(vdir, exist_ok=True)
        vname = self._version_basename(rel_path, version_id)
        dst = os.path.join(vdir, vname)
        try:
            # Rename if same filesystem (atomic, no copy). Falls back to copy
            # + remove if rename fails (e.g. cross-volume — rare since both
            # paths are under the same destination root).
            os.replace(src, dst)
        except OSError:
            try:
                shutil.copy2(src, dst)
                os.remove(src)
            except OSError as e:
                raise DestinationError(
                    f"Failed to archive existing '{rel_path}': {e}"
                ) from e
        # Return a forward-slash rel path under the versions prefix for
        # consistency with other Destination APIs.
        rel_dir, _ = os.path.split(rel_path.replace("\\", "/"))
        return (
            f"{VERSIONS_PREFIX}/{rel_dir}/{vname}"
            if rel_dir else f"{VERSIONS_PREFIX}/{vname}"
        )

    def list_versions(self, rel_path: str) -> List[FileVersion]:
        vdir = self._version_dir(rel_path)
        if not os.path.isdir(vdir):
            return []
        base = os.path.basename(rel_path.replace("\\", "/"))
        out: List[FileVersion] = []
        rel_dir, _ = os.path.split(rel_path.replace("\\", "/"))
        for name in os.listdir(vdir):
            if not name.startswith(base + "__"):
                continue
            m = _VERSION_SUFFIX_RE.search(name)
            if not m:
                continue
            full = os.path.join(vdir, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            archive_rel = (
                f"{VERSIONS_PREFIX}/{rel_dir}/{name}"
                if rel_dir else f"{VERSIONS_PREFIX}/{name}"
            )
            out.append(FileVersion(
                rel_path=rel_path, version_id=m.group(1),
                archive_rel=archive_rel, size=st.st_size, mtime=st.st_mtime,
            ))
        # Newest first
        out.sort(key=lambda v: v.version_id, reverse=True)
        return out

    def prune_versions(self, rel_path: str, keep: int) -> None:
        versions = self.list_versions(rel_path)
        if keep <= 0:
            doomed = versions
        else:
            doomed = versions[keep:]
        for v in doomed:
            try:
                os.remove(self._abs(v.archive_rel))
            except OSError:
                pass
