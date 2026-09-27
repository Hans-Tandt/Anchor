"""Dark / Light theme via Qt stylesheets.

Designed for a modern flat look with rounded corners, soft shadows, and
generous spacing. Compatible with PySide6's default Fusion style.
"""
from __future__ import annotations

from PySide6 import QtWidgets, QtGui


# Palette tuned to the TechEase brand: gold-on-black.
# The accent (#d4a85a) is sampled from the logo's gold gradient mid-tone.
DARK = {
    "bg":           "#0e0f12",
    "panel":        "#16181d",
    "panel_alt":    "#1f232b",
    "border":       "#3a3220",  # warm dark brown — subtle hint of gold
    "text":         "#ece6d8",  # soft warm white
    "text_muted":   "#8a8578",
    "accent":       "#d4a85a",  # TechEase gold
    "accent_hover": "#e9c275",  # brighter gold for hover
    "accent_text":  "#15110a",  # dark text on gold buttons (contrast)
    "ok":           "#5fb88a",
    "warn":         "#e9a23b",
    "err":          "#e35d6a",
    "input_bg":     "#0a0b0e",
}

LIGHT = {
    "bg":           "#f7f3e8",  # warm ivory
    "panel":        "#fffdf6",
    "panel_alt":    "#efeadb",
    "border":       "#d8cea8",
    "text":         "#211b0f",
    "text_muted":   "#6a624d",
    "accent":       "#a87a26",  # darker gold reads on light bg
    "accent_hover": "#c89640",
    "accent_text":  "#ffffff",
    "ok":           "#1f9b6e",
    "warn":         "#c8821b",
    "err":          "#c0392b",
    "input_bg":     "#fffdf6",
}


def _qss(c: dict) -> str:
    return f"""
    * {{
        color: {c['text']};
        font-family: "Segoe UI", "SF Pro Text", system-ui, sans-serif;
        font-size: 10pt;
    }}
    QMainWindow, QDialog, QWidget#central {{
        background: {c['bg']};
    }}
    QFrame#card {{
        background: {c['panel']};
        border: 1px solid {c['border']};
        border-radius: 10px;
    }}
    QFrame#sidebar {{
        background: {c['panel']};
        border-right: 1px solid {c['border']};
    }}
    QFrame#brandFooter {{
        background: {c['bg']};
        border: 1px solid {c['accent']};
        border-radius: 10px;
    }}
    QLabel#h1 {{ font-size: 18pt; font-weight: 600; color: {c['accent']}; }}
    QLabel#h2 {{ font-size: 13pt; font-weight: 600; }}
    QLabel#brandCredit {{ color: {c['accent']}; font-size: 8pt; letter-spacing: 1px; }}
    QLabel#muted {{ color: {c['text_muted']}; }}
    QLabel#ok {{ color: {c['ok']}; font-weight: 600; }}
    QLabel#warn {{ color: {c['warn']}; font-weight: 600; }}
    QLabel#err {{ color: {c['err']}; font-weight: 600; }}

    QPushButton {{
        background: {c['panel_alt']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: 7px;
        padding: 7px 14px;
    }}
    QPushButton:hover {{ background: {c['border']}; }}
    QPushButton:disabled {{ color: {c['text_muted']}; }}
    QPushButton#primary {{
        background: {c['accent']}; color: {c['accent_text']};
        border: none; font-weight: 600;
    }}
    QPushButton#primary:hover {{ background: {c['accent_hover']}; }}
    QPushButton#danger {{
        background: transparent; color: {c['err']};
        border: 1px solid {c['err']};
    }}
    QPushButton#danger:hover {{ background: {c['err']}; color: {c['accent_text']}; }}

    QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {{
        background: {c['input_bg']};
        border: 1px solid {c['border']};
        border-radius: 6px;
        padding: 5px 8px;
        selection-background-color: {c['accent']};
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
    QComboBox:focus, QSpinBox:focus {{ border: 1px solid {c['accent']}; }}

    QListWidget, QTreeWidget, QTableWidget {{
        background: {c['panel']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 2px;
        outline: 0;
    }}
    QListWidget::item, QTreeWidget::item {{ padding: 8px 6px; border-radius: 6px; }}
    QListWidget::item:selected, QTreeWidget::item:selected {{
        background: {c['accent']}; color: {c['accent_text']};
    }}
    QListWidget::item:hover, QTreeWidget::item:hover {{
        background: {c['panel_alt']};
    }}

    QProgressBar {{
        background: {c['panel_alt']};
        border: 1px solid {c['border']};
        border-radius: 6px;
        height: 14px;
        text-align: center;
    }}
    QProgressBar::chunk {{
        background: {c['accent']};
        border-radius: 5px;
    }}

    QCheckBox {{ spacing: 8px; }}
    QGroupBox {{
        border: 1px solid {c['border']};
        border-radius: 8px;
        margin-top: 14px;
        padding-top: 8px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 6px;
        color: {c['text_muted']};
    }}

    QStatusBar {{ background: {c['panel']}; border-top: 1px solid {c['border']}; }}
    QMenuBar {{ background: {c['panel']}; }}
    QMenuBar::item:selected, QMenu::item:selected {{ background: {c['accent']}; color: {c['accent_text']}; }}
    QMenu {{ background: {c['panel']}; border: 1px solid {c['border']}; }}

    QScrollBar:vertical {{
        background: transparent; width: 10px; margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {c['border']}; border-radius: 5px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {c['text_muted']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        background: none; height: 0;
    }}
    """


def apply_theme(app: QtWidgets.QApplication, theme: str = "dark") -> None:
    palette = DARK if theme == "dark" else LIGHT
    app.setStyle("Fusion")
    app.setStyleSheet(_qss(palette))

    # Also apply a QPalette so native dialogs (file picker, message box) match.
    qp = QtGui.QPalette()
    qp.setColor(QtGui.QPalette.Window, QtGui.QColor(palette["bg"]))
    qp.setColor(QtGui.QPalette.WindowText, QtGui.QColor(palette["text"]))
    qp.setColor(QtGui.QPalette.Base, QtGui.QColor(palette["input_bg"]))
    qp.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(palette["panel_alt"]))
    qp.setColor(QtGui.QPalette.Text, QtGui.QColor(palette["text"]))
    qp.setColor(QtGui.QPalette.Button, QtGui.QColor(palette["panel_alt"]))
    qp.setColor(QtGui.QPalette.ButtonText, QtGui.QColor(palette["text"]))
    qp.setColor(QtGui.QPalette.Highlight, QtGui.QColor(palette["accent"]))
    qp.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor(palette["accent_text"]))
    qp.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor(palette["panel"]))
    qp.setColor(QtGui.QPalette.ToolTipText, QtGui.QColor(palette["text"]))
    qp.setColor(QtGui.QPalette.PlaceholderText, QtGui.QColor(palette["text_muted"]))
    app.setPalette(qp)
