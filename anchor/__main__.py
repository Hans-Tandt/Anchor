"""Run with `python -m anchor` to launch the GUI."""
from __future__ import annotations

import sys

from .app_config import AppSettings, ensure_dirs
from .logging_setup import setup_logging


def main() -> int:
    ensure_dirs()
    setup_logging()
    settings = AppSettings.load()

    from PySide6 import QtWidgets, QtGui
    from .gui import MainWindow, apply_theme

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Anchor")
    app.setOrganizationName("Anchor")
    apply_theme(app, settings.theme)

    win = MainWindow(settings)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
