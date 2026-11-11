"""Custom widgets for the multi-phase backup progress UI.

Three widgets live here so main_window.py does not balloon:

- PhaseStripWidget
    Three mini rows (Scan / Copy / Verify). Each row shows an icon reflecting
    the phase state (pending / running / done / issue), the phase name, a thin
    bar for that phase's progress, and a right-aligned detail string (duration,
    live counts, etc.). The row for the currently-running phase is highlighted.

- ScanDonutWidget
    A 72x72 donut that paints two slices — "to copy" in the accent colour and
    "unchanged" in muted. Live-updates during the scan phase as classify() emits
    progress. The hole shows the current "to copy" percentage as text. Full
    counts are exposed via tooltip.

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

        self._apply_state("pending")

    def set_state(self, state: str, progress_pct: float = 0.0, detail: str = "") -> None:
        if state not in _STATE_ICONS:
            state = "pending"
        self._apply_state(state)
        self.bar.setRange(0, 100)
        self.bar.setValue(max(0, min(100, int(round(progress_pct)))))
        if state in ("done", "issue"):
            self.bar.setValue(100)
        self.detail_lbl.setText(detail)

    def _apply_state(self, state: str) -> None:
        self.icon_lbl.setText(_STATE_ICONS[state])
        color = _STATE_COLORS[state]
        self.icon_lbl.setStyleSheet(f"color: {color};")
        # Highlight the row's background while running so the eye jumps to it.
        bg = _ROW_BG_RUNNING if state == "running" else "transparent"
        self.setStyleSheet(
            f"QFrame#phaseRow_{self.phase_key} {{"
            f" background: {bg}; border-radius: 4px; }}"
            # Make the thin bar match the state colour (gold while running,
            # green when done, orange on issue, muted when pending).
            f" QProgressBar::chunk {{ background: {color}; border-radius: 2px; }}"
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
# Scan donut
# ---------------------------------------------------------------------------

class ScanDonutWidget(QtWidgets.QWidget):
    """Donut (ring) chart: gold slice = files that need copying, muted slice =
    unchanged. Centre text is the % to copy. Updated live during scan.
    """

    def __init__(self, parent=None, diameter: int = 72):
        super().__init__(parent)
        self._diameter = diameter
        self.setFixedSize(diameter, diameter)
        self._copy_pct = 0.0  # 0.0 - 1.0
        self._copy_count = 0
        self._unchanged_count = 0
        self._active = False
        self.setToolTip("Scan not started yet")

    def reset(self) -> None:
        self._copy_pct = 0.0
        self._copy_count = 0
        self._unchanged_count = 0
        self._active = False
        self.setToolTip("Scan not started yet")
        self.update()

    def set_fractions(self, copy_count: int, unchanged_count: int) -> None:
        """Update the donut from the engine's live counts."""
        total = copy_count + unchanged_count
        self._copy_count = copy_count
        self._unchanged_count = unchanged_count
        self._copy_pct = (copy_count / total) if total > 0 else 0.0
        self._active = True
        self.setToolTip(
            f"To copy: {copy_count} files\n"
            f"Unchanged: {unchanged_count} files\n"
            f"Total classified: {total} files"
        )
        self.update()

    def paintEvent(self, ev: QtGui.QPaintEvent) -> None:
        qp = QtGui.QPainter(self)
        qp.setRenderHint(QtGui.QPainter.Antialiasing)

        rect = self.rect().adjusted(2, 2, -2, -2)
        # Background ring (muted = unchanged slice)
        base_color = QtGui.QColor(_MUTED)
        qp.setBrush(base_color)
        qp.setPen(QtCore.Qt.NoPen)
        qp.drawEllipse(rect)

        # Accent slice (gold = to copy), starts at 12 o'clock and sweeps clockwise.
        if self._active and self._copy_pct > 0:
            span_deg = -self._copy_pct * 360  # negative = clockwise in Qt
            qp.setBrush(QtGui.QColor(_ACCENT))
            qp.drawPie(rect, 90 * 16, int(span_deg * 16))

        # Punch out the centre hole to make it a ring.
        hole_margin = int(self._diameter * 0.22)
        hole = rect.adjusted(hole_margin, hole_margin, -hole_margin, -hole_margin)
        # Use the parent's background by filling with the surrounding colour.
        # QWidget doesn't give us that directly, so just use the panel colour.
        qp.setBrush(QtGui.QColor("#16181d"))
        qp.drawEllipse(hole)

        # Centre text — "12%" or "—" when inactive.
        qp.setPen(QtGui.QColor(_TEXT))
        f = qp.font()
        f.setPointSize(10)
        f.setBold(True)
        qp.setFont(f)
        txt = f"{int(round(self._copy_pct * 100))}%" if self._active else "—"
        qp.drawText(rect, QtCore.Qt.AlignCenter, txt)

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
