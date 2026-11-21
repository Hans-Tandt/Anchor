r"""App-level configuration: where profiles, state DBs, and logs live.

All paths default under %APPDATA%\Anchor on Windows, so the app is
fully portable per-user and doesn't pollute the project directory.
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, asdict, field, fields, MISSING
from pathlib import Path
from typing import Any, Dict


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


# Profile / destination ids end up in file names (state DB, lock file,
# profile JSON) and in schtasks command lines, so they must be plain tokens.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def is_safe_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_SAFE_ID_RE.match(value))


def coerce_fields(cls, data: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only known keys of dataclass `cls` whose JSON values have the
    same type as the field's default; drop the rest so the default is used.

    Guards against hand-edited / corrupted JSON (e.g. "25" for an int, a
    string for a list) crashing the engine far from where it was loaded.
    """
    out: Dict[str, Any] = {}
    if not isinstance(data, dict):
        return out
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        if f.default is not MISSING:
            default = f.default
        elif f.default_factory is not MISSING:  # type: ignore[misc]
            default = f.default_factory()  # type: ignore[misc]
        else:
            out[f.name] = value
            continue
        if isinstance(default, bool):
            ok = isinstance(value, bool)
        elif isinstance(default, int):
            ok = isinstance(value, int) and not isinstance(value, bool)
        elif isinstance(default, float):
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif isinstance(default, str):
            ok = isinstance(value, str)
        elif isinstance(default, list):
            ok = isinstance(value, list)
            if ok and all(isinstance(x, str) for x in default):
                value = [x for x in value if isinstance(x, str)]
        else:
            ok = True
        if ok:
            out[f.name] = value
    return out


def atomic_write_text(path: Path, text: str) -> None:
    """Write `text` to `path` via a temp sibling + os.replace so a crash
    mid-write never leaves a truncated settings/profile file."""
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


@dataclass
class AppSettings:
    """Global app preferences (persisted to settings.json)."""

    theme: str = "dark"  # "dark" | "light" | "system"
    verify_with_hash: bool = False  # True = SHA-256 check; False = mtime+size only
    parallel_workers: int = 4
    auto_run_on_drive_plug_in: bool = False
    last_profile: str = ""
    # Seconds to pause between the scan phase and the copy phase so the user
    # can read the "X to copy, Y unchanged" summary before the bar resets and
    # the copy starts. 0 = no pause. The pause is interruptible by Cancel.
    scan_pause_seconds: int = 3
    # Main-window log card collapsed state. Persists across sessions so the
    # user doesn't have to re-collapse it every launch.
    log_collapsed: bool = False
    # Desktop notification (tray balloon) when a run finishes while the
    # window is not focused.
    notifications: bool = True
    # Navigation rail expanded (labels visible) or compact (icons only).
    nav_expanded: bool = True
    # SFTP/WebDAV stored credentials are *per profile*, not here.

    @classmethod
    def load(cls) -> "AppSettings":
        ensure_dirs()
        if SETTINGS_FILE.exists():
            try:
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                return cls(**coerce_fields(cls, data))
            except Exception:
                pass
        return cls()

    def save(self) -> None:
        ensure_dirs()
        atomic_write_text(SETTINGS_FILE, json.dumps(asdict(self), indent=2))
