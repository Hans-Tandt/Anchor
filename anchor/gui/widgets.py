"""Small Fluent-style widget kit used across Anchor's GUI.

Written from scratch on plain PySide6 so the app keeps its MIT licence and has
no extra runtime dependency. Inspired by the Fluent design language (WinUI 3)
— navigation rail, cards, toggle switches, info bars / toasts.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from . import icons
from .theme import color, theme_manager


# ---------------------------------------------------------------------------
# Basic building blocks
# ---------------------------------------------------------------------------

def label(text: str = "", role: str = "", parent=None, wrap: bool = False) -> QtWidgets.QLabel:
    lbl = QtWidgets.QLabel(text, parent)
    if role:
        lbl.setObjectName(role)
    if wrap:
        lbl.setWordWrap(True)
    return lbl


def hline() -> QtWidgets.QFrame:
    f = QtWidgets.QFrame()
    f.setObjectName("divider")
    f.setFixedHeight(1)
    return f


def button(text: str = "", icon_name: str = "", role: str = "", tooltip: str = "",
           icon_color: Optional[str] = None) -> QtWidgets.QPushButton:
    b = QtWidgets.QPushButton(text)
    if role:
        b.setObjectName(role)
    if icon_name:
        key = icon_color or ("accent_text" if role == "primary" else
                             "err" if role == "danger" else
                             "warn" if role == "warnButton" else "text")
        icons.bind_icon(b, icon_name, key)
    if tooltip:
        b.setToolTip(tooltip)
    b.setCursor(QtCore.Qt.PointingHandCursor)
    return b


def tool_button(icon_name: str, tooltip: str = "", color_key: str = "text", size: int = 16) -> QtWidgets.QToolButton:
    b = QtWidgets.QToolButton()
    icons.bind_icon(b, icon_name, color_key, size)
    b.setToolTip(tooltip)
    b.setCursor(QtCore.Qt.PointingHandCursor)
    b.setAutoRaise(True)
    return b


def icon_label(icon_name: str, color_key: str = "text", size: int = 16) -> QtWidgets.QLabel:
    lbl = QtWidgets.QLabel()
    lbl.setFixedSize(size + 2, size + 2)
    lbl.setAlignment(QtCore.Qt.AlignCenter)
    icons.bind_icon(lbl, icon_name, color_key, size)
    return lbl


class Card(QtWidgets.QFrame):
    """Rounded surface with a hairline border."""

    def __init__(self, parent=None, padding: int = 16, spacing: int = 10, flat: bool = False):
        super().__init__(parent)
        self.setObjectName("cardFlat" if flat else "card")
        self.lay = QtWidgets.QVBoxLayout(self)
        self.lay.setContentsMargins(padding, padding, padding, padding)
        self.lay.setSpacing(spacing)


# ---------------------------------------------------------------------------
# Toggle switch
# ---------------------------------------------------------------------------

class ToggleSwitch(QtWidgets.QAbstractButton):
    """Fluent toggle switch with an animated knob. API-compatible with
    QCheckBox for the bits Anchor uses (isChecked / setChecked / toggled)."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setText(text)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self._pos = 0.0
        self._anim = QtCore.QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)
        theme_manager.changed.connect(self.update)

    def _get_knob(self) -> float:
        return self._pos

    def _set_knob(self, v: float) -> None:
        self._pos = v
        self.update()

    knob = QtCore.Property(float, _get_knob, _set_knob)

    def setChecked(self, on: bool) -> None:  # noqa: N802 - Qt API
        super().setChecked(on)
        self._anim.stop()
        self._pos = 1.0 if on else 0.0
        self.update()

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def sizeHint(self) -> QtCore.QSize:
        fm = self.fontMetrics()
        w = 40 + (10 + fm.horizontalAdvance(self.text()) if self.text() else 0)
        return QtCore.QSize(w, max(22, fm.height() + 4))

    def hitButton(self, pos: QtCore.QPoint) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, _ev) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        h = 20
        track = QtCore.QRectF(1, (self.height() - h) / 2, 40, h)
        enabled = self.isEnabled()
        on_col = color("accent") if enabled else color("text_disabled")
        if self._pos > 0.5:
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(on_col)
        else:
            p.setPen(QtGui.QPen(color("text_muted") if enabled else color("text_disabled"), 1))
            p.setBrush(QtCore.Qt.NoBrush)
        p.drawRoundedRect(track.adjusted(0.5, 0.5, -0.5, -0.5), h / 2, h / 2)
        d = 12 if not self.underMouse() else 14
        x = track.left() + 4 + self._pos * (track.width() - 8 - d) + (12 - d) / 2 + (d - 12) / 2
        knob = QtCore.QRectF(x, track.center().y() - d / 2, d, d)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(color("accent_text") if self._pos > 0.5 else (color("text_muted") if enabled else color("text_disabled")))
        p.drawEllipse(knob)
        if self.text():
            p.setPen(color("text") if enabled else color("text_disabled"))
            p.drawText(QtCore.QRectF(track.right() + 10, 0, self.width(), self.height()),
                       QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, self.text())
        p.end()

    def enterEvent(self, ev) -> None:
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev) -> None:
        self.update()
        super().leaveEvent(ev)


# ---------------------------------------------------------------------------
# Status pill
# ---------------------------------------------------------------------------

_PILL = {
    "ok":      ("ok", "ok_soft", "Healthy"),
    "warning": ("warn", "warn_soft", "Warnings"),
    "error":   ("err", "err_soft", "Failed"),
    "never":   ("text_muted", "subtle", "Never run"),
    "running": ("accent", "accent_soft", "Running"),
    "info":    ("info", "info_soft", ""),
}


class StatusPill(QtWidgets.QWidget):
    """Rounded badge: coloured dot + short text."""

    def __init__(self, status: str = "never", text: str = "", parent=None):
        super().__init__(parent)
        self._status = status
        self._text = text
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        theme_manager.changed.connect(self.update)

    def set_status(self, status: str, text: str = "") -> None:
        self._status = status
        self._text = text
        self.updateGeometry()
        self.update()

    def text(self) -> str:
        return self._text or _PILL.get(self._status, _PILL["never"])[2]

    def sizeHint(self) -> QtCore.QSize:
        f = QtGui.QFont(self.font())
        f.setPointSizeF(8.5)
        f.setWeight(QtGui.QFont.DemiBold)
        return QtCore.QSize(QtGui.QFontMetrics(f).horizontalAdvance(self.text()) + 30, 22)

    def paintEvent(self, _ev) -> None:
        fg_key, bg_key, _ = _PILL.get(self._status, _PILL["never"])
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(color(bg_key))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setBrush(color(fg_key))
        p.drawEllipse(QtCore.QPointF(12, r.center().y()), 3.5, 3.5)
        f = QtGui.QFont(self.font())
        f.setPointSizeF(8.5)
        f.setWeight(QtGui.QFont.DemiBold)
        p.setFont(f)
        p.setPen(color(fg_key))
        p.drawText(r.adjusted(21, 0, -6, 0), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, self.text())
        p.end()


# ---------------------------------------------------------------------------
# Stat tile
# ---------------------------------------------------------------------------

class StatTile(Card):
    """Small dashboard tile: icon + caption on top, big value, sub-caption."""

    def __init__(self, icon_name: str, caption: str, parent=None):
        super().__init__(parent, padding=14, spacing=4)
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(8)
        self._icon_wrap = QtWidgets.QLabel()
        self._icon_wrap.setFixedSize(28, 28)
        self._icon_wrap.setAlignment(QtCore.Qt.AlignCenter)
        icons.bind_icon(self._icon_wrap, icon_name, "accent", 16)
        self._icon_name = icon_name
        top.addWidget(self._icon_wrap)
        top.addWidget(label(caption, "caption"))
        top.addStretch(1)
        self.lay.addLayout(top)
        self.value = label("—", "subtitle")
        self.value.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.lay.addWidget(self.value)
        self.sub = label("", "caption")
        self.sub.setWordWrap(True)
        self.lay.addWidget(self.sub)
        theme_manager.changed.connect(self._restyle)
        self._restyle()

    def _restyle(self) -> None:
        c = color("accent_soft")
        self._icon_wrap.setStyleSheet(
            f"background: rgba({c.red()},{c.green()},{c.blue()},{c.alphaF():.2f}); border-radius: 6px;"
        )

    def set(self, value: str, sub: str = "") -> None:
        self.value.setText(value)
        self.sub.setText(sub)


# ---------------------------------------------------------------------------
# Settings cards
# ---------------------------------------------------------------------------

class SettingCard(QtWidgets.QFrame):
    """Fluent "setting card": icon, title, description, control on the right."""

    def __init__(self, icon_name: str, title: str, description: str = "",
                 control: Optional[QtWidgets.QWidget] = None, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumHeight(68)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(16)
        lay.addWidget(icon_label(icon_name, "text", 20))
        text = QtWidgets.QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(label(title))
        if description:
            d = label(description, "caption", wrap=True)
            text.addWidget(d)
        lay.addLayout(text, 1)
        if control is not None:
            lay.addWidget(control, 0, QtCore.Qt.AlignVCenter)
        self.control = control


class SettingGroup(QtWidgets.QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.lay = QtWidgets.QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(4)
        head = label(title)
        head.setStyleSheet("font-weight: 600; padding: 0 0 6px 2px;")
        self.lay.addWidget(head)

    def add(self, card: QtWidgets.QWidget) -> QtWidgets.QWidget:
        self.lay.addWidget(card)
        return card


# ---------------------------------------------------------------------------
# Smooth progress bar
# ---------------------------------------------------------------------------

class SmoothProgressBar(QtWidgets.QProgressBar):
    """Thin Fluent progress bar whose value glides instead of jumping."""

    def __init__(self, parent=None, height: int = 4):
        super().__init__(parent)
        self.setRange(0, 1000)
        self.setTextVisible(False)
        self.setFixedHeight(height)
        self._target = 0.0
        self._anim = QtCore.QPropertyAnimation(self, b"value", self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)

    def set_fraction(self, f: float, animate: bool = True) -> None:
        v = int(max(0.0, min(1.0, f)) * 1000)
        if v == self._target:
            return
        self._target = v
        self._anim.stop()
        if animate and self.isVisible():
            self._anim.setStartValue(self.value())
            self._anim.setEndValue(v)
            self._anim.start()
        else:
            self.setValue(v)

    def set_chunk_color(self, key: str) -> None:
        c = color(key).name()
        t = color("track").name()
        r = self.height() // 2
        self.setStyleSheet(
            f"QProgressBar {{ background: {t}; border: none; border-radius: {r}px;"
            f" max-height: {self.height()}px; min-height: {self.height()}px; }}"
            f"QProgressBar::chunk {{ background: {c}; border-radius: {r}px; }}"
        )


# ---------------------------------------------------------------------------
# Navigation rail
# ---------------------------------------------------------------------------

class _NavItem(QtWidgets.QAbstractButton):
    def __init__(self, key: str, icon_name: str, text: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.icon_name = icon_name
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFixedHeight(40)
        self.setToolTip(text)
        self.badge = 0
        self.expanded = True
        theme_manager.changed.connect(self.update)

    def paintEvent(self, _ev) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(4, 2, -4, -2)
        if self.isChecked() or self.underMouse():
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(color("subtle_hover") if self.isChecked() else color("subtle"))
            p.drawRoundedRect(r, 6, 6)
        icon_col = "accent" if self.isChecked() else "text"
        px = icons.pixmap(self.icon_name, 18, icon_col)
        p.drawPixmap(QtCore.QPointF(r.left() + 12, r.center().y() - 9), px)
        if self.expanded:
            f = QtGui.QFont(self.font())
            if self.isChecked():
                f.setWeight(QtGui.QFont.DemiBold)
            p.setFont(f)
            p.setPen(color("text"))
            p.drawText(r.adjusted(42, 0, -8, 0), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, self.text())
        if self.badge:
            bx = r.right() - 22 if self.expanded else r.left() + 24
            br = QtCore.QRectF(bx, r.center().y() - 8 if self.expanded else r.top() + 2, 18, 16)
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(color("err"))
            p.drawRoundedRect(br, 8, 8)
            f = QtGui.QFont(self.font())
            f.setPointSizeF(7.5)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QtGui.QColor("#ffffff"))
            p.drawText(br, QtCore.Qt.AlignCenter, str(min(self.badge, 99)))
        p.end()

    def enterEvent(self, ev) -> None:
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev) -> None:
        self.update()
        super().leaveEvent(ev)


class NavigationRail(QtWidgets.QWidget):
    """Collapsible left navigation (Fluent NavigationView, compact mode)."""

    current_changed = QtCore.Signal(str)

    EXPANDED_W = 220
    COMPACT_W = 56

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("navRail")
        self._items: Dict[str, _NavItem] = {}
        self._group = QtWidgets.QButtonGroup(self)
        self._group.setExclusive(True)
        self._expanded = True

        self.lay = QtWidgets.QVBoxLayout(self)
        self.lay.setContentsMargins(4, 8, 4, 8)
        self.lay.setSpacing(2)

        head = QtWidgets.QHBoxLayout()
        head.setContentsMargins(4, 0, 4, 6)
        self.menu_btn = tool_button("menu", "Collapse / expand navigation")
        self.menu_btn.setFixedSize(40, 36)
        self.menu_btn.clicked.connect(self.toggle)
        head.addWidget(self.menu_btn)
        self.app_logo = icon_label("anchor", "accent", 18)
        head.addWidget(self.app_logo)
        self.app_title = label("Anchor")
        self.app_title.setStyleSheet("font-weight: 600; font-size: 11pt; padding-left: 4px;")
        head.addWidget(self.app_title)
        head.addStretch(1)
        self.lay.addLayout(head)

        self._top = QtWidgets.QVBoxLayout()
        self._top.setSpacing(2)
        self.lay.addLayout(self._top)
        self.lay.addStretch(1)
        self._footer_slot = QtWidgets.QVBoxLayout()
        self.lay.addLayout(self._footer_slot)
        self._bottom = QtWidgets.QVBoxLayout()
        self._bottom.setSpacing(2)
        self.lay.addLayout(self._bottom)

        # Sliding accent indicator next to the selected item.
        self._indicator = QtWidgets.QFrame(self)
        self._indicator.setFixedSize(3, 16)
        self._ind_anim = QtCore.QPropertyAnimation(self._indicator, b"pos", self)
        self._ind_anim.setDuration(200)
        self._ind_anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        theme_manager.changed.connect(self._restyle)
        self._restyle()

        self._width_anim = QtCore.QPropertyAnimation(self, b"minimumWidth", self)
        self._width_anim.setDuration(180)
        self._width_anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._width_anim.valueChanged.connect(lambda v: self.setMaximumWidth(int(v)))
        self.setFixedWidth(self.EXPANDED_W)

    def _restyle(self) -> None:
        self._indicator.setStyleSheet(f"background: {color('accent').name()}; border-radius: 1px;")

    def add_item(self, key: str, icon_name: str, text: str, bottom: bool = False) -> _NavItem:
        it = _NavItem(key, icon_name, text, self)
        it.clicked.connect(lambda _=False, k=key: self.set_current(k))
        self._group.addButton(it)
        (self._bottom if bottom else self._top).addWidget(it)
        self._items[key] = it
        return it

    def add_action(self, icon_name: str, text: str, callback: Callable[[], None]) -> _NavItem:
        """Non-selectable entry (e.g. theme toggle) in the bottom section."""
        it = _NavItem("", icon_name, text, self)
        it.setCheckable(False)
        it.clicked.connect(callback)
        self._bottom.addWidget(it)
        self._items[f"__action_{text}"] = it
        return it

    def set_footer(self, w: QtWidgets.QWidget) -> None:
        self._footer_slot.addWidget(w)
        self._footer = w
        w.setVisible(self._expanded)

    def set_badge(self, key: str, n: int) -> None:
        if key in self._items:
            self._items[key].badge = n
            self._items[key].update()

    def set_current(self, key: str, emit: bool = True) -> None:
        it = self._items.get(key)
        if not it:
            return
        it.setChecked(True)
        QtCore.QTimer.singleShot(0, lambda: self._move_indicator(it))
        if emit:
            self.current_changed.emit(key)

    def current(self) -> str:
        b = self._group.checkedButton()
        return b.key if isinstance(b, _NavItem) else ""

    def _move_indicator(self, it: _NavItem, animate: bool = True) -> None:
        pos = it.mapTo(self, QtCore.QPoint(4, (it.height() - self._indicator.height()) // 2))
        self._indicator.raise_()
        self._indicator.show()
        if animate and self._indicator.pos() != QtCore.QPoint(0, 0):
            self._ind_anim.stop()
            self._ind_anim.setStartValue(self._indicator.pos())
            self._ind_anim.setEndValue(pos)
            self._ind_anim.start()
        else:
            self._indicator.move(pos)

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        b = self._group.checkedButton()
        if isinstance(b, _NavItem):
            QtCore.QTimer.singleShot(0, lambda: self._move_indicator(b, animate=False))

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, on: bool, animate: bool = True) -> None:
        self._expanded = on
        for it in self._items.values():
            it.expanded = on
            it.update()
        self.app_title.setVisible(on)
        self.app_logo.setVisible(on)
        if getattr(self, "_footer", None) is not None:
            self._footer.setVisible(on)
        target = self.EXPANDED_W if on else self.COMPACT_W
        if animate:
            self._width_anim.stop()
            self._width_anim.setStartValue(self.width())
            self._width_anim.setEndValue(target)
            self._width_anim.start()
        else:
            self.setFixedWidth(target)

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)


# ---------------------------------------------------------------------------
# Toasts (Fluent InfoBar)
# ---------------------------------------------------------------------------

_TOAST_KIND = {
    "success": ("check-circle", "ok", "ok_soft"),
    "warning": ("warning", "warn", "warn_soft"),
    "error":   ("error", "err", "err_soft"),
    "info":    ("info", "info", "info_soft"),
}


class Toast(QtWidgets.QFrame):
    closed = QtCore.Signal(object)

    def __init__(self, kind: str, title: str, text: str, parent: QtWidgets.QWidget,
                 duration_ms: int = 4500, action: Optional[tuple] = None):
        super().__init__(parent)
        icon_name, fg, _bg = _TOAST_KIND.get(kind, _TOAST_KIND["info"])
        self.setObjectName("toast")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self._fg = fg
        self._shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(24)
        self._shadow.setOffset(0, 4)
        self.setGraphicsEffect(self._shadow)
        self._restyle()
        theme_manager.changed.connect(self._restyle)

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 8, 10)
        lay.setSpacing(12)
        lay.addWidget(icon_label(icon_name, fg, 18), 0, QtCore.Qt.AlignTop)
        col = QtWidgets.QVBoxLayout()
        col.setSpacing(2)
        t = label(title)
        t.setStyleSheet("font-weight: 600;")
        col.addWidget(t)
        if text:
            body = label(text, "body", wrap=True)
            body.setMaximumWidth(320)
            col.addWidget(body)
        if action:
            act_text, act_cb = action
            ab = button(act_text, role="link")
            ab.clicked.connect(lambda: (act_cb(), self.dismiss()))
            col.addWidget(ab, 0, QtCore.Qt.AlignLeft)
        lay.addLayout(col, 1)
        x = tool_button("close", "Dismiss", "text_muted", 12)
        x.clicked.connect(self.dismiss)
        lay.addWidget(x, 0, QtCore.Qt.AlignTop)
        self.setFixedWidth(380)

        if duration_ms > 0:
            QtCore.QTimer.singleShot(duration_ms, self.dismiss)
        self._closing = False

    def _restyle(self) -> None:
        c = theme_manager.tokens()
        self.setStyleSheet(
            f"QFrame#toast {{ background: {c['card']}; border: 1px solid {c['border_strong']};"
            f" border-left: 3px solid {color(self._fg).name()}; border-radius: 8px; }}"
        )
        self._shadow.setColor(QtGui.QColor(0, 0, 0, 90 if theme_manager.is_dark else 45))

    def dismiss(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.hide()
        self.closed.emit(self)
        self.deleteLater()


class ToastHost(QtCore.QObject):
    """Stacks toasts in the top-right corner of a host widget."""

    MARGIN = 16

    def __init__(self, host: QtWidgets.QWidget):
        super().__init__(host)
        self.host = host
        self.toasts: List[Toast] = []
        host.installEventFilter(self)

    def show(self, kind: str, title: str, text: str = "", duration_ms: int = 4500,
             action: Optional[tuple] = None) -> Toast:
        t = Toast(kind, title, text, self.host, duration_ms, action)
        t.closed.connect(self._remove)
        t.adjustSize()
        self.toasts.append(t)
        # Slide in from the right.
        end = self._slot_pos(len(self.toasts) - 1, t)
        t.move(end + QtCore.QPoint(40, 0))
        t.show()
        t.raise_()
        anim = QtCore.QPropertyAnimation(t, b"pos", t)
        anim.setDuration(220)
        anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        anim.setStartValue(t.pos())
        anim.setEndValue(end)
        anim.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
        while len(self.toasts) > 4:
            self.toasts[0].dismiss()
        return t

    def _slot_pos(self, index: int, t: QtWidgets.QWidget) -> QtCore.QPoint:
        y = self.MARGIN
        for other in self.toasts[:index]:
            y += other.height() + 8
        return QtCore.QPoint(self.host.width() - t.width() - self.MARGIN, y)

    def _remove(self, t: Toast) -> None:
        if t in self.toasts:
            self.toasts.remove(t)
        self._relayout()

    def _relayout(self) -> None:
        for i, t in enumerate(self.toasts):
            try:
                t.move(self._slot_pos(i, t))
            except RuntimeError:
                pass

    def eventFilter(self, obj, ev) -> bool:
        if obj is self.host and ev.type() == QtCore.QEvent.Resize:
            self._relayout()
        return False


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------

class EmptyState(QtWidgets.QWidget):
    def __init__(self, icon_name: str, title: str, text: str,
                 action: Optional[QtWidgets.QWidget] = None, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setAlignment(QtCore.Qt.AlignCenter)
        lay.setSpacing(10)
        ic = icon_label(icon_name, "accent", 48)
        lay.addWidget(ic, 0, QtCore.Qt.AlignHCenter)
        t = label(title, "title")
        t.setAlignment(QtCore.Qt.AlignCenter)
        lay.addWidget(t)
        b = label(text, "muted", wrap=True)
        b.setAlignment(QtCore.Qt.AlignCenter)
        b.setMaximumWidth(420)
        lay.addWidget(b, 0, QtCore.Qt.AlignHCenter)
        if action is not None:
            lay.addSpacing(6)
            lay.addWidget(action, 0, QtCore.Qt.AlignHCenter)


def human_bytes(n: float) -> str:
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or u == "TB":
            return f"{int(n)} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def human_time(sec: float) -> str:
    sec = max(0, int(sec or 0))
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m {sec % 60}s"
    return f"{sec // 3600}h {(sec % 3600) // 60}m"
