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

    if len(sys.argv) > 1 and sys.argv[1] in ("--version", "-V"):
        from anchor import __version__
        print(f"Anchor {__version__}")
        return 0

    settings = AppSettings.load()
    _install_excepthook()
    _set_app_user_model_id()

    from PySide6 import QtGui, QtWidgets
    from anchor.gui import MainWindow, apply_theme
    from anchor.gui.main_window import app_icon

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Anchor")
    app.setApplicationDisplayName("Anchor")
    app.setOrganizationName("Anchor")
    app.setWindowIcon(app_icon())
    apply_theme(app, settings.theme)

    # "Use Windows setting": follow the OS when the user flips dark/light.
    def _on_scheme_changed(*_a) -> None:
        if settings.theme == "system":
            apply_theme(app, "system")
    try:
        QtGui.QGuiApplication.styleHints().colorSchemeChanged.connect(_on_scheme_changed)
    except AttributeError:  # Qt < 6.5
        pass

    win = MainWindow(settings)
    win.show()
    return app.exec()


def _install_excepthook() -> None:
    """Log unhandled GUI exceptions instead of losing them (the windowed
    exe and pythonw have no console to print a traceback to)."""
    import logging

    log = logging.getLogger("anchor.crash")
    previous = sys.excepthook

    def hook(exc_type, exc, tb):
        log.critical("Unhandled exception", exc_info=(exc_type, exc, tb))
        if previous is not None and previous is not hook:
            previous(exc_type, exc, tb)

    sys.excepthook = hook


def _set_app_user_model_id() -> None:
    """Give the process its own taskbar identity so Windows shows Anchor's
    icon (not python.exe's) and groups its windows together."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("HansTandt.Anchor")
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
