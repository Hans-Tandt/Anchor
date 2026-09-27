"""Diagnose Anchor's runtime state.

Two modes:

    python diagnose.py
        Print resolved paths, settings, profiles, destinations, and the
        row count in each per-profile state DB. Use when something feels
        off — wrong logs location, profile that won't load, etc.

    python diagnose.py --check "C:\\path\\to\\some\\source\\file.jpg"
        Tell me, for every profile that covers this file, exactly what the
        engine would decide for it (excluded? new? unchanged? would be
        adopted?). Use this to answer "why didn't my file get copied?".
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import sqlite3
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _print_dir(label: str, p: Path) -> None:
    exists = p.exists()
    print(f"  {label:14s} = {p}")
    print(f"  {'':14s}   exists={exists}", end="")
    if exists:
        try:
            entries = list(p.iterdir())
            print(f"  ({len(entries)} entries)")
            for e in entries[:20]:
                size = ""
                if e.is_file():
                    try:
                        size = f"  ({e.stat().st_size} bytes)"
                    except OSError:
                        pass
                print(f"  {'':14s}   - {e.name}{size}")
            if len(entries) > 20:
                print(f"  {'':14s}   ... +{len(entries)-20} more")
        except OSError as e:
            print(f"  (listdir failed: {e})")
    else:
        print()


def _check_one_file(file_path: str) -> int:
    """For each profile, explain what would happen to `file_path`."""
    print("=" * 72)
    print(f"ANCHOR DIAGNOSTIC — check single file")
    print("=" * 72)
    abs_p = os.path.abspath(file_path)
    print(f"File:        {abs_p}")
    print(f"Exists:      {os.path.exists(abs_p)}")
    if not os.path.exists(abs_p):
        print("  (cannot check anything else; the file must exist on disk.)")
        return 1
    try:
        st = os.stat(abs_p)
        print(f"Size:        {st.st_size} bytes")
        print(f"Mtime:       {st.st_mtime} ({_fmt_ts(st.st_mtime)})")
    except OSError as e:
        print(f"!!! stat failed: {e}")
        return 1
    print()

    from anchor.app_config import STATE_DIR
    from anchor.core.profile import list_profiles
    from anchor.core.walker import source_label
    from anchor.destinations import open_destination, DestinationError

    profiles = list_profiles()
    if not profiles:
        print("(no profiles configured)")
        return 0

    matched_any = False
    for prof in profiles:
        # Does this profile cover the file? Walk the configured sources and
        # find one that is the file itself or a parent directory.
        covering = None
        rel = None
        for s in prof.sources:
            s_abs = os.path.abspath(s) if not s.startswith("\\\\") else s
            try:
                rel_candidate = os.path.relpath(abs_p, s_abs)
            except ValueError:
                continue
            if rel_candidate.startswith(".."):
                continue
            if os.path.normcase(abs_p) == os.path.normcase(s_abs) or not rel_candidate.startswith(".."):
                covering = s_abs
                rel = rel_candidate.replace("\\", "/")
                break
        if covering is None:
            continue

        matched_any = True
        sub = source_label(covering if os.path.isdir(covering) else os.path.dirname(covering))
        if os.path.isfile(covering):
            rel = os.path.basename(covering)
        print(f"--- Profile '{prof.name}' covers this file ---")
        print(f"  Source root:    {covering}")
        print(f"  Sub-label:      {sub}")
        print(f"  Rel path:       {rel}")

        # Exclusion check
        excluded = _is_excluded(rel, prof.exclude_globs, prof.exclude_dirs)
        if excluded:
            print(f"  ⚠ EXCLUDED by pattern: {excluded}")
            print("  -> Engine would NOT see this file at all. Edit exclusions to include it.")
            continue
        print(f"  Excluded:       no")

        # Per-destination decision
        state_path = STATE_DIR / f"{prof.id}.sqlite"
        if not state_path.exists():
            print(f"  State DB:       MISSING — every file would be 'new' (copied).")
            continue
        try:
            con = sqlite3.connect(state_path)
        except Exception as e:
            print(f"  !!! could not open state DB: {e}")
            continue

        for d in prof.destinations:
            print(f"  Destination '{d.display()}' (id={d.id}, kind={d.kind}):")
            row = con.execute(
                "SELECT size, mtime, sha256, backed_up_at FROM files "
                "WHERE dest_id=? AND sub=? AND rel_path=?",
                (d.id, sub, rel),
            ).fetchone()
            if row is None:
                print(f"    state DB:      no row for this (sub,rel)")
                # Probe the destination to predict adopt vs new
                try:
                    dest = open_destination(d, preserve_metadata=prof.preserve_metadata)
                    dest.connect()
                    try:
                        rstat = dest.stat(f"{sub}/{rel}")
                        if rstat is None:
                            print("    at destination: no")
                            print("    DECISION:      NEW — engine would copy it.")
                        else:
                            same_size = rstat.size == st.st_size
                            same_mtime = rstat.mtime and abs(rstat.mtime - st.st_mtime) < 2
                            print(f"    at destination: yes (size={rstat.size}, mtime={_fmt_ts(rstat.mtime)})")
                            print(f"    size matches:  {same_size}")
                            print(f"    mtime within 2s of source: {bool(same_mtime)}")
                            if same_size and same_mtime:
                                print("    DECISION:      ADOPTED — engine would mark as already-backed-up")
                                print("                   WITHOUT actually copying. If that surprises you,")
                                print("                   delete the file at the destination and rerun.")
                            else:
                                print("    DECISION:      NEW — engine would copy it.")
                    finally:
                        dest.close()
                except DestinationError as e:
                    print(f"    (could not probe destination: {e})")
            else:
                known_size, known_mtime, known_sha, backed_up_at = row
                print(f"    state DB row:  size={known_size}, mtime={_fmt_ts(known_mtime)}, sha={known_sha or '-'}")
                print(f"    backed up at:  {backed_up_at}")
                if known_size != st.st_size:
                    print(f"    DECISION:      SIZE-CHANGED — would copy.")
                elif abs((known_mtime or 0) - st.st_mtime) > 2:
                    print(f"    DECISION:      MTIME-CHANGED — would copy.")
                elif prof.verify_with_hash and not known_sha:
                    print(f"    DECISION:      HASH-MODE FLIP — would copy (state has no hash yet).")
                else:
                    print(f"    DECISION:      UP-TO-DATE — would SKIP.")
        con.close()
        print()

    if not matched_any:
        print("No profile covers this file path. Check the source list of your profile(s).")
    return 0


def _is_excluded(rel: str, file_globs, dir_globs):
    """Return the matching pattern if the rel path is excluded, else None."""
    name = rel.split("/")[-1]
    for g in file_globs:
        if fnmatch.fnmatch(name, g) or fnmatch.fnmatch(rel, g):
            return g
    for d in dir_globs:
        if d in rel.split("/"):
            return d
    return None


def _fmt_ts(t) -> str:
    if not t:
        return "(none)"
    from datetime import datetime
    try:
        return datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError):
        return str(t)


def main() -> int:
    parser = argparse.ArgumentParser(description="Anchor diagnostic")
    parser.add_argument("--check", metavar="PATH",
                        help="Explain what the engine would do for this source file.")
    args = parser.parse_args()
    if args.check:
        return _check_one_file(args.check)
    return _full_report()


def _full_report() -> int:
    print("=" * 72)
    print("ANCHOR DIAGNOSTIC")
    print("=" * 72)
    print(f"Python:        {sys.executable}")
    print(f"Python ver:    {sys.version.split()[0]}")
    print(f"CWD:           {os.getcwd()}")
    print(f"APPDATA env:   {os.environ.get('APPDATA', '(not set)')}")
    print()

    # --- Resolve Anchor paths ---
    try:
        from anchor.app_config import APP_DIR, PROFILES_DIR, STATE_DIR, LOGS_DIR, SETTINGS_FILE
    except Exception as e:
        print(f"!!! import failed: {e}")
        traceback.print_exc()
        return 1

    print("--- Paths Anchor would use ---")
    _print_dir("APP_DIR", APP_DIR)
    _print_dir("PROFILES_DIR", PROFILES_DIR)
    _print_dir("STATE_DIR", STATE_DIR)
    _print_dir("LOGS_DIR", LOGS_DIR)
    print(f"  SETTINGS_FILE  = {SETTINGS_FILE}  (exists={SETTINGS_FILE.exists()})")
    print()

    # --- Try ensure_dirs + setup_logging ---
    print("--- Calling ensure_dirs() ---")
    try:
        from anchor.app_config import ensure_dirs
        ensure_dirs()
        print("  ensure_dirs(): ok")
        print(f"  LOGS_DIR now exists: {LOGS_DIR.exists()}")
    except Exception as e:
        print(f"  !!! ensure_dirs failed: {e}")
        traceback.print_exc()

    print()
    print("--- Calling setup_logging() ---")
    try:
        from anchor.logging_setup import setup_logging
        setup_logging()
        print("  setup_logging(): ok")
        print(f"  LOGS_DIR contents: {[p.name for p in LOGS_DIR.iterdir()]}")
    except Exception as e:
        print(f"  !!! setup_logging failed: {e}")
        traceback.print_exc()
    print()

    # --- Profiles + state ---
    print("--- Profiles & state DBs ---")
    try:
        from anchor.core.profile import list_profiles
        profiles = list_profiles()
    except Exception as e:
        print(f"  !!! list_profiles failed: {e}")
        traceback.print_exc()
        return 1

    if not profiles:
        print("  (no profiles found)")
        return 0

    for p in profiles:
        print(f"\n  Profile: '{p.name}'")
        print(f"    id:                {p.id}")
        print(f"    verify_with_hash:  {p.verify_with_hash}")
        print(f"    keep_versions:     {p.keep_versions}")
        print(f"    mirror_deletions:  {p.mirror_deletions}")
        print(f"    preserve_metadata: {p.preserve_metadata}")
        print(f"    sources ({len(p.sources)}):")
        for s in p.sources:
            print(f"      - {s}  (exists={os.path.exists(s)})")
        print(f"    destinations ({len(p.destinations)}):")
        for d in p.destinations:
            print(f"      - id={d.id} kind={d.kind} {d.display()}")

        state_path = STATE_DIR / f"{p.id}.sqlite"
        if not state_path.exists():
            print(f"    state DB:          MISSING ({state_path})")
            print("                       -> every file will be treated as new on next run!")
            continue
        print(f"    state DB:          {state_path}  ({state_path.stat().st_size} bytes)")
        try:
            con = sqlite3.connect(state_path)
            total = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            print(f"    state rows total:  {total}")
            for d in p.destinations:
                n = con.execute(
                    "SELECT COUNT(*) FROM files WHERE dest_id=?", (d.id,)
                ).fetchone()[0]
                print(f"      dest id={d.id}: {n} rows")
            con.close()
            if total == 0:
                print("    -> state DB is empty; every file will be re-copied next run.")
        except Exception as e:
            print(f"    !!! could not read state DB: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
