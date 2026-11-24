"""RunController — the single owner of every background backup/verify thread.

Pages, the tray icon and the window all talk to this object instead of to the
QThreads directly. Centralising it fixes a class of bugs the old window had:

* only one run can be active at a time (the old code checked a different
  worker attribute in each entry point, so a verify could start during a
  group run, and the 5-second drive poll re-enabled the Run button mid-run);
* a QThread is never garbage-collected while still running (the old code
  dropped its reference inside the "finished" slot, which fires *before* the
  thread has actually returned — a classic "QThread: Destroyed while thread
  is still running" crash);
* "busy" stays true until the thread has really exited, not just emitted.
"""
from __future__ import annotations

from typing import List, Optional, Union

from PySide6 import QtCore

from ..core.profile import BackupProfile
from .worker import BackupGroupWorker, BackupWorker, VerifyWorker


_Worker = Union[BackupWorker, BackupGroupWorker, VerifyWorker]


class RunController(QtCore.QObject):
    started = QtCore.Signal(str, list)                 # kind, [profile ids]
    progress = QtCore.Signal(object)                   # BackupProgress
    backup_finished = QtCore.Signal(object, bool)      # BackupResult, cancelled
    group_profile_started = QtCore.Signal(str)         # profile id
    group_profile_done = QtCore.Signal(object)         # BackupResult
    group_finished = QtCore.Signal(list, bool)         # [BackupResult], cancelled
    verify_finished = QtCore.Signal(object, bool)      # VerifyResult, cancelled
    failed = QtCore.Signal(str, str)                   # kind, message
    busy_changed = QtCore.Signal(bool)
    cancelling = QtCore.Signal()                       # cancel was requested

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: Optional[_Worker] = None
        self.kind = ""                 # "backup" | "verify" | "group" | ""
        self.profile_ids: List[str] = []
        self.current_profile_id = ""   # the profile being processed right now

    # --- state -----------------------------------------------------------

    def is_busy(self) -> bool:
        return self._worker is not None

    def is_running_profile(self, profile_id: str) -> bool:
        return self.is_busy() and profile_id in self.profile_ids

    def is_cancelling(self) -> bool:
        w = self._worker
        return bool(w is not None and w.is_cancelling())

    # --- start -----------------------------------------------------------

    def run_backup(self, profile: BackupProfile) -> bool:
        if self.is_busy():
            return False
        w = BackupWorker(profile, parent=self)
        w.progress.connect(self.progress)
        w.finished_ok.connect(self._on_backup_ok)
        w.finished_err.connect(self._on_err)
        self._start(w, "backup", [profile.id])
        return True

    def run_group(self, profiles: List[BackupProfile]) -> bool:
        if self.is_busy() or not profiles:
            return False
        w = BackupGroupWorker(profiles, parent=self)
        w.progress.connect(self.progress)
        w.profile_started.connect(self._on_group_profile_started)
        w.one_profile_done.connect(self.group_profile_done)
        w.finished_ok.connect(self._on_group_ok)
        w.finished_err.connect(self._on_err)
        self._start(w, "group", [p.id for p in profiles])
        return True

    def run_verify(self, profile: BackupProfile) -> bool:
        if self.is_busy():
            return False
        w = VerifyWorker(profile, parent=self)
        w.progress.connect(self.progress)
        w.finished_ok.connect(self._on_verify_ok)
        w.finished_err.connect(self._on_err)
        self._start(w, "verify", [profile.id])
        return True

    def _start(self, w: _Worker, kind: str, ids: List[str]) -> None:
        self._worker = w
        self.kind = kind
        self.profile_ids = list(ids)
        self.current_profile_id = ids[0] if ids else ""
        w.finished.connect(self._on_thread_finished)
        self.busy_changed.emit(True)
        self.started.emit(kind, list(ids))
        w.start()

    # Slots are methods of this QObject (which lives on the GUI thread), so
    # Qt queues them across threads. Lambdas would run on the worker thread.
    @QtCore.Slot(object)
    def _on_backup_ok(self, r) -> None:
        self.backup_finished.emit(r, self.is_cancelling())

    @QtCore.Slot(list)
    def _on_group_ok(self, rs) -> None:
        self.group_finished.emit(rs, self.is_cancelling())

    @QtCore.Slot(object)
    def _on_verify_ok(self, r) -> None:
        self.verify_finished.emit(r, self.is_cancelling())

    @QtCore.Slot(str)
    def _on_err(self, msg: str) -> None:
        self.failed.emit(self.kind or "backup", msg)

    @QtCore.Slot(str)
    def _on_group_profile_started(self, pid: str) -> None:
        self.current_profile_id = pid
        self.group_profile_started.emit(pid)

    @QtCore.Slot()
    def _on_thread_finished(self) -> None:
        w = self.sender()
        if w is None:
            return
        if self._worker is w:
            self._worker = None
            self.kind = ""
            self.profile_ids = []
            self.current_profile_id = ""
            self.busy_changed.emit(False)
        w.deleteLater()

    # --- control ---------------------------------------------------------

    def cancel(self) -> None:
        if self._worker is not None and not self._worker.is_cancelling():
            self._worker.request_cancel()
            self.cancelling.emit()

    def confirm_copy(self) -> None:
        if self._worker is not None:
            self._worker.confirm_start_copy()

    def shutdown(self, timeout_ms: int = 15000) -> bool:
        """Cancel and wait for the worker. Returns False if it is still
        running after the timeout (the caller should then not quit)."""
        w = self._worker
        if w is None:
            return True
        w.request_cancel()
        return w.wait(timeout_ms)
