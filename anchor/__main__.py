"""Anchor entry point.

Normally: `python -m anchor` (or double-click `run.bat`, or launch the
built `Anchor.exe`) opens the GUI.

Scheduled backups invoke `Anchor.exe --cli --profile <id> --silent`, which
dispatches to `anchor.cli` and never opens a window. In a source install
the equivalent is `python -m anchor.cli --profile <id> --silent` and this
dispatcher is skipped entirely.
"""
from __future__ import annotations

import sys


def main() -> int:
    # Absolute imports (not `from .foo`) because PyInstaller runs this file
    # as an entry-point script with no `__package__` set — relative imports
    # would raise ImportError inside the frozen exe. Absolute imports work
    # in both the frozen build and the `python -m anchor` source path.
    from anchor.app_config import AppSettings, ensure_dirs
    from anchor.logging_setup import setup_logging

    ensure_dirs()
    setup_logging()

    # CLI dispatcher: when Anchor is invoked with --cli, forward the
    # remaining args to anchor.cli and skip the GUI entirely. Kept here
    # (not in cli.py) so it works for both `python -m anchor --cli ...`
    # and the frozen `Anchor.exe --cli ...` invoked by scheduled tasks.
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        from anchor.cli import main as cli_main
        return cli_main(sys.argv[2:])

    settings = AppSettings.load()

    from PySide6 import QtWidgets
    from anchor.gui import MainWindow, apply_theme

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Anchor")
    app.setOrganizationName("Anchor")
    apply_theme(app, settings.theme)

    win = MainWindow(settings)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
