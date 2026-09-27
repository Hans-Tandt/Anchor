"""Dialog showing the list of files that failed or were skipped with errors
during the most recent backup or verify run.

Kept deliberately simple: read-only list + export-to-CSV. The point is that
the user can SEE what went wrong without scrolling the log viewer.
"""
from __future__ import annotations

import csv
from datetime import datetime
from typing import List

from PySide6 import QtCore, QtWidgets


class IssuesDialog(QtWidgets.QDialog):
    """Show a list of error strings in a copy-friendly table."""

    def __init__(self, parent, title: str, errors: List[str]):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 460)
        self._errors = list(errors)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QtWidgets.QLabel(
            f"{len(self._errors)} issue(s) recorded during the last run."
        )
        header.setObjectName("h2")
        layout.addWidget(header)

        self.table = QtWidgets.QTableWidget(len(self._errors), 1)
        self.table.setHorizontalHeaderLabels(["Message"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        for i, msg in enumerate(self._errors):
            it = QtWidgets.QTableWidgetItem(msg)
            it.setToolTip(msg)
            self.table.setItem(i, 0, it)
        layout.addWidget(self.table, 1)

        btns = QtWidgets.QHBoxLayout()
        export_btn = QtWidgets.QPushButton("Export to CSV…")
        export_btn.clicked.connect(self._export)
        copy_btn = QtWidgets.QPushButton("Copy all")
        copy_btn.clicked.connect(self._copy_all)
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btns.addWidget(export_btn)
        btns.addWidget(copy_btn)
        btns.addStretch(1)
        btns.addWidget(close_btn)
        layout.addLayout(btns)

    def _export(self) -> None:
        default = f"anchor-issues-{datetime.now():%Y%m%d-%H%M%S}.csv"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export issues", default, "CSV (*.csv);;All files (*)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["#", "message"])
                for i, m in enumerate(self._errors, 1):
                    w.writerow([i, m])
        except OSError as e:
            QtWidgets.QMessageBox.warning(self, "Export failed", str(e))

    def _copy_all(self) -> None:
        QtWidgets.QApplication.clipboard().setText("\n".join(self._errors))
