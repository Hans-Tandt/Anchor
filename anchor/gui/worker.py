"""QThread wrappers around BackupEngine / Verifier so the GUI stays responsive."""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import List, Optional

from PySide6 import QtCore

from ..core.engine import BackupEngine, BackupProgress, BackupResult, Verifier, VerifyResult
from ..core.profile import BackupProfile, save_profile


class BackupWorker(QtCore.QThread):
    progress = QtCore.Signal(object)  # BackupProgress
    finished_ok = QtCore.Signal(object)  # BackupResult
    finished_err = QtCore.Signal(str)
    log_line = QtCore.Signal(str, str)  # (level, message) — wired by log handler

    def __init__(self, profile: BackupProfile, parent=None):
        super().__init__(parent)
        self.profile = profile
        self._cancel = threading.Event()

    def request_cancel(self) -> None:
        self._cancel.set()

    def is_cancelling(self) -> bool:
        return self._cancel.is_set()

    def run(self) -> None:  # noqa: D401
        try:
            engine = BackupEngine(
                self.profile,
                on_event=self._on_progress,
                cancel_event=self._cancel,
            )
            result: BackupResult = engine.run()
            # Persist run summary on profile
            self.profile.last_run_iso = datetime.now().isoformat(timespec="seconds")
            self.profile.last_status = result.status
            self.profile.last_files_copied = result.files_copied
            self.profile.last_bytes_copied = result.bytes_copied
            try:
                save_profile(self.profile)
            except Exception:
                pass
            self.finished_ok.emit(result)
        except Exception as e:
            self.finished_err.emit(str(e))

    def _on_progress(self, p: BackupProgress) -> None:
        # Cross-thread emit — Qt queues the signal automatically.
        self.progress.emit(p)


class BackupGroupWorker(QtCore.QThread):
    """Run a list of profiles sequentially, one after another.

    Emits the same `progress` events as a single BackupWorker, but augments
    each with `dest_label = "[i/N] <profile-name>" ...` so the GUI shows
    "currently running profile 2 of 5". On finish, emits a single aggregated
    GroupResult.
    """

    progress = QtCore.Signal(object)              # BackupProgress
    finished_ok = QtCore.Signal(list)             # List[BackupResult]
    finished_err = QtCore.Signal(str)
    # Fired once per profile completion so the GUI can refresh the sidebar
    # entry (status dot, last_run, etc.) without waiting for the whole group.
    one_profile_done = QtCore.Signal(object)      # BackupResult

    def __init__(self, profiles: List[BackupProfile], parent=None):
        super().__init__(parent)
        self.profiles = list(profiles)
        self._cancel = threading.Event()
        self._log = logging.getLogger("anchor.group")

    def request_cancel(self) -> None:
        self._cancel.set()

    def is_cancelling(self) -> bool:
        return self._cancel.is_set()

    def run(self) -> None:  # noqa: D401
        results: List[BackupResult] = []
        total = len(self.profiles)
        for i, profile in enumerate(self.profiles, start=1):
            if self._cancel.is_set():
                break
            # A clear header in the GUI log so the user can tell where one
            # profile's output ends and the next begins.
            self._log.info(
                "── Group run %d/%d: profile '%s' ──", i, total, profile.name,
            )
            try:
                engine = BackupEngine(
                    profile,
                    on_event=self._make_progress_emitter(i, total, profile.name),
                    cancel_event=self._cancel,
                )
                result = engine.run()
                # Persist last-run summary on the profile
                profile.last_run_iso = datetime.now().isoformat(timespec="seconds")
                profile.last_status = result.status
                profile.last_files_copied = result.files_copied
                profile.last_bytes_copied = result.bytes_copied
                try:
                    save_profile(profile)
                except Exception:
                    pass
                results.append(result)
                self.one_profile_done.emit(result)
            except Exception as e:
                self._log.exception("Group run aborted on '%s'", profile.name)
                self.finished_err.emit(f"{profile.name}: {e}")
                return
        self.finished_ok.emit(results)

    def _make_progress_emitter(self, i: int, total: int, name: str):
        """Wrap each profile's progress so dest_label includes 'i/N name'."""
        def _emit(p: BackupProgress) -> None:
            # Mutate the label in-place — the engine owns its own copy and
            # never reuses BackupProgress across destinations, so this is safe.
            p.dest_label = f"[{i}/{total}] {name}  •  {p.dest_label}"
            self.progress.emit(p)
        return _emit


class VerifyWorker(QtCore.QThread):
    """Runs Verifier.run() off the UI thread.

    Emits the same BackupProgress shape as BackupWorker so the main window's
    progress widgets can be reused without modification.
    """

    progress = QtCore.Signal(object)            # BackupProgress
    finished_ok = QtCore.Signal(object)         # VerifyResult
    finished_err = QtCore.Signal(str)

    def __init__(self, profile: BackupProfile, parent=None):
        super().__init__(parent)
        self.profile = profile
        self._cancel = threading.Event()

    def request_cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:  # noqa: D401
        try:
            v = Verifier(
                self.profile,
                on_event=lambda p: self.progress.emit(p),
                cancel_event=self._cancel,
            )
            result: VerifyResult = v.run()
            self.finished_ok.emit(result)
        except Exception as e:
            self.finished_err.emit(str(e))
