"""SFTP destination — useful for backing up to a QNAP NAS remotely.

Requires `paramiko`. If it isn't installed, opening this destination raises
DestinationError with an informative message.

Credentials: prefer Windows Credential Manager via `keyring` (service name
"Anchor:<dest_id>"). Falls back to a runtime-provided password.
"""
from __future__ import annotations

import io
import os
import posixpath
import re
import stat as _stat
from pathlib import Path
from typing import Iterable, List, Optional

from .base import Destination, DestinationError, FileVersion, RemoteStat, VERSIONS_PREFIX


_VERSION_SUFFIX_RE = re.compile(r"__(\d{8}T\d{6})\.bak$")


try:
    import paramiko  # type: ignore
except Exception:  # pragma: no cover
    paramiko = None  # type: ignore

try:
    import keyring  # type: ignore
except Exception:
    keyring = None  # type: ignore


class SFTPDestination(Destination):
    kind = "sftp"

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        remote_path: str,
        dest_id: str,
        password: Optional[str] = None,
    ):
        if paramiko is None:
            raise DestinationError(
                "SFTP support requires the 'paramiko' package. "
                "Install with: pip install paramiko keyring"
            )
        self.host = host
        self.port = port or 22
        self.username = username
        self.remote_root = remote_path.rstrip("/") or "/"
        self.dest_id = dest_id
        self._password = password
        self._client = None
        self._sftp = None

    # --- helpers ----------------------------------------------------------

    def _abs(self, rel_path: str) -> str:
        rel = rel_path.replace("\\", "/").lstrip("/")
        return posixpath.join(self.remote_root, rel) if rel else self.remote_root

    def _get_password(self) -> str:
        if self._password:
            return self._password
        if keyring is not None:
            try:
                pw = keyring.get_password("Anchor", self.dest_id)
                if pw:
                    return pw
            except Exception:
                pass
        raise DestinationError(
            "No SFTP password set. Open the destination settings and "
            "enter the password so it can be saved to Windows Credential Manager."
        )

    # --- API --------------------------------------------------------------

    def connect(self) -> None:
        try:
            self._client = paramiko.SSHClient()
            self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self._client.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self._get_password(),
                timeout=15,
                banner_timeout=15,
            )
            self._sftp = self._client.open_sftp()
            # Ensure root exists
            self._mkdir_recursive(self.remote_root)
        except DestinationError:
            raise
        except Exception as e:
            raise DestinationError(f"SFTP connect failed: {e}") from e

    def close(self) -> None:
        try:
            if self._sftp:
                self._sftp.close()
        except Exception:
            pass
        try:
            if self._client:
                self._client.close()
        except Exception:
            pass
        self._sftp = self._client = None

    def _mkdir_recursive(self, path: str) -> None:
        if not path or path == "/":
            return
        parts = path.strip("/").split("/")
        cur = "/"
        for p in parts:
            cur = posixpath.join(cur, p) if cur != "/" else "/" + p
            try:
                self._sftp.stat(cur)
            except FileNotFoundError:
                try:
                    self._sftp.mkdir(cur)
                except IOError:
                    pass

    def exists(self, rel_path: str) -> bool:
        try:
            self._sftp.stat(self._abs(rel_path))
            return True
        except FileNotFoundError:
            return False
        except IOError:
            return False

    def stat(self, rel_path: str) -> Optional[RemoteStat]:
        try:
            st = self._sftp.stat(self._abs(rel_path))
            return RemoteStat(size=st.st_size or 0, mtime=float(st.st_mtime) if st.st_mtime else None)
        except (FileNotFoundError, IOError):
            return None

    def mkdir_p(self, rel_dir: str) -> None:
        self._mkdir_recursive(self._abs(rel_dir))

    def put_file(self, local_path: str, rel_path: str, mtime: Optional[float] = None) -> None:
        remote = self._abs(rel_path)
        tmp = remote + ".bkp.tmp"
        self._mkdir_recursive(posixpath.dirname(remote))
        try:
            self._sftp.put(local_path, tmp, confirm=True)
            self._atomic_rename(tmp, remote)
            if mtime is not None:
                try:
                    self._sftp.utime(remote, (mtime, mtime))
                except Exception:
                    pass
        except Exception as e:
            try:
                self._sftp.remove(tmp)
            except Exception:
                pass
            raise DestinationError(f"SFTP put failed for {rel_path}: {e}") from e

    def _atomic_rename(self, src: str, dst: str) -> None:
        """Rename src -> dst atomically, overwriting dst if it exists.

        Prefers OpenSSH's `posix-rename@openssh.com` extension (true atomic
        overwrite — the destination is never absent). Falls back to
        remove-then-rename only if the server doesn't support it; that fallback
        opens a small window where dst is missing, but it's the best we can do
        on a non-OpenSSH SFTP server.
        """
        posix_rename = getattr(self._sftp, "posix_rename", None)
        if posix_rename is not None:
            try:
                posix_rename(src, dst)
                return
            except (IOError, OSError):
                # Some servers advertise the extension but reject it; fall
                # through to the legacy path below.
                pass
        # Legacy fallback: there's a brief window where dst doesn't exist.
        try:
            self._sftp.remove(dst)
        except (FileNotFoundError, IOError):
            pass
        self._sftp.rename(src, dst)

    def remove(self, rel_path: str) -> None:
        try:
            self._sftp.remove(self._abs(rel_path))
        except FileNotFoundError:
            pass
        except IOError as e:
            raise DestinationError(f"SFTP remove failed: {e}") from e

    # --- Read API --------------------------------------------------------

    def get_file(self, rel_path: str, local_path: str) -> None:
        remote = self._abs(rel_path)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        try:
            self._sftp.get(remote, local_path)
        except (FileNotFoundError, IOError) as e:
            raise DestinationError(f"SFTP get failed for {rel_path}: {e}") from e

    def iter_files(self, rel_dir: str = "") -> Iterable[str]:
        base_abs = self._abs(rel_dir) if rel_dir else self.remote_root
        root_len = len(self.remote_root.rstrip("/"))

        def _walk(path: str):
            try:
                entries = self._sftp.listdir_attr(path)
            except (FileNotFoundError, IOError):
                return
            for a in entries:
                name = a.filename
                if name in (".", ".."):
                    continue
                if path == self.remote_root and name == VERSIONS_PREFIX:
                    continue  # skip archive subtree
                full = posixpath.join(path, name)
                if a.st_mode is not None and _stat.S_ISDIR(a.st_mode):
                    yield from _walk(full)
                else:
                    rel = full[root_len:].lstrip("/")
                    yield rel
        yield from _walk(base_abs)

    # --- Versioning ------------------------------------------------------

    def _version_dir(self, rel_path: str) -> str:
        rel_dir = posixpath.dirname(rel_path.replace("\\", "/"))
        return self._abs(
            f"{VERSIONS_PREFIX}/{rel_dir}" if rel_dir else VERSIONS_PREFIX
        )

    def _version_basename(self, rel_path: str, version_id: str) -> str:
        return f"{posixpath.basename(rel_path)}__{version_id}.bak"

    def archive_existing(self, rel_path: str, version_id: str) -> Optional[str]:
        src = self._abs(rel_path)
        try:
            self._sftp.stat(src)
        except (FileNotFoundError, IOError):
            return None
        vdir = self._version_dir(rel_path)
        self._mkdir_recursive(vdir)
        vname = self._version_basename(rel_path, version_id)
        dst = posixpath.join(vdir, vname)
        try:
            self._atomic_rename(src, dst)
        except Exception as e:
            raise DestinationError(
                f"Failed to archive '{rel_path}' on SFTP: {e}"
            ) from e
        rel_dir = posixpath.dirname(rel_path.replace("\\", "/"))
        return (
            f"{VERSIONS_PREFIX}/{rel_dir}/{vname}"
            if rel_dir else f"{VERSIONS_PREFIX}/{vname}"
        )

    def list_versions(self, rel_path: str) -> List[FileVersion]:
        vdir = self._version_dir(rel_path)
        try:
            entries = self._sftp.listdir_attr(vdir)
        except (FileNotFoundError, IOError):
            return []
        base = posixpath.basename(rel_path)
        rel_dir = posixpath.dirname(rel_path.replace("\\", "/"))
        out: List[FileVersion] = []
        for a in entries:
            name = a.filename
            if not name.startswith(base + "__"):
                continue
            m = _VERSION_SUFFIX_RE.search(name)
            if not m:
                continue
            archive_rel = (
                f"{VERSIONS_PREFIX}/{rel_dir}/{name}"
                if rel_dir else f"{VERSIONS_PREFIX}/{name}"
            )
            out.append(FileVersion(
                rel_path=rel_path, version_id=m.group(1),
                archive_rel=archive_rel,
                size=a.st_size or 0,
                mtime=float(a.st_mtime) if a.st_mtime else None,
            ))
        out.sort(key=lambda v: v.version_id, reverse=True)
        return out

    def prune_versions(self, rel_path: str, keep: int) -> None:
        versions = self.list_versions(rel_path)
        doomed = versions if keep <= 0 else versions[keep:]
        for v in doomed:
            try:
                self._sftp.remove(self._abs(v.archive_rel))
            except (FileNotFoundError, IOError):
                pass
