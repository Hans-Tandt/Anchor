"""Tiny built-in icon set (inline SVG, drawn for Anchor).

No icon font or third-party icon pack is needed, so the app looks the same on
every Windows build and in the frozen exe. Icons are stroked line art on a
24x24 grid, recoloured on the fly from the theme tokens.

Use :func:`bind_icon` for buttons/labels so the glyph is re-tinted whenever
the theme changes.
"""
from __future__ import annotations

import math
import tempfile
import weakref
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, Optional

from PySide6 import QtCore, QtGui, QtSvg, QtWidgets

from .theme import theme_manager, tokens


def _gear_path() -> str:
    """Generated 8-tooth gear outline (keeps the SVG table readable)."""
    pts = []
    teeth = 8
    r_out, r_in = 9.2, 7.0
    for i in range(teeth * 4):
        ang = (i / (teeth * 4)) * 2 * math.pi - math.pi / 2
        r = r_out if (i % 4) in (1, 2) else r_in
        pts.append(f"{12 + r * math.cos(ang):.2f} {12 + r * math.sin(ang):.2f}")
    return "M" + " L".join(pts) + " Z"


# Each entry is the inner SVG markup; {c} is replaced by the stroke colour.
_S = 'fill="none" stroke="{c}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"'
_F = 'fill="{c}" stroke="none"'
_SF = 'fill="{c}" stroke="{c}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"'

_ICONS: Dict[str, str] = {
    "anchor": f'<g {_S}><circle cx="12" cy="5" r="2"/><path d="M12 7v14M8 10.5h8M4.5 13a7.5 7.5 0 0 0 15 0M3 14.5l1.5-1.5 1.5 1.5M18 14.5l1.5-1.5 1.5 1.5"/></g>',
    "home": f'<path {_S} d="M3.5 10.5 12 3.5l8.5 7V19a1.5 1.5 0 0 1-1.5 1.5h-4.5v-6h-5v6H5A1.5 1.5 0 0 1 3.5 19z"/>',
    "folder": f'<path {_S} d="M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2h8.5A1.5 1.5 0 0 1 21 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z"/>',
    "folder-open": f'<path {_S} d="M3 17.5V6.5A1.5 1.5 0 0 1 4.5 5H9l2 2h7a1.5 1.5 0 0 1 1.5 1.5V10M3 17.5 5.6 11a1.5 1.5 0 0 1 1.4-1h13.4a1 1 0 0 1 .95 1.3L19.3 17.9a1.5 1.5 0 0 1-1.4 1.1H4.5A1.5 1.5 0 0 1 3 17.5z"/>',
    "drive": f'<g {_S}><rect x="3" y="12.5" width="18" height="7" rx="2"/><path d="M5 12.5 7.4 5.6A1 1 0 0 1 8.3 5h7.4a1 1 0 0 1 .9.6L19 12.5"/></g><circle {_F} cx="16.8" cy="16" r="1"/>',
    "cloud": f'<path {_S} d="M7 18.5a4.25 4.25 0 0 1-.6-8.46A6 6 0 0 1 17.9 9.2 4.65 4.65 0 0 1 17.5 18.5z"/>',
    "server": f'<g {_S}><rect x="3.5" y="4" width="17" height="7" rx="1.8"/><rect x="3.5" y="13" width="17" height="7" rx="1.8"/></g><circle {_F} cx="7.3" cy="7.5" r="1"/><circle {_F} cx="7.3" cy="16.5" r="1"/>',
    "play": f'<path {_SF} d="M8 5.6v12.8a.6.6 0 0 0 .9.5l10.2-6.4a.6.6 0 0 0 0-1L8.9 5.1a.6.6 0 0 0-.9.5z"/>',
    "stop": f'<rect {_SF} x="6.5" y="6.5" width="11" height="11" rx="2"/>',
    "pause": f'<g {_SF}><rect x="6.5" y="5.5" width="3.5" height="13" rx="1"/><rect x="14" y="5.5" width="3.5" height="13" rx="1"/></g>',
    "check": f'<path {_S} stroke-width="2" d="M5 12.5l4.5 4.5L19 7.5"/>',
    "check-circle": f'<g {_S}><circle cx="12" cy="12" r="9"/><path d="M8 12.3l2.8 2.8L16.2 9.5"/></g>',
    "warning": f'<g {_S}><path d="M10.7 4.3 2.9 18a1.5 1.5 0 0 0 1.3 2.2h15.6a1.5 1.5 0 0 0 1.3-2.2L13.3 4.3a1.5 1.5 0 0 0-2.6 0z"/><path d="M12 9.5v4.5"/></g><circle {_F} cx="12" cy="17" r="1.1"/>',
    "error": f'<g {_S}><circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/></g>',
    "info": f'<g {_S}><circle cx="12" cy="12" r="9"/><path d="M12 11v5.5"/></g><circle {_F} cx="12" cy="7.8" r="1.1"/>',
    "settings": f'<g {_S}><path d="{_gear_path()}"/><circle cx="12" cy="12" r="3"/></g>',
    "activity": f'<g {_S}><path d="M8.5 6h12M8.5 12h12M8.5 18h12"/></g><circle {_F} cx="4.5" cy="6" r="1.2"/><circle {_F} cx="4.5" cy="12" r="1.2"/><circle {_F} cx="4.5" cy="18" r="1.2"/>',
    "plus": f'<path {_S} d="M12 5v14M5 12h14"/>',
    "edit": f'<path {_S} d="M4 20h4L19.2 8.8a1.9 1.9 0 0 0 0-2.7l-1.3-1.3a1.9 1.9 0 0 0-2.7 0L4 16zM13.5 6.5l4 4"/>',
    "trash": f'<path {_S} d="M4 7h16M9.5 7V4.5h5V7M6 7l1 12.5A1.5 1.5 0 0 0 8.5 21h7a1.5 1.5 0 0 0 1.5-1.5L18 7M10 11v6M14 11v6"/>',
    "restore": f'<path {_S} d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1M3.5 4v4.5H8M12 7.5V12l3 2"/>',
    "calendar": f'<g {_S}><rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/></g>',
    "shield": f'<path {_S} d="M12 3 4.5 6v6c0 4.4 3.1 7.7 7.5 9 4.4-1.3 7.5-4.6 7.5-9V6zM8.8 12.2l2.3 2.3 4.2-4.6"/>',
    "moon": f'<path {_S} d="M20 14.6A8 8 0 1 1 9.4 4a6.5 6.5 0 0 0 10.6 10.6z"/>',
    "sun": f'<g {_S}><circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/></g>',
    "refresh": f'<path {_S} d="M19.5 11A7.6 7.6 0 0 0 5.6 7M4.5 3.5V7.5h4M4.5 13a7.6 7.6 0 0 0 13.9 4M19.5 20.5v-4h-4"/>',
    "close": f'<path {_S} d="M6 6l12 12M18 6 6 18"/>',
    "menu": f'<path {_S} d="M4 6.5h16M4 12h16M4 17.5h16"/>',
    "chevron-right": f'<path {_S} d="M9.5 6l6 6-6 6"/>',
    "chevron-down": f'<path {_S} d="M6 9.5l6 6 6-6"/>',
    "download": f'<path {_S} d="M12 4v11M7 10.5l5 5 5-5M5 20h14"/>',
    "copy": f'<g {_S}><rect x="8.5" y="8.5" width="12" height="12" rx="2"/><path d="M15.5 8.5V5A1.5 1.5 0 0 0 14 3.5H5A1.5 1.5 0 0 0 3.5 5v9A1.5 1.5 0 0 0 5 15.5h3.5"/></g>',
    "search": f'<g {_S}><circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5 20.5 20.5"/></g>',
    "clock": f'<g {_S}><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.2 2"/></g>',
    "files": f'<path {_S} d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M9 13h6M9 17h4"/>',
    "database": f'<g {_S}><ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.66 3.58 3 8 3s8-1.34 8-3V6M4 12c0 1.66 3.58 3 8 3s8-1.34 8-3"/></g>',
    "layers": f'<path {_S} d="M12 3.5 3 8l9 4.5L21 8zM3 12.5l9 4.5 9-4.5M3 16.5l9 4.5 9-4.5"/>',
    "bolt": f'<path {_S} d="M13 3 5 13.5h6L10.5 21 19 10.5h-6z"/>',
    "eye": f'<g {_S}><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/></g>',
    "palette": f'<path {_S} d="M12 3a9 9 0 0 0 0 18c1.1 0 1.7-.8 1.7-1.7 0-.5-.2-.9-.5-1.2-.3-.3-.5-.7-.5-1.2 0-.9.8-1.7 1.7-1.7H16a5 5 0 0 0 5-5C21 6.6 17 3 12 3z"/><circle {_F} cx="7.5" cy="11.5" r="1.2"/><circle {_F} cx="10" cy="7.5" r="1.2"/><circle {_F} cx="14.5" cy="7.5" r="1.2"/>',
    "github": f'<path {_S} d="M9 19c-4.3 1.4-4.3-2.5-6-3m12 5v-3.5c0-1 .1-1.4-.5-2 2.8-.3 5.5-1.4 5.5-6a4.6 4.6 0 0 0-1.3-3.2 4.2 4.2 0 0 0-.1-3.2s-1.1-.3-3.5 1.3a12.3 12.3 0 0 0-6.2 0C6.5 2.8 5.4 3.1 5.4 3.1a4.2 4.2 0 0 0-.1 3.2A4.6 4.6 0 0 0 4 9.5c0 4.6 2.7 5.7 5.5 6-.6.6-.6 1.2-.5 2V21"/>',
    "more": f'<circle {_F} cx="5.5" cy="12" r="1.6"/><circle {_F} cx="12" cy="12" r="1.6"/><circle {_F} cx="18.5" cy="12" r="1.6"/>',
    "usb": f'<g {_S}><rect x="7" y="9" width="10" height="12" rx="1.5"/><path d="M9 9V3.5h6V9M10.5 6h.01M13.5 6h.01"/></g>',
}


def names() -> list:
    return sorted(_ICONS)


def svg_markup(name: str, color_value: str) -> str:
    inner = _ICONS.get(name) or _ICONS["info"]
    # QSvg doesn't understand rgba(); fall back to the hex form.
    col = QtGui.QColor(color_value) if not color_value.startswith("rgba") else None
    hex_col = col.name() if col is not None and col.isValid() else color_value
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">'
        + inner.replace("{c}", hex_col)
        + "</svg>"
    )


@lru_cache(maxsize=512)
def _pixmap_cached(name: str, color_value: str, size: int, dpr: float) -> QtGui.QPixmap:
    renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(svg_markup(name, color_value).encode("utf-8")))
    px = QtGui.QPixmap(int(size * dpr), int(size * dpr))
    px.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(px)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    renderer.render(p)
    p.end()
    px.setDevicePixelRatio(dpr)
    return px


def _dpr() -> float:
    app = QtWidgets.QApplication.instance()
    screen = app.primaryScreen() if app else None
    return float(screen.devicePixelRatio()) if screen else 1.0


def pixmap(name: str, size: int = 16, color_key: str = "text", color_value: Optional[str] = None) -> QtGui.QPixmap:
    value = color_value or tokens().get(color_key, color_key)
    return _pixmap_cached(name, value, size, _dpr())


def icon(name: str, color_key: str = "text", color_value: Optional[str] = None) -> QtGui.QIcon:
    value = color_value or tokens().get(color_key, color_key)
    ic = QtGui.QIcon()
    for s in (16, 20, 24, 32):
        ic.addPixmap(_pixmap_cached(name, value, s, _dpr()), QtGui.QIcon.Normal)
        ic.addPixmap(_pixmap_cached(name, tokens()["text_disabled"], s, _dpr()), QtGui.QIcon.Disabled)
    return ic


# --- theme binding -----------------------------------------------------------

_bound: "weakref.WeakKeyDictionary[QtCore.QObject, Callable[[], None]]" = weakref.WeakKeyDictionary()


def _refresh_all() -> None:
    for obj, fn in list(_bound.items()):
        try:
            fn()
        except RuntimeError:  # underlying C++ object already deleted
            pass


theme_manager.changed.connect(_refresh_all)


def bind_icon(widget: QtWidgets.QWidget, name: str, color_key: str = "text", size: int = 16) -> None:
    """Set an icon on a button/label and keep it in sync with the theme."""
    def apply() -> None:
        if isinstance(widget, QtWidgets.QLabel):
            widget.setPixmap(pixmap(name, size, color_key))
        else:
            widget.setIcon(icon(name, color_key))
            widget.setIconSize(QtCore.QSize(size, size))
    _bound[widget] = apply
    apply()


# --- QSS resources -----------------------------------------------------------

_RES_DIR = Path(tempfile.gettempdir()) / "anchor-ui"


def register_resources(c: Dict[str, str]) -> None:
    """QSS can only reference images by path. Write the checkbox tick for
    the current theme to a per-user temp file and alias it via a search path."""
    try:
        _RES_DIR.mkdir(parents=True, exist_ok=True)
        (_RES_DIR / "check.svg").write_text(
            svg_markup("check", c["accent_text"]).replace('stroke-width="2"', 'stroke-width="2.6"'),
            encoding="utf-8",
        )
        for name in ("chevron-right", "chevron-down"):
            (_RES_DIR / f"{name}.svg").write_text(svg_markup(name, c["text_muted"]), encoding="utf-8")
        QtCore.QDir.setSearchPaths("anchorres", [str(_RES_DIR)])
    except OSError:
        pass
