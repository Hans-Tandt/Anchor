"""App-level settings dialog (theme, parallelism, default hash mode)."""
from __future__ import annotations

import os
import subprocess
import sys

from PySide6 import QtWidgets

from ..app_config import APP_DIR, LOGS_DIR, PROFILES_DIR, AppSettings


class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent, settings: AppSettings):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(420)
        self.settings = settings

        layout = QtWidgets.QFormLayout(self)
        layout.setContentsMargins(18, 18, 18, 18); layout.setSpacing(10)

        self.theme = QtWidgets.QComboBox()
        self.theme.addItems(["Dark", "Light"])
        self.theme.setCurrentIndex(0 if settings.theme == "dark" else 1)
        layout.addRow("Theme:", self.theme)

        self.hash_default = QtWidgets.QCheckBox(
            "Default new profiles to SHA-256 verification (slower)"
        )
        self.hash_default.setChecked(settings.verify_with_hash)
        layout.addRow(self.hash_default)

        self.workers = QtWidgets.QSpinBox()
        self.workers.setRange(1, 16); self.workers.setValue(settings.parallel_workers)
        layout.addRow("Parallel workers:", self.workers)

        # Dropdown 1..10 seconds — no typing needed, the value is just clicked.
        self.scan_pause = QtWidgets.QComboBox()
        for n in range(1, 11):
            self.scan_pause.addItem(f"{n} second{'s' if n != 1 else ''}", n)
        # Default to current setting (clamped to the 1..10 range we expose).
        current = max(1, min(10, settings.scan_pause_seconds or 3))
        self.scan_pause.setCurrentIndex(current - 1)
        self.scan_pause.setToolTip(
            "How long Anchor holds the 'X to copy, Y unchanged' summary on\n"
            "screen between scan and copy phases. Cancel still works during it."
        )
        layout.addRow("Pause after scan:", self.scan_pause)

        self.auto_run = QtWidgets.QCheckBox(
            "Auto-run profile when its backup drive is plugged in"
        )
        self.auto_run.setChecked(settings.auto_run_on_drive_plug_in)
        layout.addRow(self.auto_run)

        # Quick-access buttons for the hidden APPDATA folders so users don't
        # have to type %APPDATA% into Explorer.
        layout.addRow(QtWidgets.QLabel("App data folders (hidden under %APPDATA%):"))
        folder_row = QtWidgets.QHBoxLayout()
        open_logs = QtWidgets.QPushButton("Open logs folder")
        open_logs.clicked.connect(lambda: _open_in_explorer(LOGS_DIR))
        open_profiles = QtWidgets.QPushButton("Open profiles folder")
        open_profiles.clicked.connect(lambda: _open_in_explorer(PROFILES_DIR))
        open_root = QtWidgets.QPushButton("Open app folder")
        open_root.clicked.connect(lambda: _open_in_explorer(APP_DIR))
        folder_row.addWidget(open_logs)
        folder_row.addWidget(open_profiles)
        folder_row.addWidget(open_root)
        folder_wrap = QtWidgets.QWidget(); folder_wrap.setLayout(folder_row)
        layout.addRow(folder_wrap)

        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)
        cancel = QtWidgets.QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        ok = QtWidgets.QPushButton("Save"); ok.setObjectName("primary"); ok.clicked.connect(self._accept)
        btns.addWidget(cancel); btns.addWidget(ok)
        layout.addRow(btns)

    def _accept(self) -> None:
        self.settings.theme = "dark" if self.theme.currentIndex() == 0 else "light"
        self.settings.verify_with_hash = self.hash_default.isChecked()
        self.settings.parallel_workers = self.workers.value()
        self.settings.scan_pause_seconds = int(self.scan_pause.currentData())
        self.settings.auto_run_on_drive_plug_in = self.auto_run.isChecked()
        self.settings.save()
        self.accept()


def _open_in_explorer(path) -> None:
    """Open a folder in the OS file manager. Creates it first if missing so
    users never get a 'folder does not exist' error from a fresh install."""
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
        QtWidgets.QMessageBox.warning(
            None, "Could not open folder", f"{p}\n\n{e}"
        )
