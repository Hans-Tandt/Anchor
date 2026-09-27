"""Backup engine.

Orchestrates: walk sources -> diff against state DB -> copy changed files
to every configured destination -> update state DB -> emit progress.

Designed to run in a worker thread; observers pass an `on_event` callback.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from ..app_config import AppSettings

from .locking import AlreadyLockedError, RunLock
from .profile import BackupProfile
from .state import StateDB
from .walker import ExclusionRules, WalkItem, existing_source_labels, walk_sources
from ..destinations import open_destination, DestinationError
from ..destinations.base import Destination


log = logging.getLogger("anchor.engine")


# --- Public types ------------------------------------------------------------

@dataclass
class BackupProgress:
    """Snapshot of where a backup run is.

    The meaning of the {files,bytes}_{total,done} pair changes with `phase`
    so a single progress widget can render every step:
      - "scanning": files_total = source files known so far (may still grow
                    if walking is still in progress); files_done = files
                    classified against the state DB.
      - "copying":  files_total = files that need copying; files_done = files
                    copied/failed so far this phase. bytes_total/bytes_done
                    track copied bytes (not scanned bytes).
    Cumulative counters (files_copied, files_skipped, files_failed,
    bytes_copied) are preserved across phase transitions.
    """

    profile_id: str
    dest_label: str
    # Per-phase counters — RESET on each phase transition.
    files_total: int = 0
    files_done: int = 0
    bytes_total: int = 0
    bytes_done: int = 0
    # Cumulative outcome counters — preserved across phase transitions.
    files_copied: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    bytes_copied: int = 0
    # Post-classify breakdown the GUI uses for the "found N changes" line.
    files_to_copy: int = 0
    bytes_to_copy: int = 0
    current_file: str = ""
    speed_bps: float = 0.0
    eta_seconds: float = 0.0
    phase: str = "scanning"  # scanning | copying | done | error


@dataclass
class BackupResult:
    profile_id: str
    started_at: datetime
    ended_at: datetime
    files_scanned: int = 0
    files_copied: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    bytes_copied: int = 0
    errors: List[str] = field(default_factory=list)
    per_destination: Dict[str, "BackupResult"] = field(default_factory=dict)
    # Post-copy verify (when enabled): each source file is re-checked at the
    # destination after the copy phase. verify_issues lists every file that
    # didn't pass (missing or wrong size); verify_checked is how many were
    # examined. status() is downgraded to "error" if there are any issues.
    verify_checked: int = 0
    verify_issues: List[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.files_failed or self.verify_issues:
            return "error" if (self.files_failed + len(self.verify_issues)) > max(1, self.files_copied // 20) else "warning"
        return "ok"

    @property
    def duration_s(self) -> float:
        return max(0.0, (self.ended_at - self.started_at).total_seconds())


# --- Engine ------------------------------------------------------------------

EventCb = Callable[[BackupProgress], None]


def _join_rel(sub: str, rel: str) -> str:
    """Join the source sub-label and the in-source rel path for the destination.

    Flat layout uses an empty sub, so we must avoid a leading slash that some
    destinations (notably WebDAV) treat differently than a bare relative path.
    """
    return f"{sub}/{rel}" if sub else rel


class BackupEngine:
    """Run a backup for a single profile.

    `cancel_event` lets the caller signal a graceful stop between files.
    `on_event` is called repeatedly with BackupProgress snapshots; the GUI
    forwards these to the progress bar and label.
    """

    def __init__(
        self,
        profile: BackupProfile,
        on_event: Optional[EventCb] = None,
        cancel_event: Optional[threading.Event] = None,
        verify_with_hash: Optional[bool] = None,
        settings: Optional[AppSettings] = None,
    ):
        self.profile = profile
        self.on_event = on_event or (lambda p: None)
        self.cancel_event = cancel_event or threading.Event()
        # Per-run override of the profile's hash-verify setting.
        self.verify_with_hash = (
            profile.verify_with_hash if verify_with_hash is None else verify_with_hash
        )
        # Load app-level settings on demand so callers in tests / CLI don't
        # have to construct one explicitly. parallel_workers is read from here.
        self._settings = settings or AppSettings.load()
        self._state = StateDB(profile.id)
        self._last_emit = 0.0
        self._speed_window: List[Tuple[float, int]] = []  # (t, cumulative_bytes)

    # --- Public ----------------------------------------------------------

    def run(self) -> BackupResult:
        # Hold a per-profile lock for the whole run so that a manual *Run now*
        # and a scheduled fire can't race against the state DB or destination
        # tree. The lock is released when the `with` block exits, even on
        # crash, and by the OS if the process is killed mid-run.
        try:
            with RunLock(self.profile.id):
                return self._run_locked()
        except AlreadyLockedError as e:
            log.warning(str(e))
            now = datetime.now()
            return BackupResult(
                profile_id=self.profile.id,
                started_at=now,
                ended_at=now,
                errors=[str(e)],
                files_failed=1,
            )

    def _run_locked(self) -> BackupResult:
        started = datetime.now()
        # Shared version timestamp for every file archived in this run, so the
        # versions subtree reads like a coherent snapshot ("everything that was
        # replaced at 2026-05-23 14:31:07").
        self._version_id = started.strftime("%Y%m%dT%H%M%S")
        # Visual delimiter so the log viewer makes it obvious where one run
        # ends and the next begins.
        log.info("─── Backup '%s' (id=%s) ───", self.profile.name, self.profile.id)

        # Guard: flat layout requires exactly one source, otherwise files from
        # different sources can overwrite each other at the destination root.
        if self.profile.flat_destination_layout and len(self.profile.sources) > 1:
            msg = (
                "Profile has flat_destination_layout=True but more than one source. "
                "Either turn flat layout off, or reduce to a single source."
            )
            log.error(msg)
            now = datetime.now()
            return BackupResult(
                profile_id=self.profile.id, started_at=now, ended_at=now,
                errors=[msg], files_failed=1,
            )

        # 1. Scan sources once (the scan is shared across destinations)
        rules = ExclusionRules(
            file_globs=list(self.profile.exclude_globs),
            dir_names=list(self.profile.exclude_dirs),
        )
        # Snapshot which sources are reachable right now. Used below to refuse
        # mirror-deletion for any source label whose root has vanished — e.g.
        # an unmounted USB drive — so we never wipe the backup for it.
        # In flat layout the sub is always "" — so the "reachable" set is {""}
        # iff the single source exists, else {} (which disables mirror-delete).
        if self.profile.flat_destination_layout:
            live_subs = {""} if (
                self.profile.sources
                and os.path.exists(os.path.abspath(self.profile.sources[0]))
            ) else set()
        else:
            live_subs = existing_source_labels(self.profile.sources)
        for raw in self.profile.sources:
            src = os.path.abspath(raw) if not raw.startswith("\\\\") else raw
            if not os.path.exists(src):
                log.warning("Source missing, skipped: %s", raw)
        files: List[Tuple[str, WalkItem]] = []
        scan_bytes = 0
        # Emit "walking" progress as we go so the user sees activity. We don't
        # know the source's total upfront — the bar is indeterminate during
        # this phase; the GUI shows "Scanning source: N files found, M MB".
        walk_progress = BackupProgress(
            profile_id=self.profile.id,
            dest_label="(all destinations)",
            phase="scanning",
        )
        self._emit(walk_progress, force=True)
        for sub, item in walk_sources(
            self.profile.sources, rules,
            follow_symlinks=self.profile.follow_symlinks,
            flat=self.profile.flat_destination_layout,
        ):
            if self.cancel_event.is_set():
                break
            files.append((sub, item))
            scan_bytes += item.size
            walk_progress.files_done = len(files)
            walk_progress.bytes_done = scan_bytes
            walk_progress.current_file = item.abs_path
            self._emit(walk_progress)
        log.info("Scanned %d files (%.1f MB) across %d source(s)",
                 len(files), scan_bytes / (1024 * 1024), len(self.profile.sources))
        self._live_subs = live_subs

        overall = BackupResult(profile_id=self.profile.id, started_at=started, ended_at=started)
        overall.files_scanned = len(files)

        if not self.profile.destinations:
            log.warning("No destinations configured")
            overall.ended_at = datetime.now()
            return overall

        # 2. For each destination, perform incremental copy
        for dcfg in self.profile.destinations:
            if self.cancel_event.is_set():
                break
            dest_label = dcfg.display()
            log.info("Destination: %s", dest_label)
            try:
                dest = open_destination(
                    dcfg, preserve_metadata=self.profile.preserve_metadata
                )
            except DestinationError as e:
                log.error("Cannot open destination '%s': %s", dest_label, e)
                overall.errors.append(f"{dest_label}: {e}")
                continue
            try:
                dest.connect()
            except DestinationError as e:
                log.error("Cannot connect to '%s': %s", dest_label, e)
                overall.errors.append(f"{dest_label}: {e}")
                continue

            try:
                sub_result = self._run_for_destination(
                    dest, dcfg.id, dest_label, files, scan_bytes
                )
                overall.per_destination[dcfg.id] = sub_result
                overall.files_copied += sub_result.files_copied
                overall.files_skipped += sub_result.files_skipped
                overall.files_failed += sub_result.files_failed
                overall.bytes_copied += sub_result.bytes_copied
                overall.errors.extend(sub_result.errors)
                overall.verify_checked += sub_result.verify_checked
                overall.verify_issues.extend(sub_result.verify_issues)
            finally:
                dest.close()

        overall.ended_at = datetime.now()
        log.info(
            "Backup '%s' finished: copied=%d skipped=%d failed=%d verify_checked=%d "
            "verify_issues=%d bytes=%d duration=%.1fs",
            self.profile.name, overall.files_copied, overall.files_skipped,
            overall.files_failed, overall.verify_checked, len(overall.verify_issues),
            overall.bytes_copied, overall.duration_s,
        )
        self._state.close()
        return overall

    # --- Internal --------------------------------------------------------

    def _run_for_destination(
        self,
        dest: Destination,
        dest_id: str,
        dest_label: str,
        files: List[Tuple[str, WalkItem]],
        scan_bytes: int,
    ) -> BackupResult:
        result = BackupResult(
            profile_id=self.profile.id,
            started_at=datetime.now(),
            ended_at=datetime.now(),
        )

        # Build a dict of known state for this destination
        known = self._state.all_for_dest(dest_id)
        # Also build the set of (sub, rel) we observe this run (for mirror_deletions)
        observed: set = set()
        # Per-destination "adopted into state without re-copying" counter so
        # the scan summary can mention it once instead of spamming one log
        # line per adopted file.
        self._adopted_count = 0

        if not known:
            log.info(
                "First run for destination '%s' — the state DB has no entries "
                "for it yet, so every file will be copied to populate it. "
                "Subsequent runs will only copy what's changed.",
                dest_label,
            )

        # Phase 1 — SCANNING (classifying against state DB).
        # The per-phase counters start at 0; files_total is the full scanned
        # set so the bar fills 0 → 100% during classify.
        progress = BackupProgress(
            profile_id=self.profile.id,
            dest_label=dest_label,
            files_total=len(files),
            bytes_total=scan_bytes,
            phase="scanning",
        )
        self._emit(progress, force=True)

        # Thread-safe access to shared progress/result counters when we
        # parallelize for local destinations.
        progress_lock = threading.Lock()

        # 2a. Classify files: skip vs copy. Doing the classify pass serially
        #     is cheap (stat-based) and lets us submit the copy pass cleanly.
        to_copy: List[Tuple[str, "WalkItem", str]] = []  # (sub, item, reason)
        for sub, item in files:
            if self.cancel_event.is_set():
                break
            observed.add((sub, item.rel_path))
            need_copy, reason = self._needs_copy(dest, dest_id, sub, item, known)
            if not need_copy:
                with progress_lock:
                    result.files_skipped += 1
                    progress.files_skipped += 1
                    progress.files_done += 1
                    progress.bytes_done += item.size
                    progress.current_file = _join_rel(sub, item.rel_path)
                self._emit(progress)
                continue
            to_copy.append((sub, item, reason))
            with progress_lock:
                progress.files_done += 1
                progress.bytes_done += item.size
                progress.current_file = _join_rel(sub, item.rel_path)
            self._emit(progress)

        bytes_to_copy = sum(it.size for (_, it, _) in to_copy)
        adopted_part = (
            f", adopted {self._adopted_count} into state" if self._adopted_count else ""
        )
        log.info(
            "Scan of '%s' complete: %d to copy (%.1f MB), %d unchanged%s",
            dest_label, len(to_copy), bytes_to_copy / (1024 * 1024),
            result.files_skipped - self._adopted_count, adopted_part,
        )

        # Hold the scan-complete summary on screen for a moment so the user
        # can read it before the bar resets to 0 for the copy phase. The
        # current `progress` already has the final scan counters; emitting a
        # special "scan-done" phase lets the GUI render the summary line.
        pause = max(0, int(getattr(self._settings, "scan_pause_seconds", 3)))
        if pause > 0:
            with progress_lock:
                progress.phase = "scan-done"
                progress.files_to_copy = len(to_copy)
                progress.bytes_to_copy = bytes_to_copy
                progress.current_file = ""
            self._emit(progress, force=True)
            # Sleep in small slices so Cancel still kills the run promptly.
            slept = 0.0
            while slept < pause and not self.cancel_event.is_set():
                time.sleep(0.1)
                slept += 0.1

        # Phase 2 — COPYING. Reset per-phase counters; cumulative counters
        # (files_copied, files_skipped, files_failed, bytes_copied) keep their
        # values so the GUI's final tally is right.
        with progress_lock:
            progress.phase = "copying"
            progress.files_total = len(to_copy)
            progress.bytes_total = bytes_to_copy
            progress.files_done = 0
            progress.bytes_done = 0
            progress.files_to_copy = len(to_copy)
            progress.bytes_to_copy = bytes_to_copy
            progress.current_file = ""
        self._emit(progress, force=True)

        t0 = time.time()
        self._speed_window = [(t0, 0)]

        # 2b. Copy pass. Parallel for local destinations (multiple disk writers
        #     scale nicely with CPU/disk bandwidth); serial for SFTP/WebDAV
        #     where everything shares one channel and concurrent puts would
        #     either fail or just contend on the wire.
        workers = max(1, int(self._settings.parallel_workers))
        if dest.kind != "local":
            workers = 1

        def _do_one(args: Tuple[str, "WalkItem", str]) -> None:
            sub, item, reason = args
            if self.cancel_event.is_set():
                return
            rel_full = _join_rel(sub, item.rel_path)
            with progress_lock:
                progress.current_file = rel_full
            try:
                if self.profile.keep_versions > 0 and reason != "new":
                    try:
                        dest.archive_existing(rel_full, self._version_id)
                    except DestinationError as e:
                        log.warning(
                            "Could not archive prior version of %s: %s",
                            rel_full, e,
                        )
                dest.put_file(item.abs_path, rel_full, mtime=item.mtime)
                if self.profile.keep_versions > 0:
                    try:
                        dest.prune_versions(rel_full, self.profile.keep_versions)
                    except Exception:
                        log.exception("Prune of old versions failed for %s", rel_full)
                sha = None
                if self.verify_with_hash:
                    sha = _sha256(item.abs_path)
                # StateDB has its own RLock so this is safe under threads.
                self._state.upsert(
                    dest_id, sub, item.rel_path,
                    size=item.size, mtime=item.mtime, sha256=sha,
                )
                with progress_lock:
                    result.files_copied += 1
                    result.bytes_copied += item.size
                    progress.files_copied += 1
                    progress.bytes_copied += item.size
                    progress.files_done += 1
                    progress.bytes_done += item.size
                log.debug("Copied (%s): %s", reason, rel_full)
            except DestinationError as e:
                with progress_lock:
                    result.files_failed += 1
                    progress.files_failed += 1
                    progress.files_done += 1
                    progress.bytes_done += item.size
                    result.errors.append(f"Failed: {rel_full} — {e}")
                log.warning("Failed: %s — %s", rel_full, e)
            except Exception as e:  # pragma: no cover
                with progress_lock:
                    result.files_failed += 1
                    progress.files_failed += 1
                    progress.files_done += 1
                    progress.bytes_done += item.size
                    result.errors.append(f"Unexpected error on {rel_full}: {e}")
                log.exception("Unexpected error on %s", rel_full)
            finally:
                with progress_lock:
                    self._update_speed(progress, item.size)
                self._emit(progress)

        if workers == 1:
            for args in to_copy:
                if self.cancel_event.is_set():
                    break
                _do_one(args)
        else:
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="anchor-cp") as pool:
                futures = [pool.submit(_do_one, args) for args in to_copy]
                for fut in as_completed(futures):
                    if self.cancel_event.is_set():
                        # Best-effort: outstanding tasks will see cancel_event
                        # and bail at their next entry point.
                        pass
                    try:
                        fut.result()
                    except Exception:
                        log.exception("Worker task failed unexpectedly")

        # Mirror deletions — apply two safety filters before deleting anything:
        #  (a) skip entries whose source root isn't currently reachable
        #      (e.g. unmounted USB) — otherwise we'd nuke the whole backup.
        #  (b) enforce mirror_max_delete_pct — if the proposed deletion set is
        #      a larger fraction of known files than the cap allows, abort
        #      mirror-delete for this destination and log loudly. The user
        #      can re-enable by raising the cap if it really was intentional.
        if self.profile.mirror_deletions and known:
            candidates = [
                (sub, rel) for (sub, rel) in known.keys()
                if (sub, rel) not in observed and sub in self._live_subs
            ]
            skipped_for_missing_source = sum(
                1 for (sub, _rel) in known.keys() if sub not in self._live_subs
            )
            if skipped_for_missing_source:
                log.warning(
                    "Mirror-delete: skipping %d entries because their source "
                    "root is currently unreachable", skipped_for_missing_source,
                )

            cap = self.profile.mirror_max_delete_pct
            if cap and candidates and (len(candidates) * 100) > cap * len(known):
                msg = (
                    f"Mirror-delete aborted on '{dest_label}': would remove "
                    f"{len(candidates)} of {len(known)} known files "
                    f"({100 * len(candidates) / len(known):.0f}% > cap {cap}%). "
                    "Raise mirror_max_delete_pct on the profile if intentional."
                )
                log.error(msg)
                result.errors.append(msg)
                candidates = []

            deleted_count = 0
            for sub, rel in candidates:
                rel_full = _join_rel(sub, rel)
                try:
                    # Preserve the to-be-deleted file as a recoverable version
                    # when versioning is on. archive_existing moves the file
                    # out from under rel_full, so the subsequent remove() is
                    # effectively a no-op (file is gone) — that's fine; remove
                    # tolerates missing entries.
                    if self.profile.keep_versions > 0:
                        try:
                            dest.archive_existing(rel_full, self._version_id)
                        except DestinationError as e:
                            log.warning(
                                "Could not archive %s before mirror-delete: %s",
                                rel_full, e,
                            )
                    dest.remove(rel_full)
                    self._state.delete(dest_id, sub, rel)
                    deleted_count += 1
                    # DEBUG — bulk deletes would spam the GUI tail otherwise.
                    log.debug("Mirrored deletion: %s", rel_full)
                except DestinationError as e:
                    result.errors.append(f"Could not delete {rel_full}: {e}")
            if deleted_count:
                log.info("Mirror-delete: removed %d files from '%s'",
                         deleted_count, dest_label)

        # Phase 3 — VERIFYING (post-copy sanity check).
        # Re-walk every source file we just processed and confirm it's actually
        # present at the destination with matching size. This catches the case
        # where the engine *thought* it copied something but the bytes never
        # landed (drive disconnect, fs full, sync tool race, etc). It also
        # protects against a stale state DB telling the engine "skip" while
        # the file is missing from the destination.
        if self.profile.verify_after_copy and files:
            with progress_lock:
                progress.phase = "verifying"
                progress.files_total = len(files)
                progress.bytes_total = 0
                progress.files_done = 0
                progress.bytes_done = 0
                progress.current_file = ""
            self._emit(progress, force=True)

            for sub, item in files:
                if self.cancel_event.is_set():
                    break
                rel_full = _join_rel(sub, item.rel_path)
                ok = False
                err = None
                try:
                    rstat = dest.stat(rel_full)
                    if rstat is None:
                        err = "missing at destination"
                    elif rstat.size != item.size:
                        err = f"size mismatch (dest={rstat.size}, source={item.size})"
                    else:
                        ok = True
                except DestinationError as e:
                    err = f"stat failed: {e}"

                result.verify_checked += 1
                if not ok:
                    issue = f"VERIFY: {rel_full} — {err}"
                    result.verify_issues.append(issue)
                    log.warning(issue)

                with progress_lock:
                    progress.files_done += 1
                    progress.current_file = rel_full
                self._emit(progress)

            if result.verify_issues:
                log.error(
                    "Post-copy verify FAILED on '%s': %d of %d files have issues",
                    dest_label, len(result.verify_issues), result.verify_checked,
                )
            else:
                log.info(
                    "Post-copy verify OK on '%s': %d files all present with matching sizes",
                    dest_label, result.verify_checked,
                )

        progress.phase = "done"
        self._emit(progress, force=True)
        result.ended_at = datetime.now()
        return result

    def _needs_copy(
        self,
        dest: Destination,
        dest_id: str,
        sub: str,
        item: WalkItem,
        known: Dict[Tuple[str, str], Tuple],
    ) -> Tuple[bool, str]:
        key = (sub, item.rel_path)
        rec = known.get(key)

        if rec is None:
            # Not in state. If destination has it with identical metadata,
            # adopt it without re-uploading (useful when state DB was lost).
            rstat = dest.stat(_join_rel(sub, item.rel_path))
            if rstat and rstat.size == item.size and rstat.mtime and abs(rstat.mtime - item.mtime) < 2:
                # DEBUG-level — adopt decisions can fire hundreds of times on
                # state-DB-lost rebuilds. The per-destination scan-complete
                # summary line at INFO level is what the GUI tail shows.
                log.debug(
                    "Adopted (already at dest with matching size+mtime): %s",
                    _join_rel(sub, item.rel_path),
                )
                self._state.upsert(dest_id, sub, item.rel_path, item.size, item.mtime, None)
                self._adopted_count += 1
                return False, "adopted"
            return True, "new"

        known_size, known_mtime, known_sha = rec
        if known_size != item.size:
            return True, "size-changed"
        # mtime tolerance: filesystems can disagree by up to 2s (FAT)
        if abs((known_mtime or 0) - item.mtime) > 2:
            return True, "mtime-changed"
        if self.verify_with_hash:
            # Recompute hash and compare
            cur = _sha256(item.abs_path)
            if cur != known_sha:
                return True, "hash-changed"
        return False, "up-to-date"

    # --- Progress emission -----------------------------------------------

    def _emit(self, p: BackupProgress, force: bool = False) -> None:
        now = time.time()
        if not force and (now - self._last_emit) < 0.1:
            return
        self._last_emit = now
        try:
            self.on_event(p)
        except Exception:
            log.exception("Progress callback raised")

    def _update_speed(self, p: BackupProgress, just_copied_bytes: int) -> None:
        now = time.time()
        last_t, last_b = self._speed_window[-1]
        cum = last_b + just_copied_bytes
        self._speed_window.append((now, cum))
        # keep last 5s
        while len(self._speed_window) > 2 and (now - self._speed_window[0][0]) > 5.0:
            self._speed_window.pop(0)
        t0, b0 = self._speed_window[0]
        dt = max(0.001, now - t0)
        p.speed_bps = (cum - b0) / dt
        remaining = max(0, p.bytes_total - p.bytes_done)
        p.eta_seconds = remaining / p.speed_bps if p.speed_bps > 1 else 0.0


# --- Verify ------------------------------------------------------------------

@dataclass
class VerifyResult:
    """Outcome of a destination verify pass."""

    profile_id: str
    started_at: datetime
    ended_at: datetime
    files_checked: int = 0
    bytes_checked: int = 0
    mismatches: List[str] = field(default_factory=list)   # size/hash differs
    missing_at_dest: List[str] = field(default_factory=list)  # state says it's there, it isn't
    unexpected_at_dest: List[str] = field(default_factory=list)  # at dest but not in state
    errors: List[str] = field(default_factory=list)
    per_destination: Dict[str, "VerifyResult"] = field(default_factory=dict)

    @property
    def status(self) -> str:
        if self.mismatches or self.missing_at_dest or self.errors:
            return "error"
        if self.unexpected_at_dest:
            return "warning"
        return "ok"

    @property
    def duration_s(self) -> float:
        return max(0.0, (self.ended_at - self.started_at).total_seconds())

    @property
    def all_issues(self) -> List[str]:
        out: List[str] = []
        out.extend(f"MISMATCH: {p}" for p in self.mismatches)
        out.extend(f"MISSING:  {p}" for p in self.missing_at_dest)
        out.extend(f"EXTRA:    {p}" for p in self.unexpected_at_dest)
        out.extend(self.errors)
        return out


class Verifier:
    """Walk each destination, hash every file, compare to state DB.

    Runs under the same per-profile RunLock as a backup — a verify and a
    backup of the same profile would race on the destination tree otherwise.

    Streams BackupProgress events (re-uses the same shape so the GUI can
    show progress with the existing widgets — phase is set to 'verifying').
    """

    def __init__(
        self,
        profile: BackupProfile,
        on_event: Optional[EventCb] = None,
        cancel_event: Optional[threading.Event] = None,
    ):
        self.profile = profile
        self.on_event = on_event or (lambda p: None)
        self.cancel_event = cancel_event or threading.Event()
        self._state = StateDB(profile.id)
        self._last_emit = 0.0
        self._speed_window: List[Tuple[float, int]] = []

    def run(self) -> VerifyResult:
        try:
            with RunLock(self.profile.id):
                return self._run_locked()
        except AlreadyLockedError as e:
            log.warning(str(e))
            now = datetime.now()
            return VerifyResult(
                profile_id=self.profile.id,
                started_at=now, ended_at=now,
                errors=[str(e)],
            )

    def _run_locked(self) -> VerifyResult:
        started = datetime.now()
        overall = VerifyResult(profile_id=self.profile.id, started_at=started, ended_at=started)

        for dcfg in self.profile.destinations:
            if self.cancel_event.is_set():
                break
            dest_label = dcfg.display()
            try:
                dest = open_destination(
                    dcfg, preserve_metadata=self.profile.preserve_metadata,
                )
                dest.connect()
            except DestinationError as e:
                overall.errors.append(f"{dest_label}: {e}")
                continue
            try:
                sub = self._verify_destination(dest, dcfg.id, dest_label)
                overall.per_destination[dcfg.id] = sub
                overall.files_checked += sub.files_checked
                overall.bytes_checked += sub.bytes_checked
                overall.mismatches.extend(sub.mismatches)
                overall.missing_at_dest.extend(sub.missing_at_dest)
                overall.unexpected_at_dest.extend(sub.unexpected_at_dest)
                overall.errors.extend(sub.errors)
            finally:
                dest.close()

        overall.ended_at = datetime.now()
        self._state.close()
        log.info(
            "Verify '%s' finished: checked=%d mismatches=%d missing=%d extras=%d errors=%d in %.1fs",
            self.profile.name, overall.files_checked, len(overall.mismatches),
            len(overall.missing_at_dest), len(overall.unexpected_at_dest),
            len(overall.errors), overall.duration_s,
        )
        return overall

    def _verify_destination(
        self, dest: Destination, dest_id: str, dest_label: str,
    ) -> VerifyResult:
        result = VerifyResult(
            profile_id=self.profile.id,
            started_at=datetime.now(), ended_at=datetime.now(),
        )
        known = self._state.all_for_dest(dest_id)
        log.info("Verifying %s (%d known files)", dest_label, len(known))

        progress = BackupProgress(
            profile_id=self.profile.id,
            dest_label=dest_label,
            files_total=len(known),
            phase="verifying",
        )
        self._emit(progress, force=True)

        seen: set = set()
        for (sub, rel), (size, mtime, sha256) in known.items():
            if self.cancel_event.is_set():
                break
            rel_full = _join_rel(sub, rel)
            progress.current_file = rel_full
            progress.files_done += 1

            try:
                rstat = dest.stat(rel_full)
            except DestinationError as e:
                result.errors.append(f"stat failed: {rel_full} — {e}")
                self._emit(progress)
                continue

            if rstat is None:
                result.missing_at_dest.append(rel_full)
                self._emit(progress)
                continue

            seen.add(rel_full)
            if rstat.size != size:
                result.mismatches.append(
                    f"{rel_full} (size {rstat.size} vs expected {size})"
                )
            elif sha256:
                # Hash check available — download to a temp and re-hash.
                # Bytes-on-disk are the only thing we trust here.
                import tempfile
                with tempfile.NamedTemporaryFile(delete=False) as tf:
                    tmp = tf.name
                try:
                    dest.get_file(rel_full, tmp)
                    cur = _sha256(tmp)
                    if cur != sha256:
                        result.mismatches.append(
                            f"{rel_full} (hash differs)"
                        )
                    result.bytes_checked += rstat.size
                except DestinationError as e:
                    result.errors.append(f"hash-fetch failed: {rel_full} — {e}")
                finally:
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
            else:
                # No stored hash — best we can do is the size check we just did.
                result.bytes_checked += rstat.size
            result.files_checked += 1
            self._emit(progress)

        # Look for unexpected files: anything at the destination that the
        # state DB doesn't know about (excluding the versions subtree, which
        # iter_files already filters).
        try:
            for rel in dest.iter_files():
                if self.cancel_event.is_set():
                    break
                if rel.endswith(".bkp.tmp"):
                    continue  # leftover temp from a crash; not a real file
                if rel not in seen:
                    # Map rel back to (sub, rel) to check the state — `rel` here
                    # is dest-relative (already includes the sub label as its
                    # first path component).
                    result.unexpected_at_dest.append(rel)
        except (NotImplementedError, DestinationError) as e:
            result.errors.append(f"could not enumerate dest: {e}")

        progress.phase = "done"
        self._emit(progress, force=True)
        result.ended_at = datetime.now()
        return result

    def _emit(self, p: BackupProgress, force: bool = False) -> None:
        now = time.time()
        if not force and (now - self._last_emit) < 0.1:
            return
        self._last_emit = now
        try:
            self.on_event(p)
        except Exception:
            log.exception("Verify progress callback raised")


# --- Helpers ----------------------------------------------------------------

def _sha256(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(chunk), b""):
            h.update(blk)
    return h.hexdigest()
