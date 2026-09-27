"""BackupProfile model + on-disk persistence (JSON files in PROFILES_DIR)."""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

from ..app_config import PROFILES_DIR, ensure_dirs


# --- Destination config ------------------------------------------------------

@dataclass
class DestinationConfig:
    """A destination for a backup.

    kind:
        "local"   – any path: local drive, USB, UNC (\\NAS\share), OneDrive folder
        "sftp"    – remote via SSH/SFTP (e.g., QNAP when away from home)
        "webdav"  – remote via WebDAV

    For "local", only `path` is used.
    For "sftp"/"webdav", host/port/username/remote_path are used.
    Passwords are *not* stored; we read them from Windows Credential Manager
    by service name "Anchor:<destination_id>".
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    kind: str = "local"          # "local" | "sftp" | "webdav"
    label: str = ""              # user-friendly name shown in GUI
    path: str = ""               # for "local"
    host: str = ""               # for sftp/webdav
    port: int = 22               # 22 sftp, 443/80 webdav
    username: str = ""
    remote_path: str = ""        # for sftp/webdav
    use_https: bool = True       # for webdav
    verify_tls: bool = True      # for webdav

    def display(self) -> str:
        if self.label:
            return self.label
        if self.kind == "local":
            return self.path or "(unset local path)"
        return f"{self.kind}://{self.username}@{self.host}{self.remote_path}"


# --- Profile model -----------------------------------------------------------

@dataclass
class BackupProfile:
    """A single backup job: which folders → which destinations, plus options."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = "New Backup"
    sources: List[str] = field(default_factory=list)
    destinations: List[DestinationConfig] = field(default_factory=list)

    # Exclusion patterns (glob-style, applied to relative path)
    exclude_globs: List[str] = field(default_factory=lambda: [
        "*.tmp", "*.log", "~$*", "Thumbs.db", ".DS_Store",
        "node_modules", "__pycache__", ".venv", ".git",
    ])
    exclude_dirs: List[str] = field(default_factory=list)  # absolute or basename

    # Engine options
    verify_with_hash: bool = False     # SHA-256 (slow) vs mtime+size (fast)
    mirror_deletions: bool = False     # remove dest files that vanished from source
    # Safety cap: abort mirror-delete on a destination if it would remove more
    # than this percent of known files there. Guards against accidentally wiping
    # a backup when a source goes missing or is mass-renamed. 0 disables the cap.
    mirror_max_delete_pct: int = 25
    # Versioning: keep up to this many previous versions of each file under
    # _anchor_versions/. 0 disables versioning entirely (old behavior — every
    # overwrite is lost). Recommended: 5 for personal use, more for code.
    keep_versions: int = 0
    # Destination layout:
    #   False (default) — files go into <dest>/<source-label>/<rel-path>, so
    #                    multiple sources don't collide.
    #   True            — files go directly into <dest>/<rel-path>. Only valid
    #                    with a single source; engine refuses multi-source
    #                    profiles in flat mode. Flipping this on an existing
    #                    profile means the next run re-copies everything to
    #                    the new layout (the state DB is keyed by sub-label).
    flat_destination_layout: bool = False
    # Post-copy verification: after copy, re-walk the source and confirm every
    # file is present at the destination with matching size. Catches "engine
    # said it copied but the bytes didn't actually land" scenarios (which
    # shouldn't happen, but verifying it gives the user peace of mind).
    verify_after_copy: bool = True
    follow_symlinks: bool = False
    preserve_metadata: bool = True     # copy2 (timestamps + perms) vs copy

    # Scheduling (managed via scheduler.py; stored here for GUI display)
    schedule_enabled: bool = False
    schedule_cron: str = ""            # human form, e.g. "daily 03:00"
    last_run_iso: str = ""             # ISO timestamp of last successful run
    last_status: str = "never"         # "ok" | "warning" | "error" | "never"
    last_files_copied: int = 0
    last_bytes_copied: int = 0

    # --- serialization -----------------------------------------------------

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["destinations"] = [asdict(x) for x in self.destinations]
        return d

    @classmethod
    def from_dict(cls, d: Dict) -> "BackupProfile":
        d = dict(d)
        d["destinations"] = [DestinationConfig(**x) for x in d.get("destinations", [])]
        # filter unknown keys gracefully
        allowed = set(cls.__dataclass_fields__.keys())
        return cls(**{k: v for k, v in d.items() if k in allowed})


# --- Persistence -------------------------------------------------------------

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _file_for(profile: BackupProfile) -> Path:
    ensure_dirs()
    safe = _SAFE_NAME_RE.sub("_", profile.name).strip("_") or "profile"
    return PROFILES_DIR / f"{safe}__{profile.id}.json"


def save_profile(profile: BackupProfile) -> Path:
    ensure_dirs()
    # Remove old files for this profile id (in case name changed)
    for p in PROFILES_DIR.glob(f"*__{profile.id}.json"):
        try:
            p.unlink()
        except OSError:
            pass
    path = _file_for(profile)
    path.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")
    return path


def load_profile(path: Path) -> Optional[BackupProfile]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return BackupProfile.from_dict(data)
    except Exception:
        return None


def list_profiles() -> List[BackupProfile]:
    ensure_dirs()
    out: List[BackupProfile] = []
    for p in sorted(PROFILES_DIR.glob("*.json")):
        prof = load_profile(p)
        if prof:
            out.append(prof)
    return out


def find_profile_by_id(profile_id: str) -> Optional[BackupProfile]:
    for prof in list_profiles():
        if prof.id == profile_id:
            return prof
    return None


def find_profile_by_name(name: str) -> Optional[BackupProfile]:
    for prof in list_profiles():
        if prof.name == name:
            return prof
    return None


def delete_profile(profile: BackupProfile) -> None:
    for p in PROFILES_DIR.glob(f"*__{profile.id}.json"):
        try:
            p.unlink()
        except OSError:
            pass
