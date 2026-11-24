"""Settings page — Fluent setting cards. Changes apply and save immediately."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ... import __version__
from ...app_config import APP_DIR, LOGS_DIR, PROFILES_DIR, AppSettings
from ..widgets import SettingCard, SettingGroup, ToggleSwitch, button, label

PROJECT_URL = "https://hanstandt.be/projects/anchor/"
REPO_URL = "https://github.com/Hans-Tandt/Anchor"

_BRAND = Path(__file__).resolve().parent.parent.parent / "resources" / "brand" / "techease-banner-transparent.png"


def open_in_explorer(path: Path, parent=None) -> None:
    """Open a folder in the OS file manager, creating it first if missing."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    p = str(path)
    try:
        if os.name == "nt":
            os.startfile(p)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p])
    except OSError as e:
        QtWidgets.QMessageBox.warning(parent, "Could not open folder", f"{p}\n\n{e}")


class SettingsPage(QtWidgets.QWidget):
    theme_changed = QtCore.Signal(str)
    settings_saved = QtCore.Signal()

    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.settings = settings

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        inner = QtWidgets.QWidget()
        inner.setObjectName("pageInner")
        scroll.setWidget(inner)
        lay = QtWidgets.QVBoxLayout(inner)
        lay.setContentsMargins(28, 24, 28, 28)
        lay.setSpacing(22)
        lay.addWidget(label("Settings", "title"))

        # --- appearance ---------------------------------------------------
        g = SettingGroup("Appearance")
        self.theme = QtWidgets.QComboBox()
        self.theme.addItem("Dark", "dark")
        self.theme.addItem("Light", "light")
        self.theme.addItem("Use Windows setting", "system")
        self.theme.setCurrentIndex(max(0, self.theme.findData(settings.theme)))
        self.theme.setMinimumWidth(190)
        self.theme.currentIndexChanged.connect(self._on_theme)
        g.add(SettingCard("palette", "App theme", "Dark, light, or follow the Windows colour mode.", self.theme))
        lay.addWidget(g)

        # --- backups ---------------------------------------------------------
        g = SettingGroup("Backups")
        self.hash_default = ToggleSwitch()
        self.hash_default.setChecked(settings.verify_with_hash)
        self.hash_default.toggled.connect(self._save)
        g.add(SettingCard("shield", "SHA-256 for new profiles",
                          "New profiles compare file contents by hash instead of size + date. "
                          "Slower, but catches silent corruption.", self.hash_default))
        self.workers = QtWidgets.QSpinBox()
        self.workers.setRange(1, 16)
        self.workers.setValue(max(1, min(16, settings.parallel_workers)))
        self.workers.setMinimumWidth(90)
        self.workers.valueChanged.connect(self._save)
        g.add(SettingCard("bolt", "Parallel copies",
                          "Files copied at once to local and network drives. Remote "
                          "(SFTP / WebDAV) destinations always copy one at a time.", self.workers))
        self.scan_pause = QtWidgets.QComboBox()
        self.scan_pause.addItem("No pause", 0)
        for n in range(1, 11):
            self.scan_pause.addItem(f"{n} second{'s' if n != 1 else ''}", n)
        self.scan_pause.setCurrentIndex(max(0, min(10, settings.scan_pause_seconds)))
        self.scan_pause.setMinimumWidth(140)
        self.scan_pause.currentIndexChanged.connect(self._save)
        g.add(SettingCard("clock", "Pause after scan",
                          "How long the 'X to copy, Y unchanged' summary stays on screen before "
                          "copying starts. Stop still works during the pause.", self.scan_pause))
        lay.addWidget(g)

        # --- automation --------------------------------------------------------
        g = SettingGroup("Automation and notifications")
        self.auto_run = ToggleSwitch()
        self.auto_run.setChecked(settings.auto_run_on_drive_plug_in)
        self.auto_run.toggled.connect(self._save)
        g.add(SettingCard("usb", "Back up when the drive is plugged in",
                          "While Anchor is open, a profile runs as soon as one of its local "
                          "destinations comes back online (e.g. you plug in its USB drive).",
                          self.auto_run))
        self.notify = ToggleSwitch()
        self.notify.setChecked(settings.notifications)
        self.notify.toggled.connect(self._save)
        g.add(SettingCard("info", "Desktop notifications",
                          "Show a Windows notification when a run finishes while Anchor is in "
                          "the background.", self.notify))
        lay.addWidget(g)

        # --- storage ----------------------------------------------------------
        g = SettingGroup("Storage")
        for icon_name, title, desc, path in (
            ("activity", "Log files", str(LOGS_DIR), LOGS_DIR),
            ("files", "Profiles", str(PROFILES_DIR), PROFILES_DIR),
            ("folder", "App data", str(APP_DIR), APP_DIR),
        ):
            b = button("Open", "folder-open")
            b.clicked.connect(lambda _=False, p=path: open_in_explorer(p, self))
            g.add(SettingCard(icon_name, title, desc, b))
        lay.addWidget(g)

        # --- about ------------------------------------------------------------
        g = SettingGroup("About")
        links = QtWidgets.QWidget()
        ll = QtWidgets.QHBoxLayout(links)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(6)
        for text, url in (("Project page", PROJECT_URL), ("GitHub", REPO_URL)):
            b = button(text, role="link")
            b.clicked.connect(lambda _=False, u=url: QtGui.QDesktopServices.openUrl(QtCore.QUrl(u)))
            ll.addWidget(b)
        g.add(SettingCard("anchor", f"Anchor {__version__}",
                          "Incremental backups for Windows 10 and 11. MIT licensed.", links))
        brand = QtWidgets.QFrame()
        brand.setObjectName("card")
        bl = QtWidgets.QHBoxLayout(brand)
        bl.setContentsMargins(16, 12, 16, 12)
        logo = QtWidgets.QLabel()
        if _BRAND.exists():
            pix = QtGui.QPixmap(str(_BRAND))
            if not pix.isNull():
                logo.setPixmap(pix.scaledToHeight(40, QtCore.Qt.SmoothTransformation))
        bl.addWidget(logo)
        bl.addStretch(1)
        bl.addWidget(label("CREATED BY HANS TANDT", "brandCredit"))
        g.add(brand)
        lay.addWidget(g)
        lay.addStretch(1)

    def _on_theme(self) -> None:
        self.settings.theme = self.theme.currentData()
        self._save()
        self.theme_changed.emit(self.settings.theme)

    def sync_theme(self, mode: str) -> None:
        self.theme.blockSignals(True)
        self.theme.setCurrentIndex(max(0, self.theme.findData(mode)))
        self.theme.blockSignals(False)

    def _save(self, *_a) -> None:
        s = self.settings
        s.verify_with_hash = self.hash_default.isChecked()
        s.parallel_workers = self.workers.value()
        s.scan_pause_seconds = int(self.scan_pause.currentData())
        s.auto_run_on_drive_plug_in = self.auto_run.isChecked()
        s.notifications = self.notify.isChecked()
        try:
            s.save()
        except OSError as e:
            QtWidgets.QMessageBox.warning(self, "Settings not saved", str(e))
            return
        self.settings_saved.emit()
