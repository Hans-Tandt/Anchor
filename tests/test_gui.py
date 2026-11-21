"""Headless GUI tests (QT_QPA_PLATFORM=offscreen, set in conftest).

Cover the GUI bugs fixed in 1.5.0 plus a smoke test of the main window.
"""
from __future__ import annotations

import os
import time

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6 import QtCore  # noqa: E402

from anchor.app_config import AppSettings  # noqa: E402
from anchor.core.profile import BackupProfile, DestinationConfig, list_profiles, save_profile  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from anchor.gui.theme import apply_theme
    apply_theme(app, "dark")
    return app


def _wait(app, cond, timeout=30.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def _make_source(tmp_path, n=5):
    src = tmp_path / "My_Docs"
    src.mkdir()
    for i in range(n):
        (src / f"f{i}.txt").write_text("x" * (100 + i))
    return src


# --- main window ------------------------------------------------------------

def test_main_window_smoke_and_theme(qapp, tmp_path):
    from anchor.gui import MainWindow
    from anchor.gui.theme import apply_theme, theme_manager

    src = _make_source(tmp_path)
    p = BackupProfile(name="Docs", sources=[str(src)],
                      destinations=[DestinationConfig(kind="local", path=str(tmp_path / "dest"))])
    save_profile(p)
    w = MainWindow(AppSettings())
    w.show()
    qapp.processEvents()
    assert w.dashboard.current is not None and w.dashboard.current.id == p.id
    for key in ("activity", "settings", "backups"):
        w.nav.set_current(key)
        qapp.processEvents()
    apply_theme(qapp, "light")
    assert not theme_manager.is_dark
    apply_theme(qapp, "dark")
    assert theme_manager.is_dark
    w.close()


def test_backup_end_to_end_through_controller(qapp, tmp_path):
    """A real backup through the RunController: busy stays true until the
    thread has exited, and a second run can't start while one is active."""
    from anchor.gui.controller import RunController

    src = _make_source(tmp_path, 20)
    dest = tmp_path / "dest"
    p = BackupProfile(name="Docs", sources=[str(src)],
                      destinations=[DestinationConfig(kind="local", path=str(dest))])
    save_profile(p)
    c = RunController()
    results = []
    c.backup_finished.connect(lambda r, cancelled: results.append((r, cancelled)))
    assert c.run_backup(p)
    assert c.is_busy()
    assert not c.run_backup(p), "second concurrent run must be refused"
    assert not c.run_verify(p), "verify during a backup must be refused"
    assert _wait(qapp, lambda: not c.is_busy(), 60)
    assert results and results[0][0].files_copied == 20 and not results[0][1]
    copied = [f for _r, _d, fs in os.walk(dest) for f in fs if f.endswith(".txt")]
    assert len(copied) == 20
    # run summary persisted to disk
    saved = [x for x in list_profiles() if x.id == p.id][0]
    assert saved.last_status == "ok" and saved.last_files_copied == 20


def test_drive_poll_does_not_reenable_run_during_verify(qapp, tmp_path):
    """Old bug: the 5 s poll re-rendered the profile and re-enabled Run while
    a verify / group run was active."""
    from anchor.gui import MainWindow

    src = _make_source(tmp_path)
    p = BackupProfile(name="Docs", sources=[str(src)],
                      destinations=[DestinationConfig(kind="local", path=str(tmp_path / "d"))])
    save_profile(p)
    w = MainWindow(AppSettings())
    d = w.dashboard
    w.controller.busy_changed.emit(True)  # simulate an active job
    class _FakeWorker:
        def is_cancelling(self):
            return False
    w.controller._worker = _FakeWorker()  # type: ignore[assignment]
    d._sync_buttons()
    w._on_poll()
    assert not d.run_btn.isEnabled()
    assert not d.edit_btn.isEnabled()
    w.controller._worker = None
    w.close()


# --- restore -----------------------------------------------------------------

def test_restore_original_target_keeps_underscores(tmp_path):
    from anchor.core.walker import source_label
    from anchor.gui.restore_dialog import _original_target

    src = tmp_path / "My_Docs" / "sub_dir"
    src.mkdir(parents=True)
    p = BackupProfile(sources=[str(src)])
    rel = f"{source_label(str(src))}/a_b/file_1.txt"
    target = _original_target(p, rel)
    assert target == os.path.join(str(src), "a_b", "file_1.txt")


def test_restore_original_target_refuses_traversal(tmp_path):
    from anchor.core.walker import source_label
    from anchor.gui.restore_dialog import _original_target

    src = tmp_path / "src"
    src.mkdir()
    p = BackupProfile(sources=[str(src)])
    assert _original_target(p, f"{source_label(str(src))}/../../evil.txt") is None
    assert _original_target(p, "UNKNOWN_label/file.txt") is None


def test_restore_flat_layout(tmp_path):
    from anchor.gui.restore_dialog import _original_target

    src = tmp_path / "src"
    src.mkdir()
    p = BackupProfile(sources=[str(src)], flat_destination_layout=True)
    assert _original_target(p, "x/y.txt") == os.path.join(str(src), "x", "y.txt")


# --- dialogs -----------------------------------------------------------------

def test_profile_editor_refused_save_leaves_profile_untouched(qapp, tmp_path, monkeypatch):
    from anchor.gui.profile_editor import ProfileEditor

    p = BackupProfile(name="Original", sources=[str(tmp_path / "a"), str(tmp_path / "b")])
    ed = ProfileEditor(None, p)
    ed.name_edit.setText("Changed")
    ed.flat_layout.setChecked(True)
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *a, **k: None)
    ed._accept()
    assert p.name == "Original"
    assert not p.flat_destination_layout


def test_destination_dialog_keeps_custom_port(qapp):
    from anchor.gui.profile_editor import DestinationDialog

    cfg = DestinationConfig(kind="sftp", host="nas", port=2222, username="u", remote_path="/b")
    dlg = DestinationDialog(None, cfg)
    assert dlg.port.value() == 2222
    dlg.kind.setCurrentIndex(3)  # user switches to WebDAV → default port applies
    assert dlg.port.value() == 443


def test_schedule_dialog_does_not_force_monday(qapp):
    from anchor.gui.schedule_dialog import ScheduleDialog

    p = BackupProfile(schedule_enabled=True, schedule_cron="Weekly on SAT,SUN at 10:00")
    dlg = ScheduleDialog(None, p)
    assert dlg.freq.currentIndex() == 1
    assert not dlg.day_checks["MON"].isChecked()
    assert dlg.day_checks["SAT"].isChecked() and dlg.day_checks["SUN"].isChecked()


# --- helpers -----------------------------------------------------------------

def test_destination_available_when_drive_present_but_folder_new(tmp_path):
    from anchor.drives import is_path_available

    assert is_path_available(str(tmp_path / "not" / "created" / "yet"))
    assert not is_path_available("")


def test_icons_render_every_glyph(qapp):
    from anchor.gui import icons

    for name in icons.names():
        assert not icons.pixmap(name, 16).isNull(), name
