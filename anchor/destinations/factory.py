"""Construct a Destination from a DestinationConfig."""
from __future__ import annotations

from typing import Optional

from .base import Destination, DestinationError
from .local import LocalDestination


def open_destination(cfg, preserve_metadata: bool = True, password: Optional[str] = None) -> Destination:
    """Return a Destination instance suitable for `cfg`.

    Raises DestinationError if config is invalid or optional deps are missing.
    """
    kind = (cfg.kind or "local").lower()
    if kind == "local":
        return LocalDestination(cfg.path, preserve_metadata=preserve_metadata)
    if kind == "sftp":
        from .sftp import SFTPDestination
        return SFTPDestination(
            host=cfg.host, port=cfg.port, username=cfg.username,
            remote_path=cfg.remote_path, dest_id=cfg.id, password=password,
        )
    if kind == "webdav":
        from .webdav import WebDAVDestination
        return WebDAVDestination(
            host=cfg.host, port=cfg.port, username=cfg.username,
            remote_path=cfg.remote_path, dest_id=cfg.id,
            use_https=cfg.use_https, verify_tls=cfg.verify_tls,
            password=password,
        )
    raise DestinationError(f"Unknown destination kind: {cfg.kind!r}")


def test_destination(cfg, password: Optional[str] = None) -> str:
    """Try to connect to a destination. Returns "" on success or an error msg."""
    try:
        d = open_destination(cfg, password=password)
        d.connect()
        d.close()
        return ""
    except DestinationError as e:
        return str(e)
    except Exception as e:
        return f"Unexpected error: {e}"
