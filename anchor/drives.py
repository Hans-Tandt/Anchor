"""Detect Windows drives (local, removable, network)."""
from __future__ import annotations

import os
import string
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class DriveInfo:
    letter: str          # e.g. "D:\\"
    label: str           # volume label
    drive_type: str      # "fixed" | "removable" | "network" | "cdrom" | "ramdisk" | "unknown"
    total_bytes: int
    free_bytes: int


_DRIVE_TYPE_MAP = {
    0: "unknown", 1: "unknown", 2: "removable",
    3: "fixed", 4: "network", 5: "cdrom", 6: "ramdisk",
}


def _try_win32():
    try:
        import ctypes  # noqa: F401
        return True
    except Exception:
        return False


def list_drives() -> List[DriveInfo]:
    """Return all currently-mounted Windows drive letters with type info.

    Falls back to a basic enumeration on non-Windows hosts.
    """
    drives: List[DriveInfo] = []
    if os.name != "nt":
        # On non-Windows, expose / as a fake "fixed" entry so callers don't crash.
        try:
            st = os.statvfs("/")
            total = st.f_blocks * st.f_frsize
            free = st.f_bavail * st.f_frsize
        except Exception:
            total = free = 0
        return [DriveInfo("/", "/", "fixed", total, free)]

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    bitmask = kernel32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if not (bitmask & (1 << i)):
            continue
        root = f"{letter}:\\"
        try:
            dtype_int = kernel32.GetDriveTypeW(root)
            dtype = _DRIVE_TYPE_MAP.get(dtype_int, "unknown")
        except Exception:
            dtype = "unknown"

        label = ""
        try:
            vol_name_buf = ctypes.create_unicode_buffer(1024)
            fs_name_buf = ctypes.create_unicode_buffer(1024)
            serial = wintypes.DWORD()
            max_len = wintypes.DWORD()
            fs_flags = wintypes.DWORD()
            kernel32.GetVolumeInformationW(
                root, vol_name_buf, 1024,
                ctypes.byref(serial), ctypes.byref(max_len),
                ctypes.byref(fs_flags), fs_name_buf, 1024,
            )
            label = vol_name_buf.value
        except Exception:
            pass

        total = free = 0
        try:
            free_caller = ctypes.c_ulonglong(0)
            total_bytes = ctypes.c_ulonglong(0)
            total_free = ctypes.c_ulonglong(0)
            if kernel32.GetDiskFreeSpaceExW(
                root, ctypes.byref(free_caller),
                ctypes.byref(total_bytes), ctypes.byref(total_free),
            ):
                total = total_bytes.value
                free = free_caller.value
        except Exception:
            pass

        drives.append(DriveInfo(
            letter=root,
            label=label or f"({dtype.title()})",
            drive_type=dtype,
            total_bytes=total,
            free_bytes=free,
        ))
    return drives


def find_drive_by_label(label: str) -> Optional[DriveInfo]:
    label = label.strip().lower()
    for d in list_drives():
        if d.label.strip().lower() == label:
            return d
    return None


def is_path_available(path: str) -> bool:
    """Quick check: does this path currently exist (drive plugged in / share reachable)?"""
    if not path:
        return False
    try:
        return os.path.exists(path)
    except Exception:
        return False
