"""Windows Task Scheduler integration via `schtasks.exe`.

We register one scheduled task per backup profile. The task runs:
    pythonw.exe -m anchor.cli --profile <profile-id> --silent

Tasks created here are named  "Anchor_<profile-id>".
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Optional

TASK_PREFIX = "Anchor_"


@dataclass
class ScheduleSpec:
    frequency: str   # "DAILY" | "WEEKLY" | "ONCE" | "ONLOGON"
    start_time: str  # "HH:MM" (24h) — ignored for ONLOGON
    days: str = ""   # for WEEKLY: comma list e.g. "MON,WED"

    def human(self) -> str:
        if self.frequency == "ONLOGON":
            return "Every time I sign in"
        if self.frequency == "DAILY":
            return f"Every day at {self.start_time}"
        if self.frequency == "WEEKLY":
            return f"Every {self.days or 'MON'} at {self.start_time}"
        return f"{self.frequency} {self.start_time}".strip()


def _task_name(profile_id: str) -> str:
    return f"{TASK_PREFIX}{profile_id}"


def _invocation_prefix() -> str:
    """Return the shell-quoted command that runs Anchor's CLI on this system.

    * Frozen (PyInstaller build): the exe IS the CLI entry point when invoked
      with `--cli` (see `anchor/__main__.py`), so we just wrap `sys.executable`.
    * Source install: use `pythonw.exe -m anchor.cli --cwd <project-root>`
      so scheduled runs don't flash a console window.
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --cli'
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        pw = exe[:-len("python.exe")] + "pythonw.exe"
        if os.path.exists(pw):
            exe = pw
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    return f'"{exe}" -m anchor.cli --cwd "{root}"'


def task_command(profile_id: str) -> str:
    """Return the exact command a scheduled task should run for `profile_id`."""
    return f"{_invocation_prefix()} --profile {profile_id} --silent"


def create_or_update(profile_id: str, spec: ScheduleSpec) -> Optional[str]:
    """Create/replace a scheduled task. Returns error message or None on success."""
    if os.name != "nt":
        return "Scheduling is only available on Windows."

    name = _task_name(profile_id)
    tr = task_command(profile_id)

    cmd = [
        "schtasks", "/Create", "/F",
        "/TN", name,
        "/TR", tr,
        "/SC", spec.frequency,
    ]
    if spec.frequency in ("DAILY", "WEEKLY"):
        cmd += ["/ST", spec.start_time or "03:00"]
    if spec.frequency == "WEEKLY" and spec.days:
        cmd += ["/D", spec.days]

    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            return (out.stderr or out.stdout or "schtasks failed").strip()
    except Exception as e:
        return f"schtasks error: {e}"
    return None


def delete(profile_id: str) -> Optional[str]:
    if os.name != "nt":
        return None
    name = _task_name(profile_id)
    try:
        out = subprocess.run(
            ["schtasks", "/Delete", "/TN", name, "/F"],
            capture_output=True, text=True, timeout=15,
        )
        if out.returncode != 0 and "cannot find" not in (out.stderr + out.stdout).lower():
            return (out.stderr or out.stdout or "schtasks failed").strip()
    except Exception as e:
        return f"schtasks error: {e}"
    return None


def query(profile_id: str) -> Optional[str]:
    """Return the schtasks output for this profile, or None if missing."""
    if os.name != "nt":
        return None
    name = _task_name(profile_id)
    try:
        out = subprocess.run(
            ["schtasks", "/Query", "/TN", name, "/V", "/FO", "LIST"],
            capture_output=True, text=True, timeout=15,
        )
        if out.returncode == 0:
            return out.stdout
    except Exception:
        pass
    return None


def list_managed() -> List[str]:
    """List profile IDs that currently have a scheduled task."""
    if os.name != "nt":
        return []
    try:
        out = subprocess.run(
            ["schtasks", "/Query", "/FO", "LIST"],
            capture_output=True, text=True, timeout=20,
        )
    except Exception:
        return []
    ids: List[str] = []
    for line in out.stdout.splitlines():
        m = re.match(r"TaskName:\s*\\?" + re.escape(TASK_PREFIX) + r"(\S+)", line)
        if m:
            ids.append(m.group(1))
    return ids
