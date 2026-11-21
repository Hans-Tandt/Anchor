"""Widgets for the multi-phase backup progress UI.

- PhaseStripWidget — Scan / Copy / Verify rows (state icon, name, thin bar,
  detail text) plus an overall bar. The running row is highlighted and its bar
  pulses so the eye finds the active phase.
- CopyProgressDonut — ring chart of the copy work. The scan decides the total
  (100%); the arc fills as files are written; at the end the ring shows
  Finished (green, gently pulsing), Issues (red) or Stopped (amber).
- VerifyBanner — Fluent InfoBar shown after a verify-enabled run. Success
  auto-dismisses after 10 s; failure is sticky and clicking it opens the
  issues dialog.

All colours come from the theme tokens, so the widgets read correctly in both
the dark and the light theme.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from . import icons
from .theme import color, theme_manager
from .widgets import SmoothProgressBar


_PHASE_ORDER = ("scan", "copy", "verify")
_PHASE_LABELS = {"scan": "Scan", "copy": "Copy", "verify": "Verify"}
_PHASE_ICONS = {"scan": "search", "copy": "files", "verify": "shield"}

_PHASE_TOOLTIPS = {
    "scan": (
        "Scan — classifies the SOURCE files.\n"
        "Walks every file under the source folders and decides which ones "
        "need copying (changed since the last run) and which can be skipped."
    ),
    "copy": (
        "Copy — writes the changed files to the DESTINATION.\n"
        "Only the files Scan marked 'to copy' are written. Progress tracks "
        "bytes copied / bytes to copy."
    ),
    "verify": (
        "Verify — checks the backup is intact.\n"
        "For every file that should be at the destination, the size (and "
        "hash, if the profile uses hash verification) is checked."
    ),
}

_STATE_COLOR = {"pending": "text_muted", "running": "accent", "done": "ok", "issue": "warn"}
_STATE_ICON = {"pending": None, "running": None, "done": "check-circle", "issue": "warning"}


class _PhaseRow(QtWidgets.QFrame):
    def __init__(self, phase_key: str, parent=None):
        super().__init__(parent)
        self.phase_key = phase_key
        self.setObjectName(f"phaseRow_{phase_key}")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setToolTip(_PHASE_TOOLTIPS.get(phase_key, ""))

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(10)

        self.icon_lbl = QtWidgets.QLabel()
        self.icon_lbl.setFixedSize(18, 18)
        lay.addWidget(self.icon_lbl)

        self.name_lbl = QtWidgets.QLabel(_PHASE_LABELS[phase_key])
        self.name_lbl.setFixedWidth(52)
        lay.addWidget(self.name_lbl)

        self.bar = SmoothProgressBar(height=4)
        self.bar.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        lay.addWidget(self.bar, 1)

        self.detail_lbl = QtWidgets.QLabel("")
        self.detail_lbl.setObjectName("caption")
        self.detail_lbl.setMinimumWidth(170)
        self.detail_lbl.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        lay.addWidget(self.detail_lbl)

        self._state = "pending"
        self._pct = 0.0
        self._pulse_on = True
        self._pulse = QtCore.QTimer(self)
        self._pulse.setInterval(600)
        self._pulse.timeout.connect(self._tick)
        self._applied = None
        theme_manager.changed.connect(lambda: self._apply(force=True))
        self._apply(force=True)

    def value_pct(self) -> float:
        return self._pct

    def set_state(self, state: str, progress_pct: float = 0.0, detail: str = "") -> None:
        if state not in _STATE_COLOR:
            state = "pending"
        self._state = state
        if state == "running":
            if not self._pulse.isActive():
                self._pulse_on = True
                self._pulse.start()
        else:
            self._pulse.stop()
            self._pulse_on = True
        pct = 100.0 if state in ("done", "issue") else max(0.0, min(100.0, progress_pct))
        self._pct = pct
        self.bar.set_fraction(pct / 100.0, animate=state == "running")
        self.detail_lbl.setText(detail)
        self._apply()

    def _tick(self) -> None:
        if self._state != "running":
            self._pulse.stop()
            return
        self._pulse_on = not self._pulse_on
        self._apply()

    def _apply(self, force: bool = False) -> None:
        key = (self._state, self._pulse_on, theme_manager.is_dark)
        if key == self._applied and not force:
            return
        self._applied = key
        st = self._state
        ck = _STATE_COLOR[st]
        ic = _STATE_ICON[st] or _PHASE_ICONS[self.phase_key]
        self.icon_lbl.setPixmap(icons.pixmap(ic, 16, ck))
        bar_key = ck if (st != "running" or self._pulse_on) else "accent_pressed"
        self.bar.set_chunk_color(bar_key)
        running = st == "running"
        bg = color("accent_soft") if running else QtGui.QColor(0, 0, 0, 0)
        self.setStyleSheet(
            f"QFrame#phaseRow_{self.phase_key} {{ background: rgba({bg.red()},{bg.green()},"
            f"{bg.blue()},{bg.alphaF():.2f}); border-radius: 6px; }}"
        )
        self.name_lbl.setStyleSheet(
            f"color: {color('text' if st != 'pending' else 'text_muted').name()};"
            f" font-weight: {'600' if running else 'normal'};"
        )


class PhaseStripWidget(QtWidgets.QFrame):
    """Three phase rows plus a weighted overall bar
    (Scan 10%, Copy 80%, Verify 10%; or 10/90 without Verify)."""

    _W_WITH_VERIFY = {"scan": 0.10, "copy": 0.80, "verify": 0.10}
    _W_WITHOUT_VERIFY = {"scan": 0.10, "copy": 0.90, "verify": 0.0}

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        self.rows = {k: _PhaseRow(k) for k in _PHASE_ORDER}
        for k in _PHASE_ORDER:
            v.addWidget(self.rows[k])

        v.addSpacing(8)
        head = QtWidgets.QHBoxLayout()
        head.setContentsMargins(10, 0, 10, 0)
        self.overall_lbl = QtWidgets.QLabel("Overall")
        self.overall_lbl.setObjectName("caption")
        self.overall_pct = QtWidgets.QLabel("0%")
        self.overall_pct.setObjectName("caption")
        head.addWidget(self.overall_lbl)
        head.addStretch(1)
        head.addWidget(self.overall_pct)
        v.addLayout(head)
        self.overall = SmoothProgressBar(height=6)
        wrap = QtWidgets.QHBoxLayout()
        wrap.setContentsMargins(10, 2, 10, 0)
        wrap.addWidget(self.overall)
        v.addLayout(wrap)
        theme_manager.changed.connect(lambda: self.overall.set_chunk_color("accent"))
        self.overall.set_chunk_color("accent")

        self._verify_enabled = True
        self._verify_only = False

    def overall_value(self) -> int:
        return int(round(self.overall.value() / 10))

    def reset(self, verify_enabled: bool = True) -> None:
        self._verify_only = False
        self._verify_enabled = verify_enabled
        for key in _PHASE_ORDER:
            self.rows[key].setVisible(True)
            self.rows[key].set_state("pending", 0, "")
        self.rows["verify"].setVisible(verify_enabled)
        self._set_overall(0, animate=False)

    def set_verify_only_mode(self) -> None:
        self._verify_only = True
        self._verify_enabled = True
        self.rows["scan"].setVisible(False)
        self.rows["copy"].setVisible(False)
        self.rows["verify"].setVisible(True)
        self.rows["verify"].set_state("pending", 0, "")
        self._set_overall(0, animate=False)

    def set_phase(self, phase_key: str, state: str, progress_pct: float = 0.0, detail: str = "") -> None:
        if phase_key in self.rows:
            self.rows[phase_key].set_state(state, progress_pct, detail)
        self._recompute_overall()

    def mark_done(self, phase_key: str, detail: str = "") -> None:
        if phase_key in self.rows:
            self.rows[phase_key].set_state("done", 100, detail)
        self._recompute_overall()

    def mark_pending(self, phase_key: str) -> None:
        if phase_key in self.rows:
            self.rows[phase_key].set_state("pending", 0, "")
        self._recompute_overall()

    def _set_overall(self, pct: float, animate: bool = True) -> None:
        self.overall.set_fraction(pct / 100.0, animate=animate)
        self.overall_pct.setText(f"{int(round(pct))}%")

    def _recompute_overall(self) -> None:
        if self._verify_only:
            self._set_overall(self.rows["verify"].value_pct())
            return
        weights = self._W_WITH_VERIFY if self._verify_enabled else self._W_WITHOUT_VERIFY
        total = sum(w * self.rows[k].value_pct() / 100.0 for k, w in weights.items() if w)
        self._set_overall(total * 100)


class CopyProgressDonut(QtWidgets.QWidget):
    PULSE_MS = 600

    def __init__(self, parent=None, diameter: int = 96):
        super().__init__(parent)
        self._diameter = diameter
        self.setFixedSize(diameter, diameter)
        self._fraction = 0.0
        self._shown = 0.0
        self._state = "idle"
        self._label = ""
        self._pulse_on = True
        self._pulse = QtCore.QTimer(self)
        self._pulse.setInterval(self.PULSE_MS)
        self._pulse.timeout.connect(self._tick)
        self._anim = QtCore.QVariantAnimation(self)
        self._anim.setDuration(260)
        self._anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        theme_manager.changed.connect(self.update)

    def _on_anim(self, v) -> None:
        self._shown = float(v)
        self.update()

    def _animate_to(self, f: float) -> None:
        self._fraction = f
        self._anim.stop()
        self._anim.setStartValue(self._shown)
        self._anim.setEndValue(f)
        self._anim.start()

    def reset(self) -> None:
        self._pulse.stop()
        self._anim.stop()
        self._fraction = self._shown = 0.0
        self._state = "idle"
        self._label = ""
        self._pulse_on = True
        self.update()

    def set_progress(self, fraction: float) -> None:
        self._pulse.stop()
        self._state = "running"
        f = max(0.0, min(1.0, fraction))
        self._label = f"{int(f * 100)}%"
        self._pulse_on = True
        self._animate_to(f)

    def show_finished(self) -> None:
        self._state = "finished"
        self._label = "Done"
        self._pulse_on = True
        self._pulse.start()
        self._animate_to(1.0)

    def show_issues(self, label: str = "Issues") -> None:
        self._pulse.stop()
        self._state = "issues"
        self._label = label
        self._animate_to(1.0)

    def show_stopped(self) -> None:
        self._pulse.stop()
        self._state = "stopped"
        self._label = "Stopped"
        self.update()

    def state(self) -> str:
        return self._state

    def _tick(self) -> None:
        self._pulse_on = not self._pulse_on
        self.update()

    def _arc_color(self) -> QtGui.QColor:
        if self._state == "finished":
            c = color("ok")
            if not self._pulse_on:
                c.setAlphaF(0.55)
            return c
        return color({"issues": "err", "stopped": "warn"}.get(self._state, "accent"))

    def paintEvent(self, _ev) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        thick = max(6.0, self._diameter * 0.085)
        r = QtCore.QRectF(self.rect()).adjusted(thick / 2 + 1, thick / 2 + 1, -thick / 2 - 1, -thick / 2 - 1)
        pen = QtGui.QPen(color("track"), thick)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        p.setPen(pen)
        p.drawEllipse(r)
        if self._shown > 0.001:
            pen.setColor(self._arc_color())
            p.setPen(pen)
            p.drawArc(r, 90 * 16, int(-self._shown * 360 * 16))
        if self._label:
            text_key = {"finished": "ok", "issues": "err", "stopped": "warn"}.get(self._state, "text")
            p.setPen(color(text_key))
            f = QtGui.QFont(self.font())
            f.setWeight(QtGui.QFont.DemiBold)
            room = r.width() - thick - 6
            for size in (15, 13, 12, 11, 10, 9, 8):
                f.setPointSize(size)
                if QtGui.QFontMetrics(f).horizontalAdvance(self._label) <= room:
                    break
            p.setFont(f)
            p.drawText(self.rect(), QtCore.Qt.AlignCenter, self._label)
        p.end()


class VerifyBanner(QtWidgets.QFrame):
    """Inline Fluent InfoBar for the verify result."""

    DISMISS_MS = 10_000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("verifyBanner")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setVisible(False)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(12)
        self._icon = QtWidgets.QLabel()
        self._icon.setFixedSize(20, 20)
        lay.addWidget(self._icon, 0, QtCore.Qt.AlignTop)
        col = QtWidgets.QVBoxLayout()
        col.setSpacing(2)
        self._title = QtWidgets.QLabel()
        self._title.setStyleSheet("font-weight: 600;")
        self._text = QtWidgets.QLabel()
        self._text.setWordWrap(True)
        self._text.setObjectName("body")
        col.addWidget(self._title)
        col.addWidget(self._text)
        lay.addLayout(col, 1)
        self._hint = QtWidgets.QLabel()
        self._hint.setObjectName("caption")
        lay.addWidget(self._hint, 0, QtCore.Qt.AlignVCenter)
        self._on_click: Optional[Callable[[], None]] = None
        self._kind = "ok"
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        theme_manager.changed.connect(self._restyle)

    def text(self) -> str:
        return f"{self._title.text()} {self._text.text()}"

    def _restyle(self) -> None:
        fg = "ok" if self._kind == "ok" else "err"
        bg = color(fg + "_soft")
        line = color(fg)
        self.setStyleSheet(
            f"QFrame#verifyBanner {{ background: rgba({bg.red()},{bg.green()},{bg.blue()},{bg.alphaF():.2f});"
            f" border: 1px solid rgba({line.red()},{line.green()},{line.blue()},0.45); border-radius: 8px; }}"
        )
        self._icon.setPixmap(icons.pixmap("check-circle" if self._kind == "ok" else "error", 20, fg))

    def _show(self, kind: str, text: str, hint: str) -> None:
        self._kind = kind
        title, _, rest = text.partition(" — ")
        self._title.setText(title)
        self._text.setText(rest[:1].upper() + rest[1:])
        self._text.setVisible(bool(rest))
        self._hint.setText(hint)
        self._restyle()
        self.setVisible(True)

    def show_pass(self, text: str) -> None:
        self._on_click = None
        self._show("ok", text, "Click to dismiss")
        self._timer.start(self.DISMISS_MS)

    def show_fail(self, text: str, on_click: Optional[Callable[[], None]] = None) -> None:
        self._on_click = on_click
        self._show("err", text, "Click to view issues" if on_click else "")
        self._timer.stop()

    def dismiss(self) -> None:
        self._timer.stop()
        self.hide()
        self._on_click = None

    def mousePressEvent(self, ev: QtGui.QMouseEvent) -> None:
        cb = self._on_click
        self.dismiss()
        if cb is not None:
            cb()
        super().mousePressEvent(ev)
