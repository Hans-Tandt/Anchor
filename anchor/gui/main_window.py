"""Main application window.

Layout:
  +-------------------------------------------------------------+
  |  [App icon]  Anchor                     [Theme] [Settings]  |
  +-----------------+-------------------------------------------+
  | PROFILES        |  PROFILE: Daily Documents                 |
  |  - Documents (*)|                                            |
  |  - Photos       |  Status card  |  Last run card             |
  |  - QNAP remote  |                                            |
  |  ...            |  Sources / Destinations                    |
  |                 |                                            |
  |  + New profile  |  [Run backup]  [Schedule]  [Edit]  [Del]   |
  |                 |                                            |
  |                 |  Progress: ▓▓▓▓▓░░░ 62%   15 MB/s  ETA 41s |
  +-----------------+-------------------------------------------+
  |  Log:  [ tail of recent log lines ]                          |
  +-------------------------------------------------------------+
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

from .. import __app_name__, __version__
from ..app_config import AppSettings, LOGS_DIR, ensure_dirs
from ..core.profile import (
    BackupProfile, delete_profile, list_profiles, save_profile,
)
from ..logging_setup import get_tail
from ..drives import is_path_available
from .. import scheduler as sched

from .issues_dialog import IssuesDialog
from .profile_editor import ProfileEditor
from .restore_dialog import RestoreDialog
from .schedule_dialog import ScheduleDialog
from .settings_dialog import SettingsDialog
from .theme import apply_theme
from .worker import BackupGroupWorker, BackupWorker, VerifyWorker


def _human_bytes(n: float) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or u == "TB":
            return f"{n:.1f} {u}" if u != "B" else f"{int(n)} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def _human_time(sec: float) -> str:
    sec = max(0, int(sec))
    if sec < 60: return f"{sec}s"
    if sec < 3600: return f"{sec // 60}m {sec % 60}s"
    return f"{sec // 3600}h {(sec % 3600) // 60}m"


def _status_color(status: str) -> str:
    return {"ok": "ok", "warning": "warn", "error": "err", "never": "muted"}.get(status, "muted")


# TechEase brand assets bundled with the package (sidebar footer branding).
_ASSETS_DIR = Path(__file__).resolve().parent.parent / "TechEase"
_LOGO_BANNER = _ASSETS_DIR / "TechEase Where Industry Meets AI-02.png"
_LOGO_MARK = _ASSETS_DIR / "TechEase Where Industry Meets AI-01.png"

# Multi-resolution app icon for the window and taskbar. Kept at the project
# root under assets/ so it can also be embedded by the installer.
_ICON_FILE = Path(__file__).resolve().parent.parent.parent / "assets" / "icon.ico"


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, settings: AppSettings):
        super().__init__()
        self.settings = settings
        self.setWindowTitle(f"{__app_name__} {__version__}")
        self.resize(1100, 720)
        # Prefer the multi-resolution .ico so the taskbar entry stays sharp;
        # fall back to the TechEase mark if the icon file is missing.
        if _ICON_FILE.exists():
            self.setWindowIcon(QtGui.QIcon(str(_ICON_FILE)))
        elif _LOGO_MARK.exists():
            self.setWindowIcon(QtGui.QIcon(str(_LOGO_MARK)))

        self.worker: Optional[BackupWorker] = None
        self.verify_worker: Optional[VerifyWorker] = None
        self.group_worker: Optional[BackupGroupWorker] = None
        self.profiles: list[BackupProfile] = []
        self.current: Optional[BackupProfile] = None
        # Errors from the most recent run, exposed via the "View N issues"
        # button. Lives on the window so the Verify action can populate it too.
        self._last_errors: list[str] = []
        self._last_errors_title: str = "Last run — issues"

        self._build_ui()
        self._refresh_profiles(select_id=settings.last_profile)
        self._wire_log_tail()

        # poll drive availability every 5 seconds (cheap)
        self._poll = QtCore.QTimer(self); self._poll.setInterval(5000)
        self._poll.timeout.connect(self._refresh_destination_freshness)
        self._poll.start()

    # --- UI build --------------------------------------------------------

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget(); central.setObjectName("central")
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12); root.setSpacing(12)

        # Header bar
        header = QtWidgets.QHBoxLayout(); header.setSpacing(10)
        title = QtWidgets.QLabel(f"{__app_name__}"); title.setObjectName("h1")
        header.addWidget(title)
        header.addStretch(1)
        # Open the logs folder in the OS file manager. Lives in the header so
        # the user never has to dig through Settings (or %APPDATA%) to find it.
        logs_btn = QtWidgets.QPushButton("Open logs")
        logs_btn.setToolTip(
            "Open the logs folder in Explorer (lives under %APPDATA%\\Anchor\\logs)."
        )
        logs_btn.clicked.connect(self._open_logs_folder)
        header.addWidget(logs_btn)
        theme_btn = QtWidgets.QPushButton("Toggle theme")
        theme_btn.clicked.connect(self._toggle_theme)
        header.addWidget(theme_btn)
        settings_btn = QtWidgets.QPushButton("Settings")
        settings_btn.clicked.connect(self._open_settings)
        header.addWidget(settings_btn)
        root.addLayout(header)

        # Split: sidebar (profiles) | detail
        body = QtWidgets.QHBoxLayout(); body.setSpacing(12)
        root.addLayout(body, 1)

        # Sidebar
        sidebar = QtWidgets.QFrame(); sidebar.setObjectName("sidebar")
        sidebar.setFrameShape(QtWidgets.QFrame.StyledPanel)
        sidebar.setMinimumWidth(260); sidebar.setMaximumWidth(320)
        sl = QtWidgets.QVBoxLayout(sidebar); sl.setContentsMargins(10, 10, 10, 10); sl.setSpacing(8)
        sl.addWidget(QtWidgets.QLabel("Backup profiles", objectName="h2"))
        sl.addWidget(QtWidgets.QLabel(
            "Click to view  ·  Ctrl/Shift-click for group run",
            objectName="muted",
        ))
        self.profile_list = QtWidgets.QListWidget()
        # Allow Ctrl/Shift multi-selection so the user can run several
        # profiles back-to-back via the "Run selected" button.
        self.profile_list.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection,
        )
        self.profile_list.currentRowChanged.connect(self._on_profile_select)
        self.profile_list.itemSelectionChanged.connect(self._on_selection_changed)
        sl.addWidget(self.profile_list, 1)
        # "Run selected" appears only when the user has multi-selected. A
        # single-selection (the default) still uses "Run backup now" in the
        # detail panel.
        self.run_group_btn = QtWidgets.QPushButton("▶  Run selected (0)")
        self.run_group_btn.setObjectName("primary")
        self.run_group_btn.setVisible(False)
        self.run_group_btn.clicked.connect(self._run_selected_group)
        sl.addWidget(self.run_group_btn)
        new_btn = QtWidgets.QPushButton("＋ New backup profile")
        new_btn.setObjectName("primary"); new_btn.clicked.connect(self._new_profile)
        sl.addWidget(new_btn)

        # Brand footer — framed TechEase logo + "Created by Hans Tandt".
        sl.addSpacing(6)
        sl.addWidget(self._build_brand_footer())
        body.addWidget(sidebar)

        # Detail
        detail = QtWidgets.QVBoxLayout(); detail.setSpacing(12)
        body.addLayout(detail, 1)

        # Profile header card
        self.detail_card = QtWidgets.QFrame(); self.detail_card.setObjectName("card")
        dl = QtWidgets.QVBoxLayout(self.detail_card)
        dl.setContentsMargins(18, 16, 18, 16); dl.setSpacing(10)
        self.profile_title = QtWidgets.QLabel("(no profile selected)")
        self.profile_title.setObjectName("h2")
        dl.addWidget(self.profile_title)

        # Status row
        status_row = QtWidgets.QHBoxLayout(); status_row.setSpacing(20)
        dl.addLayout(status_row)
        self.status_label = QtWidgets.QLabel("Status: —"); self.status_label.setObjectName("muted")
        self.last_run_label = QtWidgets.QLabel("Last run: never"); self.last_run_label.setObjectName("muted")
        self.schedule_label = QtWidgets.QLabel("Schedule: not set"); self.schedule_label.setObjectName("muted")
        status_row.addWidget(self.status_label)
        status_row.addWidget(self.last_run_label)
        status_row.addWidget(self.schedule_label)
        status_row.addStretch(1)

        # Sources / destinations summary
        summaries = QtWidgets.QHBoxLayout(); summaries.setSpacing(12)
        dl.addLayout(summaries, 0)

        # Sources box
        self.sources_box = QtWidgets.QGroupBox("Sources")
        sb = QtWidgets.QVBoxLayout(self.sources_box)
        self.sources_view = QtWidgets.QListWidget()
        self.sources_view.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        sb.addWidget(self.sources_view)
        summaries.addWidget(self.sources_box, 1)

        # Destinations box
        self.dest_box = QtWidgets.QGroupBox("Destinations")
        db = QtWidgets.QVBoxLayout(self.dest_box)
        self.dest_view = QtWidgets.QListWidget()
        self.dest_view.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        db.addWidget(self.dest_view)
        summaries.addWidget(self.dest_box, 1)

        # Action buttons
        actions = QtWidgets.QHBoxLayout(); actions.setSpacing(8)
        self.run_btn = QtWidgets.QPushButton("▶  Run backup now"); self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self._run_backup)
        self.cancel_btn = QtWidgets.QPushButton("■  Cancel")
        self.cancel_btn.clicked.connect(self._cancel_backup); self.cancel_btn.setEnabled(False)
        self.verify_btn = QtWidgets.QPushButton("Verify"); self.verify_btn.clicked.connect(self._verify_backup)
        self.verify_btn.setToolTip(
            "Walk each destination and check every backed-up file against the "
            "state DB (size always, hash if profile was running in hash-verify mode)."
        )
        self.restore_btn = QtWidgets.QPushButton("Restore…"); self.restore_btn.clicked.connect(self._open_restore)
        self.restore_btn.setToolTip(
            "Browse the destination, pick files (and versions), restore to original "
            "location or an alternate folder."
        )
        self.schedule_btn = QtWidgets.QPushButton("Schedule…"); self.schedule_btn.clicked.connect(self._schedule_profile)
        self.edit_btn = QtWidgets.QPushButton("Edit"); self.edit_btn.clicked.connect(self._edit_profile)
        self.delete_btn = QtWidgets.QPushButton("Delete"); self.delete_btn.setObjectName("danger")
        self.delete_btn.clicked.connect(self._delete_profile)
        # "View issues" appears next to the run buttons only when the last run
        # left errors behind. Click → IssuesDialog with full list + CSV export.
        self.issues_btn = QtWidgets.QPushButton("⚠  View 0 issues")
        self.issues_btn.setObjectName("warn")
        self.issues_btn.setVisible(False)
        self.issues_btn.clicked.connect(self._show_issues)
        actions.addWidget(self.run_btn); actions.addWidget(self.cancel_btn)
        actions.addWidget(self.verify_btn)
        actions.addWidget(self.restore_btn)
        actions.addWidget(self.schedule_btn); actions.addWidget(self.edit_btn)
        actions.addWidget(self.issues_btn)
        actions.addStretch(1); actions.addWidget(self.delete_btn)
        dl.addLayout(actions)

        # Progress
        self.progress = QtWidgets.QProgressBar(); self.progress.setRange(0, 100); self.progress.setValue(0)
        dl.addWidget(self.progress)
        # Use a fixed-height label so a long current-file path can't push the
        # whole window taller. Long text is elided in the middle (e.g.
        # "Dest • 12/100 files • …/long/path/file.txt") so both the summary
        # at the start and the file name at the end stay visible.
        self.progress_label = QtWidgets.QLabel("Idle.")
        self.progress_label.setObjectName("muted")
        self.progress_label.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed,
        )
        self.progress_label.setMinimumHeight(self.progress_label.sizeHint().height())
        self.progress_label.setMaximumHeight(self.progress_label.sizeHint().height())
        # Tooltip mirrors the full text so users can hover to read the rest.
        self.progress_label.setToolTip("")
        dl.addWidget(self.progress_label)

        detail.addWidget(self.detail_card)

        # Log viewer
        log_card = QtWidgets.QFrame(); log_card.setObjectName("card")
        ll = QtWidgets.QVBoxLayout(log_card); ll.setContentsMargins(18, 16, 18, 16); ll.setSpacing(6)
        log_header = QtWidgets.QHBoxLayout()
        log_header.addWidget(QtWidgets.QLabel("Log", objectName="h2"))
        log_header.addStretch(1)
        clear_log_btn = QtWidgets.QPushButton("Clear")
        clear_log_btn.clicked.connect(self._clear_log)
        log_header.addWidget(clear_log_btn)
        ll.addLayout(log_header)
        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        f = QtGui.QFont("Consolas"); f.setStyleHint(QtGui.QFont.Monospace); f.setPointSize(9)
        self.log_view.setFont(f)
        ll.addWidget(self.log_view, 1)
        detail.addWidget(log_card, 1)

        # Status bar
        self.statusBar().showMessage("Ready")

    def _build_brand_footer(self) -> QtWidgets.QWidget:
        """Framed footer in the sidebar: TechEase logo banner + credit line."""
        frame = QtWidgets.QFrame(); frame.setObjectName("brandFooter")
        fl = QtWidgets.QVBoxLayout(frame)
        fl.setContentsMargins(10, 10, 10, 10); fl.setSpacing(6)

        logo_label = QtWidgets.QLabel(); logo_label.setAlignment(QtCore.Qt.AlignCenter)
        if _LOGO_BANNER.exists():
            pix = QtGui.QPixmap(str(_LOGO_BANNER))
            if not pix.isNull():
                pix = pix.scaledToWidth(
                    220, QtCore.Qt.SmoothTransformation,
                )
                logo_label.setPixmap(pix)
        else:
            logo_label.setText("TechEase")
        fl.addWidget(logo_label)

        credit = QtWidgets.QLabel("CREATED BY HANS TANDT")
        credit.setObjectName("brandCredit")
        credit.setAlignment(QtCore.Qt.AlignCenter)
        fl.addWidget(credit)

        return frame

    # --- Profile list ----------------------------------------------------

    def _refresh_profiles(self, select_id: str = "") -> None:
        self.profiles = list_profiles()
        self.profile_list.clear()
        target_row = -1
        for i, p in enumerate(self.profiles):
            it = QtWidgets.QListWidgetItem(self._profile_row_text(p))
            it.setData(QtCore.Qt.UserRole, p.id)
            it.setToolTip(p.name)
            self.profile_list.addItem(it)
            if p.id == select_id:
                target_row = i
        if self.profiles:
            self.profile_list.setCurrentRow(target_row if target_row >= 0 else 0)
        else:
            self._render_no_profile()

    def _profile_row_text(self, p: BackupProfile) -> str:
        marker = {"ok": "●", "warning": "●", "error": "●", "never": "○"}.get(p.last_status, "○")
        return f"  {marker}  {p.name}"

    def _on_profile_select(self, row: int) -> None:
        if row < 0 or row >= len(self.profiles):
            self.current = None
            self._render_no_profile()
            return
        self.current = self.profiles[row]
        self.settings.last_profile = self.current.id
        self.settings.save()
        self._render_current()

    def _selected_profiles(self) -> list[BackupProfile]:
        """Return the BackupProfile objects backing the current multi-selection."""
        out: list[BackupProfile] = []
        for item in self.profile_list.selectedItems():
            pid = item.data(QtCore.Qt.UserRole)
            for p in self.profiles:
                if p.id == pid:
                    out.append(p)
                    break
        return out

    def _on_selection_changed(self) -> None:
        """Show or hide the 'Run selected' button based on selection size."""
        sel = self._selected_profiles()
        # The button is only meaningful when >1 profile is selected — for a
        # single selection, the existing "Run backup now" button in the detail
        # panel does the job and stays the primary action.
        if len(sel) >= 2 and not (self.worker or self.verify_worker or self.group_worker):
            self.run_group_btn.setText(f"▶  Run selected ({len(sel)})")
            self.run_group_btn.setVisible(True)
        else:
            self.run_group_btn.setVisible(False)

    # --- Render right-hand panel ----------------------------------------

    def _render_no_profile(self) -> None:
        self.profile_title.setText("Create your first backup profile")
        self.status_label.setText("Status: —")
        self.last_run_label.setText("")
        self.schedule_label.setText("")
        self.sources_view.clear()
        self.dest_view.clear()
        for b in (self.run_btn, self.verify_btn, self.restore_btn, self.schedule_btn, self.edit_btn, self.delete_btn):
            b.setEnabled(False)
        self.progress.setValue(0); self._set_progress_text("")

    def _render_current(self) -> None:
        p = self.current
        if p is None:
            return
        for b in (self.run_btn, self.verify_btn, self.restore_btn, self.schedule_btn, self.edit_btn, self.delete_btn):
            b.setEnabled(True)

        self.profile_title.setText(p.name)
        self.status_label.setText(f"Status: {p.last_status}")
        self.status_label.setObjectName(_status_color(p.last_status)); self.status_label.style().unpolish(self.status_label); self.status_label.style().polish(self.status_label)

        if p.last_run_iso:
            try:
                dt = datetime.fromisoformat(p.last_run_iso)
                self.last_run_label.setText(
                    f"Last run: {dt:%Y-%m-%d %H:%M}  •  {p.last_files_copied} files, {_human_bytes(p.last_bytes_copied)}"
                )
            except Exception:
                self.last_run_label.setText("Last run: " + p.last_run_iso)
        else:
            self.last_run_label.setText("Last run: never")

        if p.schedule_enabled:
            self.schedule_label.setText(f"Schedule: {p.schedule_cron}")
        else:
            self.schedule_label.setText("Schedule: not set")

        self.sources_view.clear()
        if not p.sources:
            self.sources_view.addItem("(no sources — click Edit to add)")
        for s in p.sources:
            it = QtWidgets.QListWidgetItem(s)
            it.setToolTip(s)
            if not os.path.exists(s):
                it.setForeground(QtGui.QBrush(QtGui.QColor("#e35d6a")))
                it.setText(s + "    ⚠ missing")
            self.sources_view.addItem(it)

        self.dest_view.clear()
        if not p.destinations:
            self.dest_view.addItem("(no destinations — click Edit to add)")
        for d in p.destinations:
            txt = d.display()
            available = True
            if d.kind == "local":
                available = is_path_available(d.path)
            it = QtWidgets.QListWidgetItem(("✔  " if available else "⚠  ") + txt)
            it.setToolTip(txt)
            if not available:
                it.setForeground(QtGui.QBrush(QtGui.QColor("#e9a23b")))
            self.dest_view.addItem(it)

    def _refresh_destination_freshness(self) -> None:
        if self.current and not self.worker:
            self._render_current()

    # --- Profile CRUD ----------------------------------------------------

    def _new_profile(self) -> None:
        prof = BackupProfile(name="New backup")
        dlg = ProfileEditor(self, prof)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            save_profile(prof)
            self._refresh_profiles(select_id=prof.id)

    def _edit_profile(self) -> None:
        if not self.current:
            return
        dlg = ProfileEditor(self, self.current)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            save_profile(self.current)
            self._refresh_profiles(select_id=self.current.id)

    def _delete_profile(self) -> None:
        if not self.current:
            return
        if QtWidgets.QMessageBox.question(
            self, "Delete profile",
            f"Delete profile '{self.current.name}'?\n"
            "This removes the profile and its scheduled task; backed-up files are kept.",
        ) != QtWidgets.QMessageBox.Yes:
            return
        sched.delete(self.current.id)
        delete_profile(self.current)
        self.current = None
        self._refresh_profiles()

    def _schedule_profile(self) -> None:
        if not self.current:
            return
        dlg = ScheduleDialog(self, self.current)
        dlg.exec()
        self._refresh_profiles(select_id=self.current.id)

    def _open_logs_folder(self) -> None:
        """Open %APPDATA%\\Anchor\\logs in Explorer. Creates it if missing.

        The logs folder lives under the hidden AppData tree, which most users
        can't browse to. This is the simplest way to expose it.
        """
        try:
            ensure_dirs()  # in case the user deleted them
        except OSError:
            pass
        target = str(LOGS_DIR)
        try:
            if os.name == "nt":
                os.startfile(target)  # type: ignore[attr-defined]
            else:
                import subprocess, sys as _sys
                if _sys.platform == "darwin":
                    subprocess.Popen(["open", target])
                else:
                    subprocess.Popen(["xdg-open", target])
        except OSError as e:
            QtWidgets.QMessageBox.warning(
                self, "Could not open logs folder", f"{target}\n\n{e}",
            )

    def _open_restore(self) -> None:
        if not self.current:
            return
        if not self.current.destinations:
            QtWidgets.QMessageBox.warning(
                self, "No destinations",
                "This profile has no destinations to restore from.")
            return
        dlg = RestoreDialog(self, self.current)
        dlg.exec()

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self, self.settings)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            apply_theme(QtWidgets.QApplication.instance(), self.settings.theme)

    def _toggle_theme(self) -> None:
        self.settings.theme = "light" if self.settings.theme == "dark" else "dark"
        self.settings.save()
        apply_theme(QtWidgets.QApplication.instance(), self.settings.theme)

    # --- Running a backup ------------------------------------------------

    def _run_backup(self) -> None:
        if not self.current:
            return
        if self.worker:
            return
        if not self.current.sources:
            QtWidgets.QMessageBox.warning(self, "No sources",
                "Add at least one source folder before running.")
            return
        if not self.current.destinations:
            QtWidgets.QMessageBox.warning(self, "No destinations",
                "Add at least one destination before running.")
            return

        self.worker = BackupWorker(self.current)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_ok.connect(self._on_finished_ok)
        self.worker.finished_err.connect(self._on_finished_err)
        self.worker.start()

        self.run_btn.setEnabled(False)
        self.verify_btn.setEnabled(False)
        self.restore_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.edit_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)
        self.progress.setValue(0)
        self._set_progress_text("Scanning…")
        self.statusBar().showMessage("Backup running…")

    def _cancel_backup(self) -> None:
        if self.worker:
            self.worker.request_cancel()
            self.statusBar().showMessage("Cancelling…")
        if self.verify_worker:
            self.verify_worker.request_cancel()
            self.statusBar().showMessage("Cancelling verify…")
        if self.group_worker:
            self.group_worker.request_cancel()
            self.statusBar().showMessage("Cancelling group run…")

    # --- Group run ------------------------------------------------------

    def _run_selected_group(self) -> None:
        if self.worker or self.verify_worker or self.group_worker:
            return
        profiles = self._selected_profiles()
        if len(profiles) < 2:
            return
        # Sanity: each profile in the group must have at least one source and
        # one destination, otherwise it would just fail in the engine.
        invalid = [p.name for p in profiles if not p.sources or not p.destinations]
        if invalid:
            QtWidgets.QMessageBox.warning(
                self, "Some profiles are incomplete",
                "The following profiles have no sources or no destinations and "
                "will be skipped:\n\n  • " + "\n  • ".join(invalid),
            )
            profiles = [p for p in profiles if p.sources and p.destinations]
            if not profiles:
                return

        self.group_worker = BackupGroupWorker(profiles, parent=self)
        self.group_worker.progress.connect(self._on_progress)
        self.group_worker.one_profile_done.connect(self._on_one_group_profile_done)
        self.group_worker.finished_ok.connect(self._on_group_finished_ok)
        self.group_worker.finished_err.connect(self._on_group_finished_err)

        # Lock UI like a single run
        self.run_btn.setEnabled(False)
        self.verify_btn.setEnabled(False)
        self.restore_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.edit_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)
        self.run_group_btn.setEnabled(False)
        self.progress.setValue(0)
        self._set_progress_text(f"Group run starting — {len(profiles)} profile(s)…")
        self.statusBar().showMessage(f"Group run: {len(profiles)} profile(s)…")
        self.group_worker.start()

    def _on_one_group_profile_done(self, result) -> None:
        # Refresh sidebar so this profile's status dot updates immediately.
        self._refresh_profiles(select_id=self.current.id if self.current else "")

    def _on_group_finished_ok(self, results) -> None:
        self.group_worker = None
        self.run_btn.setEnabled(True)
        self.verify_btn.setEnabled(True)
        self.restore_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.edit_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)
        self.run_group_btn.setEnabled(True)
        self.progress.setValue(100)

        # Aggregate counters for the group summary.
        total_copied = sum(r.files_copied for r in results)
        total_skipped = sum(r.files_skipped for r in results)
        total_failed = sum(r.files_failed for r in results)
        total_verify_issues = sum(len(r.verify_issues) for r in results)
        total_bytes = sum(r.bytes_copied for r in results)
        verify_part = ""
        if any(r.verify_checked for r in results):
            if total_verify_issues:
                verify_part = f", verify FAILED on {total_verify_issues}"
            else:
                verify_part = ", verify OK"
        self._set_progress_text(
            f"Group done — {len(results)} profile(s)"
            f"  •  copied {total_copied}"
            f"  •  skipped {total_skipped}"
            f"  •  failed {total_failed}"
            f"{verify_part}"
            f"  •  {_human_bytes(total_bytes)} copied"
        )
        self.statusBar().showMessage("Ready")

        # Combine all issues from every profile so the View Issues button
        # shows the full group.
        all_issues: list[str] = []
        for r in results:
            all_issues.extend(r.errors or [])
            all_issues.extend(r.verify_issues or [])
        self._set_last_errors(all_issues, title="Group run — issues")
        self._refresh_profiles(select_id=self.current.id if self.current else "")
        # Refresh visibility of the run-group button against the (now-stale)
        # selection state.
        self._on_selection_changed()

    def _on_group_finished_err(self, msg: str) -> None:
        self.group_worker = None
        self.run_btn.setEnabled(True)
        self.verify_btn.setEnabled(True)
        self.restore_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.edit_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)
        self.run_group_btn.setEnabled(True)
        self._set_progress_text(f"Group run aborted: {msg}")
        self.statusBar().showMessage("Error")
        QtWidgets.QMessageBox.critical(self, "Group run failed", msg)
        self._on_selection_changed()

    # --- Verify ----------------------------------------------------------

    def _verify_backup(self) -> None:
        if not self.current or self.worker or self.verify_worker:
            return
        if not self.current.destinations:
            QtWidgets.QMessageBox.warning(
                self, "No destinations",
                "Add at least one destination before verifying.")
            return
        self.verify_worker = VerifyWorker(self.current)
        self.verify_worker.progress.connect(self._on_progress)
        self.verify_worker.finished_ok.connect(self._on_verify_finished_ok)
        self.verify_worker.finished_err.connect(self._on_verify_finished_err)
        self.verify_worker.start()

        self.run_btn.setEnabled(False)
        self.verify_btn.setEnabled(False)
        self.restore_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.edit_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)
        self.progress.setValue(0)
        self._set_progress_text("Verifying…")
        self.statusBar().showMessage("Verify running…")

    def _on_verify_finished_ok(self, result) -> None:
        self.verify_worker = None
        self.run_btn.setEnabled(True)
        self.verify_btn.setEnabled(True)
        self.restore_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.edit_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)
        self.progress.setValue(100)
        bytes_mb = result.bytes_checked / (1024 * 1024)
        n_issues = (
            len(result.mismatches) + len(result.missing_at_dest)
            + len(result.unexpected_at_dest) + len(result.errors)
        )
        verdict = "OK" if n_issues == 0 else f"{n_issues} issue(s)"
        self._set_progress_text(
            f"Verify done — checked {result.files_checked} files "
            f"({bytes_mb:.1f} MB) in {_human_time(result.duration_s)} → {verdict}"
        )
        self.statusBar().showMessage("Ready")
        self._set_last_errors(
            result.all_issues,
            title=f"Verify of '{self.current.name}' — issues" if self.current else "Verify — issues",
        )

    def _on_verify_finished_err(self, msg: str) -> None:
        self.verify_worker = None
        self.run_btn.setEnabled(True)
        self.verify_btn.setEnabled(True)
        self.restore_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.edit_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)
        self._set_progress_text(f"Verify error: {msg}")
        self.statusBar().showMessage("Error")
        QtWidgets.QMessageBox.critical(self, "Verify failed", msg)

    def _on_progress(self, p) -> None:
        phase = getattr(p, "phase", "copying") or "copying"

        # During the WALKING + CLASSIFYING phase ("scanning"):
        #   - while files_total is 0 (walking, total unknown): show indeterminate bar
        #   - once files_total is known: show files_done / files_total
        # During the COPYING phase: bar tracks bytes_done / bytes_total (which
        # are now scoped to the to-copy subset, not the whole scan).
        if phase == "scanning":
            if p.files_total <= 0:
                # Indeterminate — Qt convention: range (0, 0).
                if self.progress.maximum() != 0:
                    self.progress.setRange(0, 0)
            else:
                if self.progress.maximum() != 100:
                    self.progress.setRange(0, 100)
                self.progress.setValue(min(100, int(p.files_done * 100 / max(1, p.files_total))))
        else:  # copying / done / error
            if self.progress.maximum() != 100:
                self.progress.setRange(0, 100)
            if p.bytes_total > 0:
                self.progress.setValue(min(100, int(p.bytes_done * 100 / p.bytes_total)))
            elif p.files_total > 0:
                self.progress.setValue(min(100, int(p.files_done * 100 / p.files_total)))
            else:
                # Nothing needed copying — fill the bar so users see "done".
                self.progress.setValue(100)

        speed = _human_bytes(p.speed_bps) + "/s" if p.speed_bps > 1 else ""
        eta = _human_time(p.eta_seconds) if p.eta_seconds > 0 else ""

        if phase == "scanning":
            # Walking has no total yet; classifying does. Phrase accordingly.
            if p.files_total <= 0:
                tally = f"Scanning source — {p.files_done} files found ({_human_bytes(p.bytes_done)})"
            else:
                tally = (
                    f"Scanning — {p.files_done} of {p.files_total} checked"
                    f"  •  {p.files_skipped} unchanged so far"
                )
            parts = [p.dest_label, tally]
        elif phase == "scan-done":
            # Pause-and-show summary between scan and copy.
            mb = _human_bytes(p.bytes_to_copy)
            tally = (
                f"Scan complete — {p.files_to_copy} to copy ({mb}), "
                f"{p.files_skipped} unchanged. Starting copy…"
            )
            parts = [p.dest_label, tally]
            # Hold the bar at 100% for this phase so the visual feels "complete".
            if self.progress.maximum() != 100:
                self.progress.setRange(0, 100)
            self.progress.setValue(100)
        elif phase == "verifying":
            # Post-copy: walking the source again to confirm everything is at
            # the destination. files_total is the source count; files_done is
            # how many we've checked so far.
            if self.progress.maximum() != 100:
                self.progress.setRange(0, 100)
            if p.files_total > 0:
                self.progress.setValue(min(100, int(p.files_done * 100 / p.files_total)))
            tally = f"Verifying — {p.files_done} of {p.files_total} files checked at destination"
            parts = [p.dest_label, tally]
        else:
            # Copying tally: show progress within the to-copy subset, plus the
            # cumulative "unchanged" so users can see what was skipped.
            tally = (
                f"Copying — {p.files_done} of {p.files_total} files"
                f"  •  {p.files_skipped} unchanged"
            )
            if p.files_failed:
                tally += f"  •  {p.files_failed} failed"
            bytes_str = f"{_human_bytes(p.bytes_done)} / {_human_bytes(p.bytes_total)}"
            parts = [p.dest_label, tally, bytes_str]
            if speed:
                parts.append(speed)
            if eta:
                parts.append("ETA " + eta)

        full = "  •  ".join(parts) + ("  •  " + p.current_file if p.current_file else "")
        self._set_progress_text(full)

    def _set_progress_text(self, text: str) -> None:
        """Set progress_label text without letting it widen/grow the window.

        We measure the text against the label's current pixel width and elide
        the middle if needed. Full text goes into the tooltip so the user can
        still read it on hover. The full text is also remembered so resize
        events can re-elide against the new width.
        """
        self._progress_full_text = text
        self.progress_label.setToolTip(text)
        self._reelide_progress()

    def _reelide_progress(self) -> None:
        text = getattr(self, "_progress_full_text", None)
        if text is None:
            return
        fm = self.progress_label.fontMetrics()
        # 16px slack for padding/borders so we never hit the right edge.
        avail = max(40, self.progress_label.width() - 16)
        elided = fm.elidedText(text, QtCore.Qt.ElideMiddle, avail)
        self.progress_label.setText(elided)

    def resizeEvent(self, ev: QtGui.QResizeEvent) -> None:
        super().resizeEvent(ev)
        # Re-elide the progress text against the new width so the middle "…"
        # shrinks/grows with the window.
        self._reelide_progress()

    def _on_finished_ok(self, result) -> None:
        self.worker = None
        self.run_btn.setEnabled(True)
        self.verify_btn.setEnabled(True)
        self.restore_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.edit_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)
        self.progress.setValue(100)
        verify_part = ""
        if getattr(result, "verify_checked", 0):
            if result.verify_issues:
                verify_part = f", verify FAILED on {len(result.verify_issues)}"
            else:
                verify_part = f", verified {result.verify_checked} OK"
        self._set_progress_text(
            f"Done — copied {result.files_copied} files "
            f"({_human_bytes(result.bytes_copied)}), "
            f"skipped {result.files_skipped}, failed {result.files_failed}"
            f"{verify_part} "
            f"in {_human_time(result.duration_s)}"
        )
        self.statusBar().showMessage("Ready")
        # Combine engine errors and verify issues into the single issues view.
        all_issues = list(getattr(result, "errors", []) or [])
        all_issues.extend(getattr(result, "verify_issues", []) or [])
        self._set_last_errors(
            all_issues,
            title=f"Backup of '{self.current.name}' — issues" if self.current else "Backup — issues",
        )
        self._refresh_profiles(select_id=self.current.id if self.current else "")

    # --- Issues panel ----------------------------------------------------

    def _set_last_errors(self, errors: list[str], title: str) -> None:
        """Update the persistent error list shown via the issues button.

        Called from both backup-finished and verify-finished paths so the
        button is always backed by the freshest data.
        """
        self._last_errors = list(errors)
        self._last_errors_title = title
        n = len(self._last_errors)
        self.issues_btn.setVisible(n > 0)
        self.issues_btn.setText(f"⚠  View {n} issue{'s' if n != 1 else ''}")

    def _show_issues(self) -> None:
        if not self._last_errors:
            return
        dlg = IssuesDialog(self, self._last_errors_title, self._last_errors)
        dlg.exec()

    def _on_finished_err(self, msg: str) -> None:
        self.worker = None
        self.run_btn.setEnabled(True)
        self.verify_btn.setEnabled(True)
        self.restore_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.edit_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)
        self._set_progress_text(f"Error: {msg}")
        self.statusBar().showMessage("Error")
        QtWidgets.QMessageBox.critical(self, "Backup failed", msg)

    # --- Log viewer ------------------------------------------------------

    def _wire_log_tail(self) -> None:
        tail = get_tail()
        # populate with existing buffer
        for line in tail.snapshot()[-200:]:
            self.log_view.appendPlainText(line)

        def on_line(level: str, msg: str) -> None:
            # marshal back to UI thread
            QtCore.QMetaObject.invokeMethod(
                self.log_view, "appendPlainText",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(str, msg),
            )
        tail.add_listener(on_line)
        self._log_listener = on_line  # keep ref

    def _clear_log(self) -> None:
        self.log_view.clear()

    # --- Close handling --------------------------------------------------

    def closeEvent(self, ev: QtGui.QCloseEvent) -> None:
        # Any of the workers running blocks a clean exit.
        running = []
        if self.worker and self.worker.isRunning():
            running.append(("backup", self.worker))
        if self.verify_worker and self.verify_worker.isRunning():
            running.append(("verify", self.verify_worker))
        if self.group_worker and self.group_worker.isRunning():
            running.append(("group run", self.group_worker))
        if running:
            r = QtWidgets.QMessageBox.question(
                self, "Work in progress",
                "A " + " and ".join(name for name, _ in running)
                + " is in progress. Cancel and quit?",
            )
            if r != QtWidgets.QMessageBox.Yes:
                ev.ignore(); return
            for _, w in running:
                w.request_cancel()
                w.wait(3000)
        super().closeEvent(ev)
