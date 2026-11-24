"""QThread wrappers around BackupEngine / Verifier so the GUI stays responsive."""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import List

from PySide6 import QtCore

from ..core.engine import BackupEngine, BackupProgress, BackupResult, Verifier, VerifyResult
from ..core.profile import BackupProfile, find_profile_by_id, save_profile

log = logging.getLogger("anchor.gui.worker")


def _persist_run_summary(profile: BackupProfile, result: BackupResult) -> None:
    """Write last-run fields back to the profile file.

    Re-reads the profile from disk first so edits saved elsewhere while the
    run was going (e.g. the CLI or another window) are not overwritten by the
    snapshot the run started with. The in-memory object is updated too so the
    GUI shows the new status without reloading.
    """
    stamp = datetime.now().isoformat(timespec="seconds")
    fresh = find_profile_by_id(profile.id)
    for target in (profile, fresh):
        if target is None:
            continue
        target.last_run_iso = stamp
        target.last_status = result.status
        target.last_files_copied = result.files_copied
        target.last_bytes_copied = result.bytes_copied
    if fresh is None:
        return  # profile was deleted meanwhile — don't resurrect it
    try:
        save_profile(fresh)
    except Exception:
        log.exception("Could not save run summary for profile '%s'", profile.name)


class BackupWorker(QtCore.QThread):
    progress = QtCore.Signal(object)       # BackupProgress
    finished_ok = QtCore.Signal(object)    # BackupResult
    finished_err = QtCore.Signal(str)

    def __init__(self, profile: BackupProfile, parent=None):
        super().__init__(parent)
        self.profile = profile
        self._cancel = threading.Event()
        # Set when the user clicks "Start copy". Only observed by the engine
        # when profile.confirm_before_copy is on.
        self._confirm = threading.Event()

    def request_cancel(self) -> None:
        self._cancel.set()
        self._confirm.set()  # unblock a scan-done wait so cancel is prompt

    def is_cancelling(self) -> bool:
        return self._cancel.is_set()

    def confirm_start_copy(self) -> None:
        self._confirm.set()

    def run(self) -> None:  # noqa: D401
        try:
            engine = BackupEngine(
                self.profile,
                on_event=self.progress.emit,
                cancel_event=self._cancel,
                confirm_event=self._confirm,
            )
            result: BackupResult = engine.run()
            _persist_run_summary(self.profile, result)
            self.finished_ok.emit(result)
        except Exception as e:
            log.exception("Backup of '%s' crashed", self.profile.name)
            self.finished_err.emit(str(e) or e.__class__.__name__)


class BackupGroupWorker(QtCore.QThread):
    """Run several profiles one after another.

    Progress events get "[i/N] <profile>" prefixed to dest_label. A profile
    that crashes is recorded as an error and the group carries on with the
    next one (previously one bad profile aborted the whole group and threw
    away the results of the profiles that had already finished).
    """

    progress = QtCore.Signal(object)          # BackupProgress
    finished_ok = QtCore.Signal(list)         # List[BackupResult]
    finished_err = QtCore.Signal(str)
    one_profile_done = QtCore.Signal(object)  # BackupResult
    profile_started = QtCore.Signal(str)      # profile id

    def __init__(self, profiles: List[BackupProfile], parent=None):
        super().__init__(parent)
        self.profiles = list(profiles)
        self._cancel = threading.Event()
        self._confirm = threading.Event()
        self.current_profile_id = ""

    def request_cancel(self) -> None:
        self._cancel.set()
        self._confirm.set()

    def is_cancelling(self) -> bool:
        return self._cancel.is_set()

    def confirm_start_copy(self) -> None:
        self._confirm.set()

    def run(self) -> None:  # noqa: D401
        results: List[BackupResult] = []
        total = len(self.profiles)
        for i, profile in enumerate(self.profiles, start=1):
            if self._cancel.is_set():
                break
            self._confirm.clear()
            self.current_profile_id = profile.id
            self.profile_started.emit(profile.id)
            log.info("── Group run %d/%d: profile '%s' ──", i, total, profile.name)
            started = datetime.now()
            try:
                engine = BackupEngine(
                    profile,
                    on_event=self._make_progress_emitter(i, total, profile.name),
                    cancel_event=self._cancel,
                    confirm_event=self._confirm,
                )
                result = engine.run()
            except Exception as e:
                log.exception("Group run: profile '%s' crashed", profile.name)
                result = BackupResult(
                    profile_id=profile.id, started_at=started, ended_at=datetime.now(),
                    errors=[f"{profile.name}: {e}"], destinations_failed=1,
                )
            _persist_run_summary(profile, result)
            results.append(result)
            self.one_profile_done.emit(result)
        self.finished_ok.emit(results)

    def _make_progress_emitter(self, i: int, total: int, name: str):
        def _emit(p: BackupProgress) -> None:
            # Each event is a fresh snapshot (BackupEngine._emit), safe to edit.
            p.dest_label = f"[{i}/{total}] {name}  •  {p.dest_label}"
            self.progress.emit(p)
        return _emit


class VerifyWorker(QtCore.QThread):
    progress = QtCore.Signal(object)       # BackupProgress
    finished_ok = QtCore.Signal(object)    # VerifyResult
    finished_err = QtCore.Signal(str)

    def __init__(self, profile: BackupProfile, parent=None):
        super().__init__(parent)
        self.profile = profile
        self._cancel = threading.Event()

    def request_cancel(self) -> None:
        self._cancel.set()

    def is_cancelling(self) -> bool:
        return self._cancel.is_set()

    def confirm_start_copy(self) -> None:
        pass

    def run(self) -> None:  # noqa: D401
        try:
            v = Verifier(self.profile, on_event=self.progress.emit, cancel_event=self._cancel)
            result: VerifyResult = v.run()
            self.finished_ok.emit(result)
        except Exception as e:
            log.exception("Verify of '%s' crashed", self.profile.name)
            self.finished_err.emit(str(e) or e.__class__.__name__)
