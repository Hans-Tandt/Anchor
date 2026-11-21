"""Fluent-style theme for Anchor.

One place owns every colour. Widgets that paint themselves (donut, phase
strip, status pills, navigation rail) read tokens from :func:`tokens` and
repaint when :data:`theme_manager` emits ``changed`` — so switching between
dark, light and "follow Windows" is instant and nothing keeps stale colours.

The look borrows from Microsoft's Fluent design language: layered surfaces
(window → page → card), 1 px hairline borders, 8 px corner radius, a single
accent colour (the TechEase gold) and generous spacing.
"""
from __future__ import annotations

import sys
from typing import Dict

from PySide6 import QtCore, QtGui, QtWidgets


# ---------------------------------------------------------------------------
# Palettes
# ---------------------------------------------------------------------------

DARK: Dict[str, str] = {
    "window":        "#1c1c1c",   # outermost background (nav rail sits on it)
    "page":          "#202020",   # content area
    "card":          "#2b2b2b",
    "card_hover":    "#323232",
    "card_pressed":  "#272727",
    "subtle":        "#383838",   # secondary button / inputs fill
    "subtle_hover":  "#414141",
    "border":        "#3a3a3a",
    "border_strong": "#4d4d4d",
    "divider":       "#333333",
    "text":          "#f3f3f3",
    "text_secondary": "#c5c5c5",
    "text_muted":    "#9a9a9a",
    "text_disabled": "#6b6b6b",
    "accent":        "#d4a85a",   # TechEase gold
    "accent_hover":  "#e2b96d",
    "accent_pressed": "#bf944a",
    "accent_text":   "#1a1408",
    "accent_soft":   "rgba(212, 168, 90, 0.16)",
    "ok":            "#6ccb5f",
    "ok_soft":       "rgba(108, 203, 95, 0.14)",
    "warn":          "#fcb44b",
    "warn_soft":     "rgba(252, 180, 75, 0.14)",
    "err":           "#ff6b6b",
    "err_soft":      "rgba(255, 107, 107, 0.14)",
    "info":          "#60cdff",
    "info_soft":     "rgba(96, 205, 255, 0.14)",
    "input":         "#2d2d2d",
    "track":         "#3d3d3d",
    "shadow":        "#000000",
}

LIGHT: Dict[str, str] = {
    "window":        "#eeeeee",
    "page":          "#f7f7f7",
    "card":          "#ffffff",
    "card_hover":    "#fafafa",
    "card_pressed":  "#f3f3f3",
    "subtle":        "#f3f3f3",
    "subtle_hover":  "#eaeaea",
    "border":        "#e3e3e3",
    "border_strong": "#cfcfcf",
    "divider":       "#ebebeb",
    "text":          "#1b1b1b",
    "text_secondary": "#3d3d3d",
    "text_muted":    "#6b6b6b",
    "text_disabled": "#a5a5a5",
    "accent":        "#9c6f1e",   # darker gold so it reads on white
    "accent_hover":  "#b07f27",
    "accent_pressed": "#87601a",
    "accent_text":   "#ffffff",
    "accent_soft":   "rgba(156, 111, 30, 0.12)",
    "ok":            "#0f7b0f",
    "ok_soft":       "rgba(15, 123, 15, 0.10)",
    "warn":          "#9d5d00",
    "warn_soft":     "rgba(157, 93, 0, 0.10)",
    "err":           "#c42b1c",
    "err_soft":      "rgba(196, 43, 28, 0.10)",
    "info":          "#005fb8",
    "info_soft":     "rgba(0, 95, 184, 0.10)",
    "input":         "#ffffff",
    "track":         "#e1e1e1",
    "shadow":        "#000000",
}

THEME_MODES = ("dark", "light", "system")


class ThemeManager(QtCore.QObject):
    """Holds the active palette and tells custom-painted widgets to refresh."""

    changed = QtCore.Signal()

    def __init__(self) -> None:
        super().__init__()
        self.mode = "dark"          # what the user picked
        self.is_dark = True         # what is actually on screen
        self._tokens: Dict[str, str] = dict(DARK)

    def tokens(self) -> Dict[str, str]:
        return self._tokens

    def color(self, key: str) -> QtGui.QColor:
        return parse_color(self._tokens[key])

    def _set(self, dark: bool) -> None:
        self.is_dark = dark
        self._tokens = dict(DARK if dark else LIGHT)


theme_manager = ThemeManager()


def tokens() -> Dict[str, str]:
    return theme_manager.tokens()


def color(key: str) -> QtGui.QColor:
    return theme_manager.color(key)


def parse_color(value: str) -> QtGui.QColor:
    """QColor from '#rrggbb' or 'rgba(r, g, b, a)' with a 0..1 alpha."""
    value = value.strip()
    if value.startswith("rgba"):
        inner = value[value.index("(") + 1: value.rindex(")")]
        r, g, b, a = (p.strip() for p in inner.split(","))
        c = QtGui.QColor(int(r), int(g), int(b))
        c.setAlphaF(float(a))
        return c
    return QtGui.QColor(value)


def _system_prefers_dark() -> bool:
    try:
        hints = QtGui.QGuiApplication.styleHints()
        scheme = hints.colorScheme()
        if scheme == QtCore.Qt.ColorScheme.Dark:
            return True
        if scheme == QtCore.Qt.ColorScheme.Light:
            return False
    except (AttributeError, RuntimeError):
        pass
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            ) as k:
                return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
        except OSError:
            pass
    return True


# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------

def _qss(c: Dict[str, str]) -> str:
    return f"""
    * {{
        font-family: "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif;
        font-size: 10pt;
        color: {c['text']};
        outline: 0;
    }}
    QMainWindow, QDialog {{ background: {c['page']}; }}
    QWidget#shell {{ background: {c['window']}; }}
    QWidget#page, QStackedWidget#pages, QScrollArea#pageScroll,
    QWidget#pageInner {{ background: {c['page']}; }}
    QFrame#pageFrame {{
        background: {c['page']};
        border-top-left-radius: 10px;
        border-left: 1px solid {c['border']};
        border-top: 1px solid {c['border']};
    }}
    QToolTip {{
        background: {c['card']}; color: {c['text']};
        border: 1px solid {c['border_strong']}; border-radius: 6px; padding: 6px 8px;
    }}

    /* ---- typography ---- */
    QLabel {{ background: transparent; }}
    QLabel#display  {{ font-size: 22pt; font-weight: 600; }}
    QLabel#title    {{ font-size: 16pt; font-weight: 600; }}
    QLabel#subtitle {{ font-size: 12pt; font-weight: 600; }}
    QLabel#body     {{ color: {c['text_secondary']}; }}
    QLabel#caption  {{ font-size: 8.5pt; color: {c['text_muted']}; }}
    QLabel#muted    {{ color: {c['text_muted']}; }}
    QLabel#accent   {{ color: {c['accent']}; font-weight: 600; }}
    QLabel#ok   {{ color: {c['ok']};   font-weight: 600; }}
    QLabel#warn {{ color: {c['warn']}; font-weight: 600; }}
    QLabel#err  {{ color: {c['err']};  font-weight: 600; }}
    QLabel#brandCredit {{ color: {c['accent']}; font-size: 7.5pt; letter-spacing: 1px; }}

    /* ---- surfaces ---- */
    QFrame#card {{
        background: {c['card']};
        border: 1px solid {c['border']};
        border-radius: 8px;
    }}
    QFrame#cardFlat {{
        background: {c['card']};
        border: none; border-radius: 8px;
    }}
    QFrame#divider {{ background: {c['divider']}; border: none; max-height: 1px; min-height: 1px; }}

    /* ---- buttons ---- */
    QPushButton {{
        background: {c['subtle']};
        border: 1px solid {c['border']};
        border-radius: 6px;
        padding: 6px 14px;
        min-height: 20px;
    }}
    QPushButton:hover   {{ background: {c['subtle_hover']}; }}
    QPushButton:pressed {{ background: {c['card_pressed']}; color: {c['text_secondary']}; }}
    QPushButton:disabled {{ color: {c['text_disabled']}; background: {c['subtle']}; border-color: {c['divider']}; }}
    QPushButton#primary {{
        background: {c['accent']}; color: {c['accent_text']};
        border: 1px solid {c['accent']}; font-weight: 600;
    }}
    QPushButton#primary:hover   {{ background: {c['accent_hover']}; border-color: {c['accent_hover']}; }}
    QPushButton#primary:pressed {{ background: {c['accent_pressed']}; }}
    QPushButton#primary:disabled {{
        background: {c['subtle']}; color: {c['text_disabled']}; border-color: {c['divider']};
        font-weight: normal;
    }}
    QPushButton#danger {{ color: {c['err']}; }}
    QPushButton#danger:hover {{ background: {c['err_soft']}; border-color: {c['err']}; }}
    QPushButton#danger:disabled {{ color: {c['text_disabled']}; }}
    QPushButton#warnButton {{
        background: {c['warn_soft']}; color: {c['warn']}; border: 1px solid {c['warn']};
        font-weight: 600;
    }}
    QPushButton#ghost {{ background: transparent; border: 1px solid transparent; }}
    QPushButton#ghost:hover {{ background: {c['subtle']}; }}
    QPushButton#link {{
        background: transparent; border: none; color: {c['accent']}; padding: 2px 4px;
    }}
    QPushButton#link:hover {{ text-decoration: underline; }}

    QToolButton {{
        background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 5px;
    }}
    QToolButton:hover {{ background: {c['subtle']}; }}
    QToolButton:pressed {{ background: {c['card_pressed']}; }}
    QToolButton:checked {{ background: {c['accent_soft']}; }}
    QToolButton:disabled {{ color: {c['text_disabled']}; }}

    /* ---- inputs ---- */
    QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QTimeEdit {{
        background: {c['input']};
        border: 1px solid {c['border']};
        border-bottom: 1px solid {c['border_strong']};
        border-radius: 6px;
        padding: 5px 9px;
        selection-background-color: {c['accent']};
        selection-color: {c['accent_text']};
    }}
    QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QTimeEdit:hover {{ background: {c['card_hover']}; }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
    QComboBox:focus, QSpinBox:focus, QTimeEdit:focus {{
        border-bottom: 2px solid {c['accent']};
    }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {c['text_disabled']}; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    QComboBox QAbstractItemView {{
        background: {c['card']}; border: 1px solid {c['border_strong']};
        border-radius: 6px; padding: 4px; selection-background-color: {c['accent_soft']};
        selection-color: {c['text']};
    }}
    QSpinBox::up-button, QSpinBox::down-button, QTimeEdit::up-button, QTimeEdit::down-button {{
        border: none; width: 18px; background: transparent;
    }}

    QCheckBox {{ spacing: 8px; background: transparent; }}
    QCheckBox::indicator {{
        width: 18px; height: 18px; border-radius: 4px;
        border: 1px solid {c['border_strong']}; background: {c['input']};
    }}
    QCheckBox::indicator:hover {{ border-color: {c['text_muted']}; }}
    QCheckBox::indicator:checked {{
        background: {c['accent']}; border-color: {c['accent']};
        image: url(anchorres:check.svg);
    }}
    QRadioButton {{ spacing: 8px; background: transparent; }}

    /* ---- lists / trees / tables ---- */
    QListWidget, QTreeWidget, QTableWidget, QTreeView, QListView {{
        background: {c['card']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 4px;
        alternate-background-color: {c['card_hover']};
    }}
    QListWidget::item, QTreeWidget::item {{ padding: 6px 6px; border-radius: 5px; }}
    QListWidget::item:hover, QTreeWidget::item:hover, QTableWidget::item:hover {{ background: {c['subtle']}; }}
    QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected {{
        background: {c['accent_soft']}; color: {c['text']};
    }}
    QTreeView, QTreeWidget {{
        show-decoration-selected: 1;
        selection-background-color: {c['accent_soft']};
        selection-color: {c['text']};
    }}
    QTreeView::item, QTreeWidget::item {{ border-radius: 0; padding: 5px 4px; }}
    QTreeView::branch {{ background: transparent; }}
    QTreeView::branch:selected, QTreeView::branch:hover {{ background: {c['accent_soft']}; }}
    QTreeView::branch:has-children:!has-siblings:closed,
    QTreeView::branch:closed:has-children:has-siblings {{ image: url(anchorres:chevron-right.svg); }}
    QTreeView::branch:open:has-children:!has-siblings,
    QTreeView::branch:open:has-children:has-siblings {{ image: url(anchorres:chevron-down.svg); }}
    QHeaderView::section {{
        background: {c['card']}; color: {c['text_muted']};
        border: none; border-bottom: 1px solid {c['divider']}; padding: 6px 8px;
    }}
    QTableWidget {{ gridline-color: {c['divider']}; }}

    QProgressBar {{
        background: {c['track']}; border: none; border-radius: 2px;
        max-height: 4px; min-height: 4px; text-align: center; color: transparent;
    }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 2px; }}

    QGroupBox {{
        background: {c['card']}; border: 1px solid {c['border']}; border-radius: 8px;
        margin-top: 22px; padding: 12px 10px 10px 10px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin; left: 4px; top: 0px; padding: 0 4px;
        color: {c['text_secondary']}; font-weight: 600;
    }}

    QTabWidget::pane {{ border: none; }}
    QTabBar::tab {{
        background: transparent; color: {c['text_muted']};
        padding: 8px 14px; margin-right: 2px; border: none;
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:hover {{ color: {c['text']}; }}
    QTabBar::tab:selected {{ color: {c['text']}; border-bottom: 2px solid {c['accent']}; font-weight: 600; }}

    QSplitter::handle {{ background: transparent; }}

    QMenu {{
        background: {c['card']}; border: 1px solid {c['border_strong']};
        border-radius: 8px; padding: 4px;
    }}
    QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {c['subtle']}; }}
    QMenu::separator {{ height: 1px; background: {c['divider']}; margin: 4px 6px; }}

    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {c['border_strong']}; border-radius: 3px; min-height: 30px; margin: 0 2px; }}
    QScrollBar::handle:vertical:hover {{ background: {c['text_muted']}; margin: 0; border-radius: 4px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {c['border_strong']}; border-radius: 3px; min-width: 30px; margin: 2px 0; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; background: none; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

    QMessageBox QLabel {{ color: {c['text']}; }}
    QStatusBar {{ background: {c['window']}; color: {c['text_muted']}; }}
    """


def resolve_dark(mode: str) -> bool:
    if mode == "light":
        return False
    if mode == "system":
        return _system_prefers_dark()
    return True


def apply_theme(app: QtWidgets.QApplication, theme: str = "dark") -> None:
    """Apply ``theme`` ("dark" | "light" | "system") to the whole app."""
    if theme not in THEME_MODES:
        theme = "dark"
    theme_manager.mode = theme
    theme_manager._set(resolve_dark(theme))
    c = theme_manager.tokens()

    from . import icons  # registers the :/anchor/check.svg resource
    icons.register_resources(c)

    app.setStyle("Fusion")
    qp = QtGui.QPalette()
    roles = {
        QtGui.QPalette.Window: c["page"],
        QtGui.QPalette.WindowText: c["text"],
        QtGui.QPalette.Base: c["input"],
        QtGui.QPalette.AlternateBase: c["card_hover"],
        QtGui.QPalette.Text: c["text"],
        QtGui.QPalette.Button: c["subtle"],
        QtGui.QPalette.ButtonText: c["text"],
        QtGui.QPalette.Highlight: c["accent"],
        QtGui.QPalette.HighlightedText: c["accent_text"],
        QtGui.QPalette.ToolTipBase: c["card"],
        QtGui.QPalette.ToolTipText: c["text"],
        QtGui.QPalette.PlaceholderText: c["text_muted"],
        QtGui.QPalette.Link: c["accent"],
    }
    for role, value in roles.items():
        qp.setColor(role, parse_color(value))
    qp.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.Text, parse_color(c["text_disabled"]))
    qp.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.ButtonText, parse_color(c["text_disabled"]))
    qp.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.WindowText, parse_color(c["text_disabled"]))
    app.setPalette(qp)
    app.setStyleSheet(_qss(c))

    if not hasattr(app, "_anchor_chrome_filter"):
        app._anchor_chrome_filter = _ChromeFilter(app)  # type: ignore[attr-defined]
        app.installEventFilter(app._anchor_chrome_filter)  # type: ignore[attr-defined]
    for w in app.topLevelWidgets():
        if w.isVisible():
            apply_window_chrome(w)
    theme_manager.changed.emit()


class _ChromeFilter(QtCore.QObject):
    """Applies the themed title bar to every window (dialogs, message
    boxes) the moment it is shown."""

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802 - Qt API
        if ev.type() == QtCore.QEvent.Show and isinstance(obj, QtWidgets.QWidget) and obj.isWindow():
            apply_window_chrome(obj)
        return False


def apply_window_chrome(widget: QtWidgets.QWidget) -> None:
    """Match the native Windows title bar to the theme (Win 10 1809+ / 11).

    Uses the documented DWMWA_USE_IMMERSIVE_DARK_MODE attribute. Silently a
    no-op on other platforms or older Windows builds.
    """
    if sys.platform != "win32" or not widget.isWindow():
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        value = ctypes.c_int(1 if theme_manager.is_dark else 0)
        dwm = ctypes.windll.dwmapi
        for attr in (20, 19):  # 20 on 20H1+, 19 on 1809..1909
            if dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass
