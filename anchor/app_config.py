r"""App-level configuration: where profiles, state DBs, and logs live.

All paths default under %APPDATA%\Anchor on Windows, so the app is
fully portable per-user and doesn't pollute the project directory.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path


def _appdata_root() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return Path(base) / "Anchor"


def _project_root() -> Path:
    """Folder that contains the `anchor` package. Used as the default home
    for logs when the app folder is user-writable."""
    return Path(__file__).resolve().parent.parent


def _writable_logs_dir() -> Path:
    """Where log files live.

    * PyInstaller build: always `%APPDATA%\\Anchor\\logs\\` — the install
      folder may be under Program Files (read-only for standard users) and
      shouldn't hold per-user data anyway.
    * Source install: prefer `<project>/logs/` for discoverability, fall
      back to `%APPDATA%\\Anchor\\logs\\` only when the project folder
      isn't writable.
    """
    if getattr(sys, "frozen", False):
        return _appdata_root() / "logs"
    candidate = _project_root() / "logs"
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        # Probe writability with a tiny sentinel file.
        probe = candidate / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return candidate
    except OSError:
        return _appdata_root() / "logs"


APP_DIR: Path = _appdata_root()
PROFILES_DIR: Path = APP_DIR / "profiles"
STATE_DIR: Path = APP_DIR / "state"
LOGS_DIR: Path = _writable_logs_dir()
SETTINGS_FILE: Path = APP_DIR / "settings.json"


def ensure_dirs() -> None:
    # Per-user data (profiles, state DBs, settings) stays under %APPDATA% so
    # multiple Windows users on the same machine each get their own. Logs
    # alone live next to the app for discoverability.
    for d in (APP_DIR, PROFILES_DIR, STATE_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)


@dataclass
class AppSettings:
    """Global app preferences (persisted to settings.json)."""

    theme: str = "dark"  # "dark" | "light"
    verify_with_hash: bool = False  # True = SHA-256 check; False = mtime+size only
    parallel_workers: int = 4
    auto_run_on_drive_plug_in: bool = False
    last_profile: str = ""
    # Seconds to pause between the scan phase and the copy phase so the user
    # can read the "X to copy, Y unchanged" summary before the bar resets and
    # the copy starts. 0 = no pause. The pause is interruptible by Cancel.
    scan_pause_seconds: int = 3
    # SFTP/WebDAV stored credentials are *per profile*, not here.

    @classmethod
    def load(cls) -> "AppSettings":
        ensure_dirs()
        if SETTINGS_FILE.exists():
            try:
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                return cls(**{k: v for k, v in data.items() if k in cls.__annotations__})
            except Exception:
                pass
        return cls()

    def save(self) -> None:
        ensure_dirs()
        SETTINGS_FILE.write_text(
            json.dumps(asdict(self), indent=2), encoding="utf-8"
        )
