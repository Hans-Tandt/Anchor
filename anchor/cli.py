"""Hidden CLI used by Windows Task Scheduler to run a backup silently.

Not for interactive use — the user-facing entry point is `python -m anchor`.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

from .core.profile import find_profile_by_id, find_profile_by_name, save_profile
from .core.engine import BackupEngine
from .logging_setup import setup_logging, get_logger


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="anchor.cli")
    parser.add_argument("--profile", required=True, help="Profile id or name")
    parser.add_argument("--silent", action="store_true")
    parser.add_argument("--cwd", help="Change to this directory before running")
    args = parser.parse_args(argv)

    if args.cwd:
        try:
            os.chdir(args.cwd)
        except OSError:
            pass

    setup_logging()
    log = get_logger("anchor.cli")

    profile = find_profile_by_id(args.profile) or find_profile_by_name(args.profile)
    if not profile:
        log.error("Profile not found: %s", args.profile)
        return 2

    engine = BackupEngine(profile)
    result = engine.run()

    # Persist last_* fields on the profile
    profile.last_run_iso = datetime.now().isoformat(timespec="seconds")
    profile.last_status = result.status
    profile.last_files_copied = result.files_copied
    profile.last_bytes_copied = result.bytes_copied
    save_profile(profile)

    if not args.silent:
        print(
            f"Done. copied={result.files_copied} skipped={result.files_skipped} "
            f"failed={result.files_failed} bytes={result.bytes_copied}"
        )
    return 0 if result.status != "error" else 1


if __name__ == "__main__":
    sys.exit(main())
