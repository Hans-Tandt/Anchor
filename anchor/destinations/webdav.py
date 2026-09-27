"""WebDAV destination (e.g., QNAP via WebDAV)."""
from __future__ import annotations

import os
import posixpath
import re
from datetime import datetime
from typing import Iterable, List, Optional

from .base import Destination, DestinationError, FileVersion, RemoteStat, VERSIONS_PREFIX


_VERSION_SUFFIX_RE = re.compile(r"__(\d{8}T\d{6})\.bak$")

try:
    from webdav3.client import Client  # type: ignore
    from webdav3.exceptions import RemoteResourceNotFound  # type: ignore
except Exception:
    Client = None  # type: ignore
    RemoteResourceNotFound = Exception  # type: ignore

try:
    import keyring  # type: ignore
except Exception:
    keyring = None  # type: ignore


class WebDAVDestination(Destination):
    kind = "webdav"

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        remote_path: str,
        dest_id: str,
        use_https: bool = True,
        verify_tls: bool = True,
        password: Optional[str] = None,
    ):
        if Client is None:
            raise DestinationError(
                "WebDAV support requires 'webdavclient3'. "
                "Install with: pip install webdavclient3 keyring"
            )
        scheme = "https" if use_https else "http"
        if not port:
            port = 443 if use_https else 80
        self._url = f"{scheme}://{host}:{port}"
        self.remote_root = "/" + remote_path.strip("/") if remote_path.strip("/") else "/"
        self.username = username
        self.dest_id = dest_id
        self.verify_tls = verify_tls
        self._password = password
        self._client = None

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
        raise DestinationError("No WebDAV password set for this destination.")

    def _abs(self, rel_path: str) -> str:
        rel = rel_path.replace("\\", "/").lstrip("/")
        return posixpath.join(self.remote_root, rel) if rel else self.remote_root

    def connect(self) -> None:
        try:
            self._client = Client({
                "webdav_hostname": self._url,
                "webdav_login": self.username,
                "webdav_password": self._get_password(),
                "webdav_timeout": 30,
                "verbose": False,
            })
            if not self.verify_tls:
                self._client.verify = False
            # Try a tiny request to validate
            self._client.list("/")
            self._mkdir_recursive(self.remote_root)
        except DestinationError:
            raise
        except Exception as e:
            raise DestinationError(f"WebDAV connect failed: {e}") from e

    def close(self) -> None:
        self._client = None

    def _mkdir_recursive(self, path: str) -> None:
        if not path or path == "/":
            return
        parts = path.strip("/").split("/")
        cur = ""
        for p in parts:
            cur += "/" + p
            try:
                if not self._client.check(cur):
                    self._client.mkdir(cur)
            except Exception:
                # Best effort — some servers throw on existing dirs
                pass

    def exists(self, rel_path: str) -> bool:
        try:
            return bool(self._client.check(self._abs(rel_path)))
        except Exception:
            return False

    def stat(self, rel_path: str) -> Optional[RemoteStat]:
        try:
            info = self._client.info(self._abs(rel_path))
            size = int(info.get("size") or 0)
            mtime = None
            modified = info.get("modified")
            if modified:
                try:
                    mtime = datetime.strptime(
                        modified, "%a, %d %b %Y %H:%M:%S %Z"
                    ).timestamp()
                except Exception:
                    mtime = None
            return RemoteStat(size=size, mtime=mtime)
        except Exception:
            return None

    def mkdir_p(self, rel_dir: str) -> None:
        self._mkdir_recursive(self._abs(rel_dir))

    def put_file(self, local_path: str, rel_path: str, mtime: Optional[float] = None) -> None:
        # Atomic-ish two-step: upload to a .bkp.tmp sibling, then MOVE it over
        # the final path. A failed upload leaves the previous good copy intact
        # at the final path and an orphan .tmp (cleaned up on the next attempt).
        # Most WebDAV servers implement MOVE as a metadata rename, so the
        # window where the final path is absent is very small.
        final = self._abs(rel_path)
        tmp = final + ".bkp.tmp"
        try:
            self._mkdir_recursive(posixpath.dirname(final))
            # Clean a stale tmp from a previous failed run.
            try:
                if self._client.check(tmp):
                    self._client.clean(tmp)
            except Exception:
                pass
            self._client.upload_sync(remote_path=tmp, local_path=local_path)
            # MOVE with overwrite: webdavclient3 sends Overwrite: T by default.
            try:
                self._client.move(remote_path_from=tmp, remote_path_to=final, overwrite=True)
            except TypeError:
                # Older webdavclient3 signatures don't accept overwrite=.
                self._client.move(remote_path_from=tmp, remote_path_to=final)
        except Exception as e:
            # Best-effort tmp cleanup so we don't leave junk behind.
            try:
                self._client.clean(tmp)
            except Exception:
                pass
            raise DestinationError(f"WebDAV upload failed for {rel_path}: {e}") from e

    def remove(self, rel_path: str) -> None:
        try:
            self._client.clean(self._abs(rel_path))
        except Exception:
            pass

    # --- Read API --------------------------------------------------------

    def get_file(self, rel_path: str, local_path: str) -> None:
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        try:
            self._client.download_sync(
                remote_path=self._abs(rel_path), local_path=local_path
            )
        except Exception as e:
            raise DestinationError(
                f"WebDAV download failed for {rel_path}: {e}"
            ) from e

    def iter_files(self, rel_dir: str = "") -> Iterable[str]:
        base = self._abs(rel_dir) if rel_dir else self.remote_root
        root_len = len(self.remote_root.rstrip("/"))

        def _walk(path: str):
            try:
                entries = self._client.list(path)
            except Exception:
                return
            # webdavclient3 returns names (with trailing / for dirs); the
            # first entry is usually the dir itself. We probe each child.
            for name in entries:
                clean = name.rstrip("/")
                if not clean or clean == posixpath.basename(path.rstrip("/")):
                    continue
                child = posixpath.join(path, clean)
                if path == self.remote_root and clean == VERSIONS_PREFIX:
                    continue
                try:
                    if self._client.is_dir(child):
                        yield from _walk(child)
                    else:
                        rel = child[root_len:].lstrip("/")
                        yield rel
                except Exception:
                    continue
        yield from _walk(base)

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
            if not self._client.check(src):
                return None
        except Exception:
            return None
        vdir = self._version_dir(rel_path)
        self._mkdir_recursive(vdir)
        vname = self._version_basename(rel_path, version_id)
        dst = posixpath.join(vdir, vname)
        try:
            try:
                self._client.move(remote_path_from=src, remote_path_to=dst, overwrite=True)
            except TypeError:
                self._client.move(remote_path_from=src, remote_path_to=dst)
        except Exception as e:
            raise DestinationError(
                f"Failed to archive '{rel_path}' on WebDAV: {e}"
            ) from e
        rel_dir = posixpath.dirname(rel_path.replace("\\", "/"))
        return (
            f"{VERSIONS_PREFIX}/{rel_dir}/{vname}"
            if rel_dir else f"{VERSIONS_PREFIX}/{vname}"
        )

    def list_versions(self, rel_path: str) -> List[FileVersion]:
        vdir = self._version_dir(rel_path)
        try:
            entries = self._client.list(vdir)
        except Exception:
            return []
        base = posixpath.basename(rel_path)
        rel_dir = posixpath.dirname(rel_path.replace("\\", "/"))
        out: List[FileVersion] = []
        for raw in entries:
            name = raw.rstrip("/")
            if not name.startswith(base + "__"):
                continue
            m = _VERSION_SUFFIX_RE.search(name)
            if not m:
                continue
            full = posixpath.join(vdir, name)
            try:
                info = self._client.info(full)
                size = int(info.get("size") or 0)
                mtime = None
                modified = info.get("modified")
                if modified:
                    try:
                        mtime = datetime.strptime(
                            modified, "%a, %d %b %Y %H:%M:%S %Z"
                        ).timestamp()
                    except Exception:
                        mtime = None
            except Exception:
                size = 0
                mtime = None
            archive_rel = (
                f"{VERSIONS_PREFIX}/{rel_dir}/{name}"
                if rel_dir else f"{VERSIONS_PREFIX}/{name}"
            )
            out.append(FileVersion(
                rel_path=rel_path, version_id=m.group(1),
                archive_rel=archive_rel, size=size, mtime=mtime,
            ))
        out.sort(key=lambda v: v.version_id, reverse=True)
        return out

    def prune_versions(self, rel_path: str, keep: int) -> None:
        versions = self.list_versions(rel_path)
        doomed = versions if keep <= 0 else versions[keep:]
        for v in doomed:
            try:
                self._client.clean(self._abs(v.archive_rel))
            except Exception:
                pass
