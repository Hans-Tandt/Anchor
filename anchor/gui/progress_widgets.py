"""Custom widgets for the multi-phase backup progress UI.

Three widgets live here so main_window.py does not balloon:

- PhaseStripWidget
    Three mini rows (Scan / Copy / Verify). Each row shows an icon reflecting
    the phase state (pending / running / done / issue), the phase name, a thin
    bar for that phase's progress, and a right-aligned detail string (duration,
    live counts, etc.). The row for the currently-running phase is highlighted.

- CopyProgressDonut
    An 84x84 ring that shows the copy work of the current run. The scan sets
    the total (100%); the gold arc fills as files are copied. At the end it
    blinks green with "Finished", or turns red ("Issues") / amber ("Stopped").

- VerifyBanner
    A stylised banner shown under the progress area after a run finishes. Green
    for pass (auto-dismisses after 10 s), red for fail (sticky, clicking it
    opens the issues dialog).
"""
from __future__ import annotations

from typing import Callable, List, Optional

from PySide6 import QtCore, QtGui, QtWidgets


# TechEase palette tokens — matched to anchor/gui/theme.py's DARK dict but kept
# constant here so the widgets look the same in both themes (the overall UI's
# background already changes with the theme, which gives enough contrast).
_ACCENT = "#d4a85a"       # gold — the "needs copy" slice / running row
_ACCENT_DIM = "#8a6f3d"
_MUTED = "#4a4a4a"
_TEXT = "#ece6d8"
_TEXT_DIM = "#8a8578"
_OK = "#5fb88a"
_WARN = "#e9a23b"
_ERR = "#e35d6a"
_ROW_BG_RUNNING = "#1f232b"


# ---------------------------------------------------------------------------
# Phase strip
# ---------------------------------------------------------------------------

_PHASE_ORDER = ("scan", "copy", "verify")
_PHASE_LABELS = {"scan": "Scan", "copy": "Copy", "verify": "Verify"}

# Tooltips that explain what each phase actually does — Scan and Verify are
# easy to confuse ("they both walk files"), so each row carries a short
# explainer on hover.
_PHASE_TOOLTIPS = {
    "scan": (
        "Scan — classifies the SOURCE files.\n"
        "Walks every file under the source folders and decides which ones "
        "need copying (changed since the last run) and which can be skipped "
        "(unchanged, already at the destination according to the state DB)."
    ),
    "copy": (
        "Copy — writes the changed files to the DESTINATION.\n"
        "Only the files Scan marked 'to copy' are written. Progress tracks "
        "bytes copied / bytes to copy."
    ),
    "verify": (
        "Verify — walks the DESTINATION to check the backup is intact.\n"
        "For every file the state DB says should be at the destination, the "
        "size (and hash, if the profile uses hash verification) is checked. "
        "Reports missing or wrong-sized files."
    ),
}

# Unicode icons for each state (keep pure text so no font files needed).
_STATE_ICONS = {
    "pending": "○",
    "running": "▶",
    "done":    "✓",
    "issue":   "⚠",
}
_STATE_COLORS = {
    "pending": _TEXT_DIM,
    "running": _ACCENT,
    "done":    _OK,
    "issue":   _WARN,
}


class _PhaseRow(QtWidgets.QFrame):
    """Single row of the PhaseStripWidget.

    Layout: [icon] [phase name] [thin progress bar] [detail text].
    The whole row gets a subtle background highlight while running.
    """

    def __init__(self, phase_key: str, parent=None):
        super().__init__(parent)
        self.phase_key = phase_key
        self.setObjectName(f"phaseRow_{phase_key}")
        self.setFrameShape(QtWidgets.QFrame.NoFrame)

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(10)

        self.icon_lbl = QtWidgets.QLabel(_STATE_ICONS["pending"])
        self.icon_lbl.setFixedWidth(18)
        self.icon_lbl.setAlignment(QtCore.Qt.AlignCenter)
        f = self.icon_lbl.font(); f.setPointSize(11); f.setBold(True)
        self.icon_lbl.setFont(f)
        lay.addWidget(self.icon_lbl)

        self.name_lbl = QtWidgets.QLabel(_PHASE_LABELS[phase_key])
        self.name_lbl.setFixedWidth(60)
        # Explain what this phase actually does on hover — Scan vs Verify
        # is easy to mix up.
        tip = _PHASE_TOOLTIPS.get(phase_key, "")
        if tip:
            self.name_lbl.setToolTip(tip)
            self.setToolTip(tip)
        lay.addWidget(self.name_lbl)

        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        self.bar.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed,
        )
        lay.addWidget(self.bar, 1)

        self.detail_lbl = QtWidgets.QLabel("")
        self.detail_lbl.setMinimumWidth(140)
        self.detail_lbl.setAlignment(
            QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter,
        )
        lay.addWidget(self.detail_lbl)

        # The bar of the running phase blinks (bright / dim gold) so the eye
        # finds the active phase at once.
        self._state = "pending"
        self._blink_on = True
        self._applied = None  # (state, blink_on) last written to the stylesheet
        self._blink = QtCore.QTimer(self)
        self._blink.setInterval(500)
        self._blink.timeout.connect(self._tick_blink)

        self._apply_state("pending")

    def set_state(self, state: str, progress_pct: float = 0.0, detail: str = "") -> None:
        if state not in _STATE_ICONS:
            state = "pending"
        self._state = state
        if state == "running":
            # Progress events arrive ~10x per second: only start the timer
            # once, or it would never get to tick.
            if not self._blink.isActive():
                self._blink_on = True
                self._blink.start()
        else:
            self._blink.stop()
            self._blink_on = True
        self._apply_state(state)
        self.bar.setRange(0, 100)
        self.bar.setValue(max(0, min(100, int(round(progress_pct)))))
        if state in ("done", "issue"):
            self.bar.setValue(100)
        self.detail_lbl.setText(detail)

    def _tick_blink(self) -> None:
        if self._state != "running":
            self._blink.stop()
            return
        self._blink_on = not self._blink_on
        self._apply_state(self._state)

    def _apply_state(self, state: str) -> None:
        # Re-writing a stylesheet re-polishes the whole row; skip it when
        # nothing visible changed (set_state runs on every progress event).
        key = (state, self._blink_on)
        if key == self._applied:
            return
        self._applied = key
        self.icon_lbl.setText(_STATE_ICONS[state])
        color = _STATE_COLORS[state]
        self.icon_lbl.setStyleSheet(f"color: {color};")
        bar_color = color if (state != "running" or self._blink_on) else _ACCENT_DIM
        # Highlight the row's background while running so the eye jumps to it.
        bg = _ROW_BG_RUNNING if state == "running" else "transparent"
        self.setStyleSheet(
            f"QFrame#phaseRow_{self.phase_key} {{"
            f" background: {bg}; border-radius: 4px; }}"
            # Make the thin bar match the state colour (gold while running,
            # green when done, orange on issue, muted when pending).
            f" QProgressBar::chunk {{ background: {bar_color}; border-radius: 2px; }}"
            f" QProgressBar {{ background: {_MUTED}; border: none; border-radius: 2px; }}"
        )
        self.name_lbl.setStyleSheet(
            f"color: {_TEXT if state == 'running' else _TEXT_DIM};"
            f" font-weight: {'600' if state == 'running' else 'normal'};"
        )


class PhaseStripWidget(QtWidgets.QFrame):
    """The three stacked phase rows, plus the overall progress bar.

    The overall bar is weighted: Scan contributes 10%, Copy 80%, Verify 10%.
    When Verify is disabled for the profile, Scan contributes 10% and Copy
    contributes the remaining 90%.
    """

    # Weights for the overall bar. Tuned by rough wall-clock ratios: scan
    # is cheap (stat-based), copy is the real I/O, verify is a re-walk.
    _W_WITH_VERIFY = {"scan": 0.10, "copy": 0.80, "verify": 0.10}
    _W_WITHOUT_VERIFY = {"scan": 0.10, "copy": 0.90, "verify": 0.0}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("phaseStrip")
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)

        self.rows = {k: _PhaseRow(k) for k in _PHASE_ORDER}
        for k in _PHASE_ORDER:
            v.addWidget(self.rows[k])

        # Overall bar — larger, below the three phase rows.
        self.overall = QtWidgets.QProgressBar()
        self.overall.setRange(0, 100)
        self.overall.setValue(0)
        self.overall.setFixedHeight(16)
        self.overall.setFormat("Overall  %p%")
        self.overall.setAlignment(QtCore.Qt.AlignCenter)
        v.addSpacing(4)
        v.addWidget(self.overall)

        self._verify_enabled = True
        self._verify_only = False

    def reset(self, verify_enabled: bool = True) -> None:
        self._verify_only = False
        self._verify_enabled = verify_enabled
        for key in _PHASE_ORDER:
            self.rows[key].setVisible(True)
            self.rows[key].set_state("pending", 0, "")
        self.rows["verify"].setVisible(verify_enabled)
        self.overall.setValue(0)

    def set_verify_only_mode(self) -> None:
        """Show only the verify row (for a standalone Verify run). The
        overall bar then tracks verify progress alone."""
        self._verify_only = True
        self._verify_enabled = True
        self.rows["scan"].setVisible(False)
        self.rows["copy"].setVisible(False)
        self.rows["verify"].setVisible(True)
        self.rows["verify"].set_state("pending", 0, "")
        self.overall.setValue(0)

    def set_phase(
        self,
        phase_key: str,
        state: str,
        progress_pct: float = 0.0,
        detail: str = "",
    ) -> None:
        """Set one phase's row and recompute the overall bar."""
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

    def _recompute_overall(self) -> None:
        if self._verify_only:
            # Standalone Verify run: the overall bar == the verify row.
            self.overall.setValue(self.rows["verify"].bar.value())
            return
        weights = (
            self._W_WITH_VERIFY if self._verify_enabled else self._W_WITHOUT_VERIFY
        )
        total = 0.0
        for key in _PHASE_ORDER:
            w = weights.get(key, 0.0)
            if w == 0:
                continue
            total += w * (self.rows[key].bar.value() / 100.0)
        self.overall.setValue(int(round(total * 100)))


# ---------------------------------------------------------------------------
# Copy progress donut
# ---------------------------------------------------------------------------

class CopyProgressDonut(QtWidgets.QWidget):
    """Ring chart of the copy work for the current run.

    The scan decides how much data has to be copied; that amount is 100%.
    The gold arc then fills as the copy phase writes files. When the run
    ends the ring turns:
      - green and blinks for BLINK_MS, centre text "Finished" (all OK),
      - red, centre text "Issues" (failed files or verify problems),
      - amber, centre text "Stopped" (the user pressed Cancel).
    """

    BLINK_INTERVAL_MS = 500
    BLINK_MS = 10_000

    def __init__(self, parent=None, diameter: int = 84):
        super().__init__(parent)
        self._diameter = diameter
        self.setFixedSize(diameter, diameter)
        self._fraction = 0.0      # 0.0 - 1.0 of the copy work done
        self._state = "idle"      # idle | running | finished | issues | stopped
        self._label = ""
        self._blink_on = True
        self._blink_ticks_left = 0
        self._blink = QtCore.QTimer(self)
        self._blink.setInterval(self.BLINK_INTERVAL_MS)
        self._blink.timeout.connect(self._tick_blink)

    # --- state changes ---------------------------------------------------

    def reset(self) -> None:
        self._blink.stop()
        self._fraction = 0.0
        self._state = "idle"
        self._label = ""
        self._blink_on = True
        self.update()

    def set_progress(self, fraction: float) -> None:
        """Copy work done so far, 0.0 - 1.0."""
        self._blink.stop()
        self._fraction = max(0.0, min(1.0, fraction))
        self._state = "running"
        self._label = f"{int(self._fraction * 100)}%"
        self._blink_on = True
        self.update()

    def show_finished(self) -> None:
        self._fraction = 1.0
        self._state = "finished"
        self._label = "Finished"
        self._blink_on = True
        self._blink_ticks_left = self.BLINK_MS // self.BLINK_INTERVAL_MS
        self._blink.start()
        self.update()

    def show_issues(self, label: str = "Issues") -> None:
        self._blink.stop()
        self._fraction = 1.0
        self._state = "issues"
        self._label = label
        self._blink_on = True
        self.update()

    def show_stopped(self) -> None:
        # Keep the arc where the copy stopped so the user sees how far it got.
        self._blink.stop()
        self._state = "stopped"
        self._label = "Stopped"
        self._blink_on = True
        self.update()

    def _tick_blink(self) -> None:
        self._blink_ticks_left -= 1
        if self._blink_ticks_left <= 0:
            # Blink over: hold a solid green ring.
            self._blink.stop()
            self._blink_on = True
        else:
            self._blink_on = not self._blink_on
        self.update()

    # --- painting --------------------------------------------------------

    def _arc_color(self) -> QtGui.QColor:
        if self._state == "finished":
            return QtGui.QColor(_OK if self._blink_on else "#2c5a42")
        if self._state == "issues":
            return QtGui.QColor(_ERR)
        if self._state == "stopped":
            return QtGui.QColor(_WARN)
        return QtGui.QColor(_ACCENT)

    def paintEvent(self, ev: QtGui.QPaintEvent) -> None:
        qp = QtGui.QPainter(self)
        qp.setRenderHint(QtGui.QPainter.Antialiasing)
        qp.setPen(QtCore.Qt.NoPen)

        outer = QtCore.QRectF(self.rect()).adjusted(2, 2, -2, -2)
        thickness = max(8.0, self._diameter * 0.14)
        inner = outer.adjusted(thickness, thickness, -thickness, -thickness)

        # Real ring (outer minus inner), so the panel behind shows through
        # the hole in both the dark and the light theme.
        ring = QtGui.QPainterPath()
        ring.addEllipse(outer)
        hole = QtGui.QPainterPath()
        hole.addEllipse(inner)
        ring = ring.subtracted(hole)

        # Track: semi-transparent grey reads on dark and light panels alike.
        qp.setBrush(QtGui.QColor(128, 128, 128, 90))
        qp.drawPath(ring)

        # Progress arc from 12 o'clock, clockwise.
        if self._fraction > 0:
            sweep = QtGui.QPainterPath()
            centre = outer.center()
            sweep.moveTo(centre)
            sweep.arcTo(outer, 90.0, -self._fraction * 360.0)
            sweep.closeSubpath()
            qp.setBrush(self._arc_color())
            qp.drawPath(sweep.intersected(ring))

        # Centre text, shrunk until it fits inside the hole.
        if self._label:
            # Only the ring blinks; the text keeps the bright state colour so
            # "Finished" stays readable on the dim half of the blink.
            text_color = {
                "finished": QtGui.QColor(_OK),
                "issues": QtGui.QColor(_ERR),
                "stopped": QtGui.QColor(_WARN),
            }.get(self._state, self.palette().color(QtGui.QPalette.WindowText))
            qp.setPen(text_color)
            f = QtGui.QFont(self.font())
            f.setBold(True)
            room = inner.width() - 6
            for size in (11, 10, 9, 8, 7, 6):
                f.setPointSize(size)
                if QtGui.QFontMetrics(f).horizontalAdvance(self._label) <= room:
                    break
            qp.setFont(f)
            qp.drawText(outer, QtCore.Qt.AlignCenter, self._label)

        qp.end()


# ---------------------------------------------------------------------------
# Verify banner
# ---------------------------------------------------------------------------

class VerifyBanner(QtWidgets.QLabel):
    """Flashed under the progress area after a verify-enabled run finishes.

    Pass: green background, auto-dismisses after 10 s.
    Fail: red background, sticky — clicking it invokes the on_click callback
    (used to open the issues dialog).
    """

    DISMISS_MS = 10_000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)
        self.setWordWrap(True)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setMinimumHeight(40)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self._on_click: Optional[Callable[[], None]] = None

        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_pass(self, text: str) -> None:
        self._on_click = None
        self.setStyleSheet(
            "QLabel { background-color: #1e4a30; color: #d4f0dd;"
            " border: 1px solid #5fb88a; border-radius: 6px;"
            " padding: 10px; font-weight: 600; font-size: 11pt; }"
        )
        self.setText("✓  " + text + "   (click to dismiss)")
        self.setVisible(True)
        self._timer.start(self.DISMISS_MS)

    def show_fail(self, text: str, on_click: Optional[Callable[[], None]] = None) -> None:
        self._on_click = on_click
        self.setStyleSheet(
            "QLabel { background-color: #4a1a1a; color: #ffd0d0;"
            " border: 1px solid #e35d6a; border-radius: 6px;"
            " padding: 10px; font-weight: 600; font-size: 11pt; }"
        )
        suffix = "   (click to open issues)" if on_click else ""
        self.setText("✗  " + text + suffix)
        self.setVisible(True)
        # Fail banner is sticky — no timer.
        self._timer.stop()

    def dismiss(self) -> None:
        self._timer.stop()
        self.hide()
        self._on_click = None

    def mousePressEvent(self, ev: QtGui.QMouseEvent) -> None:
        cb = self._on_click
        self.dismiss()
        if cb is not None:
            try:
                cb()
            except Exception:
                pass
        super().mousePressEvent(ev)
