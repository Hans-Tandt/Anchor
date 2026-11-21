"""Activity page — the live log, with level filter, search and colouring."""
from __future__ import annotations

import re
from collections import deque
from typing import Deque, Tuple

from PySide6 import QtCore, QtGui, QtWidgets

from ...logging_setup import get_tail
from ..theme import color, theme_manager
from ..widgets import Card, button, label

_LEVEL_RE = re.compile(r"\[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\]")
_LEVEL_RANK = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


class _LogHighlighter(QtGui.QSyntaxHighlighter):
    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt API
        m = _LEVEL_RE.search(text)
        ts = QtGui.QTextCharFormat()
        ts.setForeground(color("text_muted"))
        self.setFormat(0, min(19, len(text)), ts)
        if not m:
            return
        lvl = m.group(1)
        key = {"WARNING": "warn", "ERROR": "err", "CRITICAL": "err", "DEBUG": "text_muted"}.get(lvl)
        tag = QtGui.QTextCharFormat()
        tag.setForeground(color(key or "accent"))
        tag.setFontWeight(QtGui.QFont.DemiBold)
        self.setFormat(m.start(), m.end() - m.start(), tag)
        if key in ("warn", "err"):
            body = QtGui.QTextCharFormat()
            body.setForeground(color(key))
            self.setFormat(m.end(), len(text) - m.end(), body)


class ActivityPage(QtWidgets.QWidget):
    """Shows the in-memory log tail. Lines arrive from any thread through a
    queued signal; the listener is removed in :meth:`shutdown` so a late log
    line can never touch a deleted widget."""

    line_received = QtCore.Signal(str, str)
    error_count_changed = QtCore.Signal(int)

    MAX_LINES = 5000

    def __init__(self, open_logs, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self._lines: Deque[Tuple[str, str]] = deque(maxlen=self.MAX_LINES)
        self._unseen_errors = 0

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)
        lay.addWidget(label("Activity", "title"))
        lay.addWidget(label("Everything Anchor did this session. The full history is in the monthly log "
                            "files.", "muted", wrap=True))

        card = Card(padding=12, spacing=10)
        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(8)
        self.level = QtWidgets.QComboBox()
        self.level.addItems(["All levels", "Warnings and errors", "Errors only"])
        self.level.currentIndexChanged.connect(self._rebuild)
        bar.addWidget(self.level)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Filter lines…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._rebuild)
        bar.addWidget(self.search, 1)
        self.follow = QtWidgets.QCheckBox("Follow")
        self.follow.setChecked(True)
        self.follow.setToolTip("Keep scrolling to the newest line")
        bar.addWidget(self.follow)
        copy_btn = button("Copy", "copy")
        copy_btn.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(self.view.toPlainText()))
        bar.addWidget(copy_btn)
        clear_btn = button("Clear", "trash")
        clear_btn.clicked.connect(self.clear)
        bar.addWidget(clear_btn)
        open_btn = button("Open log folder", "folder-open")
        open_btn.clicked.connect(open_logs)
        bar.addWidget(open_btn)
        card.lay.addLayout(bar)

        self.view = QtWidgets.QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.view.setMaximumBlockCount(self.MAX_LINES)
        f = QtGui.QFont("Cascadia Mono")
        f.setStyleHint(QtGui.QFont.Monospace)
        f.setFamilies(["Cascadia Mono", "Consolas", "monospace"])
        f.setPointSize(9)
        self.view.setFont(f)
        self.view.setStyleSheet("QPlainTextEdit { border: none; background: transparent; }")
        self._hl = _LogHighlighter(self.view.document())
        theme_manager.changed.connect(self._hl.rehighlight)
        card.lay.addWidget(self.view, 1)
        lay.addWidget(card, 1)

        self.line_received.connect(self._append, QtCore.Qt.QueuedConnection)
        tail = get_tail()
        for line in tail.snapshot()[-500:]:
            m = _LEVEL_RE.search(line)
            self._lines.append((m.group(1) if m else "INFO", line))
        self._rebuild()
        self._listener = lambda lvl, msg: self.line_received.emit(lvl, msg)
        tail.add_listener(self._listener)

    def shutdown(self) -> None:
        get_tail().remove_listener(self._listener)

    def _min_rank(self) -> int:
        return {0: 0, 1: 30, 2: 40}[self.level.currentIndex()]

    def _accept(self, lvl: str, msg: str) -> bool:
        if _LEVEL_RANK.get(lvl, 20) < self._min_rank():
            return False
        q = self.search.text().strip().lower()
        return not q or q in msg.lower()

    def _rebuild(self) -> None:
        self.view.setPlainText("\n".join(m for lvl, m in self._lines if self._accept(lvl, m)))
        self.view.moveCursor(QtGui.QTextCursor.End)

    @QtCore.Slot(str, str)
    def _append(self, lvl: str, msg: str) -> None:
        self._lines.append((lvl, msg))
        if lvl in ("ERROR", "CRITICAL") and not self.isVisible():
            self._unseen_errors += 1
            self.error_count_changed.emit(self._unseen_errors)
        if not self._accept(lvl, msg):
            return
        sb = self.view.verticalScrollBar()
        self.view.appendPlainText(msg)
        if self.follow.isChecked():
            sb.setValue(sb.maximum())

    def clear(self) -> None:
        self._lines.clear()
        self.view.clear()

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        if self._unseen_errors:
            self._unseen_errors = 0
            self.error_count_changed.emit(0)
