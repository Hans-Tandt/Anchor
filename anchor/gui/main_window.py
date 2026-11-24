"""Main application window — Fluent shell.

    +--------------+-------------------------------------------------+
    | ≡  Anchor    |                                                 |
    |              |   Backups  | profile detail / run / paths       |
    |  Backups     |   (list)   |                                    |
    |  Activity    |            |                                    |
    |              |            |                                    |
    |  ☾ Theme     |            |                                    |
    |  ⚙ Settings  |            |                                    |
    +--------------+-------------------------------------------------+

The window wires pages to the RunController and owns the dialogs, tray icon,
toasts and the drive poll. It holds no backup state of its own.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from .. import __app_name__, __version__
from .. import scheduler as sched
from ..app_config import LOGS_DIR, AppSettings
from ..core.profile import BackupProfile, delete_profile, list_profiles, save_profile
from ..drives import is_path_available
from . import icons
from .controller import RunController
from .issues_dialog import IssuesDialog
from .pages.activity import ActivityPage
from .pages.dashboard import DashboardPage
from .pages.settings import SettingsPage, open_in_explorer
from .profile_editor import ProfileEditor
from .restore_dialog import RestoreDialog
from .schedule_dialog import ScheduleDialog
from .theme import apply_theme, apply_window_chrome, theme_manager
from .widgets import NavigationRail, ToastHost, hline, human_bytes, human_time, label

RESOURCES = Path(__file__).resolve().parent.parent / "resources"
ICON_FILE = RESOURCES / "icons" / "anchor.ico"


def app_icon() -> QtGui.QIcon:
    if ICON_FILE.exists():
        return QtGui.QIcon(str(ICON_FILE))
    return icons.icon("anchor", color_value="#d4a85a")


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, settings: AppSettings):
        super().__init__()
        self.settings = settings
        self.setWindowTitle(f"{__app_name__} {__version__}")
        self.setWindowIcon(app_icon())
        self.resize(1240, 800)
        self.setMinimumSize(980, 640)

        self.controller = RunController(self)
        self._last_errors: List[str] = []
        self._last_errors_title = "Last run — issues"
        # Local-destination availability per profile, for auto-run on plug-in.
        self._avail: Dict[str, bool] = {}
        self._quitting = False

        self._build_ui()
        self._wire_controller()
        self._build_tray()
        self._build_shortcuts()
        self.reload_profiles(select_id=settings.last_profile)
        self._avail = self._snapshot_availability()

        self._poll = QtCore.QTimer(self)
        self._poll.setInterval(5000)
        self._poll.timeout.connect(self._on_poll)
        self._poll.start()

    # --- construction ----------------------------------------------------

    def _build_ui(self) -> None:
        shell = QtWidgets.QWidget()
        shell.setObjectName("shell")
        self.setCentralWidget(shell)
        h = QtWidgets.QHBoxLayout(shell)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        self.nav = NavigationRail()
        self.nav.add_item("backups", "home", "Backups")
        self.nav.add_item("activity", "activity", "Activity")
        self.theme_item = self.nav.add_action("moon", "Dark theme", self._toggle_theme)
        self.nav.add_item("settings", "settings", "Settings", bottom=True)
        self.nav.set_footer(self._brand_footer())
        h.addWidget(self.nav)

        frame = QtWidgets.QFrame()
        frame.setObjectName("pageFrame")
        fl = QtWidgets.QVBoxLayout(frame)
        fl.setContentsMargins(0, 0, 0, 0)
        self.pages = QtWidgets.QStackedWidget()
        self.pages.setObjectName("pages")
        fl.addWidget(self.pages)
        h.addWidget(frame, 1)
        self.toasts = ToastHost(frame)

        self.dashboard = DashboardPage(self.controller)
        self.activity = ActivityPage(self._open_logs)
        self.settings_page = SettingsPage(self.settings)
        self._page_for = {"backups": self.dashboard, "activity": self.activity, "settings": self.settings_page}
        for w in self._page_for.values():
            self.pages.addWidget(w)
        self.nav.current_changed.connect(self._show_page)
        self.nav.set_current("backups")
        self.nav.set_expanded(self.settings.nav_expanded, animate=False)
        self.nav.menu_btn.clicked.connect(self._remember_nav)

        d = self.dashboard
        d.new_profile_requested.connect(self.new_profile)
        d.edit_requested.connect(self.edit_profile)
        d.delete_requested.connect(self.delete_profile)
        d.schedule_requested.connect(self.schedule_profile)
        d.restore_requested.connect(self.open_restore)
        d.issues_requested.connect(self.show_issues)
        d.run_requested.connect(self.run_backup)
        d.verify_requested.connect(self.verify_backup)
        d.group_run_requested.connect(self.run_group)
        d.current_changed.connect(self._on_current_changed)
        self.activity.error_count_changed.connect(lambda n: self.nav.set_badge("activity", n))
        self.settings_page.theme_changed.connect(self._set_theme)
        theme_manager.changed.connect(self._sync_theme_item)
        self._sync_theme_item()

    def _brand_footer(self) -> QtWidgets.QWidget:
        """Sidebar credit: the TechEase logo (black keyed out, so it sits on
        either theme) above a thin divider-separated credit line."""
        f = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(f)
        lay.setContentsMargins(14, 6, 14, 10)
        lay.setSpacing(6)
        lay.addWidget(hline())
        banner = RESOURCES / "brand" / "techease-banner-transparent.png"
        pix = QtGui.QPixmap(str(banner)) if banner.exists() else QtGui.QPixmap()
        if not pix.isNull():
            logo = QtWidgets.QLabel()
            dpr = self.devicePixelRatioF() or 1.0
            scaled = pix.scaledToWidth(int(160 * dpr), QtCore.Qt.SmoothTransformation)
            scaled.setDevicePixelRatio(dpr)
            logo.setPixmap(scaled)
            logo.setAlignment(QtCore.Qt.AlignCenter)
            logo.setToolTip("TechEase — where industry meets AI")
            lay.addWidget(logo)
        credit = label("CREATED BY HANS TANDT", "brandCredit")
        credit.setAlignment(QtCore.Qt.AlignCenter)
        lay.addWidget(credit)
        return f

    def _build_tray(self) -> None:
        self.tray: Optional[QtWidgets.QSystemTrayIcon] = None
        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QtWidgets.QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip(f"{__app_name__} — idle")
        menu = QtWidgets.QMenu()
        menu.addAction("Open Anchor", self._bring_to_front)
        self._tray_cancel = menu.addAction("Stop running job", self.controller.cancel)
        self._tray_cancel.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Quit", self.close)
        self.tray.setContextMenu(menu)
        self._tray_menu = menu
        self.tray.activated.connect(
            lambda r: self._bring_to_front() if r == QtWidgets.QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def _build_shortcuts(self) -> None:
        def sc(seq, fn):
            s = QtGui.QShortcut(QtGui.QKeySequence(seq), self)
            s.activated.connect(fn)
        sc("Ctrl+N", self.new_profile)
        sc("F5", self.run_backup)
        sc("Ctrl+E", self.edit_profile)
        sc("Escape", lambda: self.controller.cancel() if self.controller.is_busy() else None)
        sc("Ctrl+1", lambda: self.nav.set_current("backups"))
        sc("Ctrl+2", lambda: self.nav.set_current("activity"))
        sc("Ctrl+,", lambda: self.nav.set_current("settings"))
        sc("Ctrl+F", lambda: (self.nav.set_current("backups"), self.dashboard.search.setFocus()))

    def _wire_controller(self) -> None:
        c = self.controller
        c.busy_changed.connect(self._on_busy_changed)
        c.backup_finished.connect(self._on_backup_finished)
        c.group_profile_done.connect(lambda _r: self.reload_profiles())
        c.group_finished.connect(self._on_group_finished)
        c.verify_finished.connect(self._on_verify_finished)
        c.failed.connect(self._on_failed)
        c.progress.connect(self._on_progress_tray)

    # --- navigation / theme ----------------------------------------------

    def _show_page(self, key: str) -> None:
        w = self._page_for.get(key)
        if w is not None:
            self.pages.setCurrentWidget(w)

    def _remember_nav(self) -> None:
        self.settings.nav_expanded = self.nav.is_expanded()
        self._save_settings()

    def _set_theme(self, mode: str) -> None:
        apply_theme(QtWidgets.QApplication.instance(), mode)

    def _toggle_theme(self) -> None:
        mode = "light" if theme_manager.is_dark else "dark"
        self.settings.theme = mode
        self._save_settings()
        self.settings_page.sync_theme(mode)
        self._set_theme(mode)

    def _sync_theme_item(self) -> None:
        it = self.theme_item
        it.icon_name = "sun" if theme_manager.is_dark else "moon"
        it.setText("Light theme" if theme_manager.is_dark else "Dark theme")
        it.setToolTip(it.text())
        it.update()

    def _save_settings(self) -> None:
        try:
            self.settings.save()
        except OSError:
            pass

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        apply_window_chrome(self)

    def _bring_to_front(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # --- profiles --------------------------------------------------------

    def reload_profiles(self, select_id: str = "") -> None:
        self.dashboard.set_profiles(list_profiles(), select_id=select_id)

    @property
    def current(self) -> Optional[BackupProfile]:
        return self.dashboard.current

    def _on_current_changed(self, p: Optional[BackupProfile]) -> None:
        if p is not None and self.settings.last_profile != p.id:
            self.settings.last_profile = p.id
            self._save_settings()

    def new_profile(self) -> None:
        if self.controller.is_busy():
            return
        prof = BackupProfile(name="New backup", verify_with_hash=self.settings.verify_with_hash)
        dlg = ProfileEditor(self, prof)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._save_profile(prof)
            self.nav.set_current("backups")
            self.reload_profiles(select_id=prof.id)
            self.toasts.show("success", "Profile created", f"'{prof.name}' is ready. Press Back up now to run it.")

    def edit_profile(self) -> None:
        p = self.current
        if p is None or self.controller.is_busy():
            return
        dlg = ProfileEditor(self, p)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._save_profile(p)
            self.reload_profiles(select_id=p.id)
            self.toasts.show("success", "Profile saved", p.name, 2500)

    def _save_profile(self, p: BackupProfile) -> None:
        try:
            save_profile(p)
        except (OSError, ValueError) as e:
            QtWidgets.QMessageBox.critical(self, "Could not save profile", str(e))

    def delete_profile(self) -> None:
        p = self.current
        if p is None or self.controller.is_busy():
            return
        if QtWidgets.QMessageBox.question(
            self, "Delete profile",
            f"Delete profile '{p.name}'?\n\n"
            "This removes the profile and its scheduled task. Files already backed up are kept.",
        ) != QtWidgets.QMessageBox.Yes:
            return
        err = sched.delete(p.id) if p.schedule_enabled else None
        try:
            delete_profile(p)
        except (OSError, ValueError) as e:
            QtWidgets.QMessageBox.critical(self, "Could not delete profile", str(e))
            return
        self.reload_profiles()
        if err:
            self.toasts.show("warning", "Profile deleted, schedule not removed", err, 8000)
        else:
            self.toasts.show("info", "Profile deleted", p.name, 3000)

    def schedule_profile(self) -> None:
        p = self.current
        if p is None:
            return
        ScheduleDialog(self, p).exec()
        self.reload_profiles(select_id=p.id)

    def open_restore(self) -> None:
        p = self.current
        if p is None or self.controller.is_busy():
            return
        if not p.destinations:
            self.toasts.show("warning", "Nothing to restore from", "This profile has no destinations.")
            return
        RestoreDialog(self, p).exec()

    def _open_logs(self) -> None:
        open_in_explorer(LOGS_DIR, self)

    # --- running ---------------------------------------------------------

    def _check_runnable(self, p: BackupProfile) -> bool:
        if not p.sources:
            self.toasts.show("warning", "No sources", f"Add at least one folder to '{p.name}' first.")
            return False
        if not p.destinations:
            self.toasts.show("warning", "No destinations", f"Add a destination to '{p.name}' first.")
            return False
        return True

    def run_backup(self, profile: Optional[BackupProfile] = None) -> None:
        p = profile or self.current
        if p is None or self.controller.is_busy() or not self._check_runnable(p):
            return
        self._set_last_errors([], "")
        self.controller.run_backup(p)

    def run_group(self, profiles: List[BackupProfile]) -> None:
        if self.controller.is_busy() or len(profiles) < 2:
            return
        invalid = [p.name for p in profiles if not p.sources or not p.destinations]
        runnable = [p for p in profiles if p.sources and p.destinations]
        if invalid:
            self.toasts.show("warning", "Skipping incomplete profiles", ", ".join(invalid), 7000)
        if not runnable:
            return
        self._set_last_errors([], "")
        self.controller.run_group(runnable)

    def verify_backup(self) -> None:
        p = self.current
        if p is None or self.controller.is_busy():
            return
        if not p.destinations:
            self.toasts.show("warning", "No destinations", "Add a destination before verifying.")
            return
        self._set_last_errors([], "")
        self.controller.run_verify(p)

    def _on_busy_changed(self, busy: bool) -> None:
        if self.tray is not None:
            self._tray_cancel.setEnabled(busy)
            if not busy:
                self.tray.setToolTip(f"{__app_name__} — idle")

    def _on_progress_tray(self, p) -> None:
        if self.tray is None:
            return
        phase = {"scanning": "scanning", "scan-done": "scan done", "copying": "copying",
                 "verifying": "verifying"}.get(p.phase, p.phase)
        pct = ""
        if p.phase == "copying" and p.bytes_total:
            pct = f" {int(p.bytes_done * 100 / p.bytes_total)}%"
        self.tray.setToolTip(f"{__app_name__} — {phase}{pct}")

    def _notify(self, kind: str, title: str, text: str) -> None:
        """Toast inside the window, plus a desktop notification when the
        window is in the background."""
        self.toasts.show(kind, title, text, 7000 if kind != "success" else 5000,
                         action=("View issues", self.show_issues) if self._last_errors else None)
        if (self.tray is not None and self.settings.notifications
                and not self.isActiveWindow()):
            icon = {"success": QtWidgets.QSystemTrayIcon.Information,
                    "warning": QtWidgets.QSystemTrayIcon.Warning,
                    "error": QtWidgets.QSystemTrayIcon.Critical}.get(kind, QtWidgets.QSystemTrayIcon.Information)
            self.tray.showMessage(title, text, icon, 8000)

    def _on_backup_finished(self, result, cancelled: bool) -> None:
        d = self.dashboard
        did_verify = bool(result.verify_checked)
        verify_failed = did_verify and bool(result.verify_issues)
        d.phase_strip.mark_done("scan", d.phase_strip.rows["scan"].detail_lbl.text())
        d.phase_strip.mark_done("copy", f"{result.files_copied:,} files · {human_bytes(result.bytes_copied)}")
        if did_verify:
            d.phase_strip.set_phase(
                "verify", "issue" if verify_failed else "done", 100,
                f"{result.verify_checked:,} files · "
                + (f"{len(result.verify_issues)} issue(s)" if verify_failed else "all present"),
            )
            if verify_failed:
                d.verify_banner.show_fail(
                    f"Verify failed — {len(result.verify_issues)} issue(s) in "
                    f"{result.verify_checked:,} checked files.", on_click=self.show_issues)
            else:
                d.verify_banner.show_pass(
                    f"Verify passed — all {result.verify_checked:,} files are present with the right size.")
        summary = (f"Copied {result.files_copied:,} files ({human_bytes(result.bytes_copied)}), "
                   f"skipped {result.files_skipped:,}, failed {result.files_failed:,} "
                   f"in {human_time(result.duration_s)}")
        d.set_progress_text(("Stopped — " if cancelled else "Done — ") + summary)
        d.run_title.setText("Last run — stopped" if cancelled else "Last run — finished")
        name = d.profile_by_id(result.profile_id).name if d.profile_by_id(result.profile_id) else "Backup"
        self._set_last_errors(list(result.errors or []) + list(result.verify_issues or []),
                              f"Backup of '{name}' — issues")
        had_issues = bool(result.files_failed or verify_failed or result.destinations_failed)
        d.finish_donut(cancelled, had_issues)
        self.reload_profiles()
        if cancelled:
            self._notify("warning", f"{name}: stopped", summary)
        elif result.status == "ok":
            self._notify("success", f"{name}: backup complete", summary)
        else:
            self._notify("error" if result.status == "error" else "warning",
                         f"{name}: finished with problems", summary)

    def _on_group_finished(self, results, cancelled: bool) -> None:
        d = self.dashboard
        copied = sum(r.files_copied for r in results)
        failed = sum(r.files_failed for r in results)
        vissues = sum(len(r.verify_issues) for r in results)
        nbytes = sum(r.bytes_copied for r in results)
        any_verified = any(r.verify_checked for r in results)
        d.phase_strip.mark_done("scan")
        d.phase_strip.mark_done("copy", f"{copied:,} files · {human_bytes(nbytes)}")
        if any_verified:
            d.phase_strip.set_phase("verify", "issue" if vissues else "done", 100, "")
            if vissues:
                d.verify_banner.show_fail(f"Verify failed — {vissues} issue(s) across {len(results)} profiles.",
                                          on_click=self.show_issues)
            else:
                checked = sum(r.verify_checked for r in results)
                d.verify_banner.show_pass(f"Verify passed — {checked:,} files checked across {len(results)} profiles.")
        summary = f"{len(results)} profile(s) · copied {copied:,} · failed {failed:,} · {human_bytes(nbytes)}"
        d.set_progress_text(("Group stopped — " if cancelled else "Group done — ") + summary)
        d.run_title.setText("Group run — stopped" if cancelled else "Group run — finished")
        issues: List[str] = []
        for r in results:
            issues.extend(r.errors or [])
            issues.extend(r.verify_issues or [])
        self._set_last_errors(issues, "Group run — issues")
        bad = any(r.status != "ok" for r in results)
        d.finish_donut(cancelled, bad)
        self.reload_profiles()
        self._notify("warning" if cancelled or bad else "success",
                     "Group run stopped" if cancelled else "Group run complete", summary)

    def _on_verify_finished(self, result, cancelled: bool) -> None:
        d = self.dashboard
        n = len(result.mismatches) + len(result.missing_at_dest) + len(result.unexpected_at_dest) + len(result.errors)
        mb = human_bytes(result.bytes_checked)
        d.phase_strip.set_phase("verify", "done" if n == 0 else "issue", 100,
                                f"{result.files_checked:,} files · {mb} · {human_time(result.duration_s)}")
        verdict = "OK" if n == 0 else f"{n} issue(s)"
        d.run_title.setText("Verify — stopped" if cancelled else "Verify — finished")
        d.set_progress_text(f"Verify {'stopped' if cancelled else 'done'} — checked {result.files_checked:,} "
                            f"files ({mb}) in {human_time(result.duration_s)} → {verdict}")
        name = self.current.name if self.current else "Verify"
        self._set_last_errors(result.all_issues, f"Verify of '{name}' — issues")
        if n == 0 and not cancelled:
            d.verify_banner.show_pass(f"Verify passed — {result.files_checked:,} files ({mb}) present and sized correctly.")
            self._notify("success", f"{name}: verify passed", f"{result.files_checked:,} files checked.")
        elif n:
            d.verify_banner.show_fail(f"Verify failed — {n} issue(s) in {result.files_checked:,} files.",
                                      on_click=self.show_issues)
            self._notify("error", f"{name}: verify found problems", f"{n} issue(s).")

    def _on_failed(self, kind: str, msg: str) -> None:
        d = self.dashboard
        if not d.donut.isHidden():
            d.donut.show_issues("Error")
        d.set_progress_text(f"{kind.capitalize()} error: {msg}")
        self.reload_profiles()
        QtWidgets.QMessageBox.critical(self, f"{kind.capitalize()} failed", msg)

    # --- issues ----------------------------------------------------------

    def _set_last_errors(self, errors: List[str], title: str) -> None:
        self._last_errors = list(errors)
        if title:
            self._last_errors_title = title
        self.dashboard.set_issue_count(len(self._last_errors))

    def show_issues(self) -> None:
        if self._last_errors:
            IssuesDialog(self, self._last_errors_title, self._last_errors).exec()

    # --- drive poll / auto-run -------------------------------------------

    def _snapshot_availability(self) -> Dict[str, bool]:
        out: Dict[str, bool] = {}
        for p in self.dashboard.profiles:
            locals_ = [d for d in p.destinations if d.kind == "local" and d.path]
            if locals_:
                out[p.id] = any(is_path_available(d.path) for d in locals_)
        return out

    def _on_poll(self) -> None:
        self.dashboard.refresh_availability()
        now = self._snapshot_availability()
        if self.settings.auto_run_on_drive_plug_in and not self.controller.is_busy():
            for pid, up in now.items():
                if up and self._avail.get(pid) is False:
                    p = self.dashboard.profile_by_id(pid)
                    if p is not None and p.sources:
                        self.toasts.show("info", "Drive connected", f"Starting '{p.name}'.")
                        self.run_backup(p)
                        break
        self._avail = now

    # --- close -----------------------------------------------------------

    def closeEvent(self, ev: QtGui.QCloseEvent) -> None:
        if self.controller.is_busy():
            r = QtWidgets.QMessageBox.question(
                self, "Job in progress",
                f"A {self.controller.kind} is running. Stop it and quit?\n\n"
                "Files already copied are kept; the next run picks up where this one stopped.",
            )
            if r != QtWidgets.QMessageBox.Yes:
                ev.ignore()
                return
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            try:
                stopped = self.controller.shutdown(15000)
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()
            if not stopped:
                # Never tear down a QThread that is still running.
                QtWidgets.QMessageBox.warning(
                    self, "Still stopping",
                    "The job is finishing its current file. Try closing again in a moment.")
                ev.ignore()
                return
        self._poll.stop()
        self.activity.shutdown()
        if self.tray is not None:
            self.tray.hide()
        super().closeEvent(ev)
