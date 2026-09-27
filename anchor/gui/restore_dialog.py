"""Restore dialog — browse a destination, pick a file (and optionally a
specific archived version), restore to original or alternate location.

Design:
  +-------------------------------------------------------------+
  | Destination: [QNAP via SFTP        v]                       |
  +--------------------------+----------------------------------+
  | Files at destination     |  Versions of selected file       |
  | ▼ C__Users_<you>_Docs    |   ● Current at destination       |
  |    file1.txt             |   ○ 20260520T143005 (2 days ago) |
  |    project/              |   ○ 20260519T112201              |
  |       readme.md          |                                  |
  | ▼ E__Photos              |                                  |
  |    ...                   |                                  |
  +--------------------------+----------------------------------+
  | [Restore to original location]  [Restore to folder...]      |
  |                                              [Close]        |
  +-------------------------------------------------------------+
"""
from __future__ import annotations

import os
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from PySide6 import QtCore, QtGui, QtWidgets

from ..core.profile import BackupProfile, DestinationConfig
from ..destinations import open_destination
from ..destinations.base import Destination, DestinationError, FileVersion


# Sentinel for "current file at destination" (i.e., not a specific archived
# version). Distinct value, not a FileVersion.
_CURRENT_SENTINEL = object()


# --- Worker for the actual restore copy --------------------------------------

class _RestoreWorker(QtCore.QThread):
    """Run the file-by-file download from destination to target directory.

    Re-opens the destination on its own thread so the connection isn't shared
    with the dialog's connection (paramiko / webdavclient3 don't promise
    thread-safety on a single client).
    """

    progress = QtCore.Signal(int, int, str)   # done, total, current_file
    finished_ok = QtCore.Signal(int, int)     # restored_ok, restored_failed
    finished_err = QtCore.Signal(str)

    def __init__(
        self,
        dest_cfg: DestinationConfig,
        preserve_metadata: bool,
        jobs: List[Tuple[str, str, str]],
        # Each job: (archive_rel_or_current_rel, target_abs_path, label_for_progress)
        parent=None,
    ):
        super().__init__(parent)
        self.dest_cfg = dest_cfg
        self.preserve_metadata = preserve_metadata
        self.jobs = jobs
        self._cancel = threading.Event()

    def request_cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:  # noqa: D401
        try:
            dest = open_destination(self.dest_cfg, preserve_metadata=self.preserve_metadata)
            dest.connect()
        except DestinationError as e:
            self.finished_err.emit(str(e))
            return

        ok = failed = 0
        try:
            for i, (src_rel, target, label) in enumerate(self.jobs):
                if self._cancel.is_set():
                    break
                self.progress.emit(i, len(self.jobs), label)
                try:
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    dest.get_file(src_rel, target)
                    ok += 1
                except (DestinationError, OSError) as e:
                    failed += 1
                    # The IssuesDialog isn't wired into restore yet — log via
                    # the parent worker's signal channel instead.
                    self.progress.emit(i, len(self.jobs), f"FAILED {label}: {e}")
        finally:
            try:
                dest.close()
            except Exception:
                pass
        self.finished_ok.emit(ok, failed)


# --- The dialog --------------------------------------------------------------

class RestoreDialog(QtWidgets.QDialog):
    def __init__(self, parent, profile: BackupProfile):
        super().__init__(parent)
        self.setWindowTitle(f"Restore from '{profile.name}'")
        self.resize(960, 640)
        self.profile = profile
        self.dest: Optional[Destination] = None
        self.dest_cfg: Optional[DestinationConfig] = None
        self._worker: Optional[_RestoreWorker] = None
        # rel_path -> [FileVersion...] cache for the right-hand list
        self._versions_cache: Dict[str, List[FileVersion]] = {}

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14); root.setSpacing(10)

        # Destination picker
        dest_row = QtWidgets.QHBoxLayout()
        dest_row.addWidget(QtWidgets.QLabel("Destination:"))
        self.dest_combo = QtWidgets.QComboBox()
        for d in self.profile.destinations:
            self.dest_combo.addItem(d.display(), d.id)
        dest_row.addWidget(self.dest_combo, 1)
        reload_btn = QtWidgets.QPushButton("Reload")
        reload_btn.clicked.connect(self._reload)
        dest_row.addWidget(reload_btn)
        root.addLayout(dest_row)

        # Split: file tree | versions list
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        root.addWidget(split, 1)

        left = QtWidgets.QWidget(); ll = QtWidgets.QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0); ll.setSpacing(4)
        ll.addWidget(QtWidgets.QLabel("Files at destination"))
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["Path", "Size", "Modified"])
        self.tree.setColumnWidth(0, 380)
        self.tree.setUniformRowHeights(True)
        self.tree.itemSelectionChanged.connect(self._on_file_selected)
        ll.addWidget(self.tree, 1)
        split.addWidget(left)

        right = QtWidgets.QWidget(); rl = QtWidgets.QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(4)
        rl.addWidget(QtWidgets.QLabel("Versions of selected file"))
        self.versions_list = QtWidgets.QListWidget()
        self.versions_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        rl.addWidget(self.versions_list, 1)
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 1)

        # Bottom actions
        bot = QtWidgets.QHBoxLayout()
        self.restore_original_btn = QtWidgets.QPushButton("Restore to original location…")
        self.restore_original_btn.clicked.connect(lambda: self._restore(to_alt=False))
        self.restore_alt_btn = QtWidgets.QPushButton("Restore to folder…")
        self.restore_alt_btn.clicked.connect(lambda: self._restore(to_alt=True))
        self.cancel_btn = QtWidgets.QPushButton("Cancel restore")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_restore)
        self.close_btn = QtWidgets.QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        bot.addWidget(self.restore_original_btn)
        bot.addWidget(self.restore_alt_btn)
        bot.addWidget(self.cancel_btn)
        bot.addStretch(1)
        bot.addWidget(self.close_btn)
        root.addLayout(bot)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setObjectName("muted")
        root.addWidget(self.status_label)

        self.dest_combo.currentIndexChanged.connect(self._reload)
        self._reload()

    # --- Loading ---------------------------------------------------------

    def _reload(self) -> None:
        # Close any previous connection
        if self.dest is not None:
            try:
                self.dest.close()
            except Exception:
                pass
            self.dest = None
        self.tree.clear()
        self.versions_list.clear()
        self._versions_cache.clear()

        idx = self.dest_combo.currentIndex()
        if idx < 0:
            return
        self.dest_cfg = self.profile.destinations[idx]

        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            self.dest = open_destination(self.dest_cfg, preserve_metadata=self.profile.preserve_metadata)
            self.dest.connect()
        except DestinationError as e:
            QtWidgets.QApplication.restoreOverrideCursor()
            QtWidgets.QMessageBox.warning(self, "Cannot open destination", str(e))
            return

        try:
            files: List[str] = []
            for rel in self.dest.iter_files():
                if rel.endswith(".bkp.tmp"):
                    continue
                files.append(rel)
            self._populate_tree(files)
            self.status_label.setText(f"{len(files)} file(s) at this destination.")
        except (NotImplementedError, DestinationError) as e:
            QtWidgets.QMessageBox.warning(self, "Cannot list files", str(e))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _populate_tree(self, files: List[str]) -> None:
        """Group files into a tree by forward-slash separators."""
        # Build a nested dict of path components, sorted by name for stability.
        root_map: Dict[str, dict] = {}
        sizes: Dict[str, int] = {}
        mtimes: Dict[str, Optional[float]] = {}
        # We'll fetch size/mtime only for shown files when the user expands —
        # but for a small file count we can stat eagerly. Keep it lazy here
        # to keep the dialog fast on huge destinations.
        for rel in files:
            parts = rel.split("/")
            cur = root_map
            for p in parts[:-1]:
                cur = cur.setdefault(p, {})
            cur.setdefault("__files__", []).append(parts[-1])

        def _add(parent: QtWidgets.QTreeWidgetItem, node: dict, prefix: str) -> None:
            # Subdirectories first (sorted)
            for name in sorted(k for k in node if k != "__files__"):
                child = QtWidgets.QTreeWidgetItem(parent, [name + "/"])
                child.setData(0, QtCore.Qt.UserRole, None)  # folder marker
                _add(child, node[name], f"{prefix}{name}/")
            for fname in sorted(node.get("__files__", [])):
                full_rel = f"{prefix}{fname}"
                it = QtWidgets.QTreeWidgetItem(parent, [fname, "", ""])
                it.setData(0, QtCore.Qt.UserRole, full_rel)
                # Lazily fill size/mtime when the row scrolls into view? Simpler:
                # fill on demand when selected (avoids 1000s of stats at load).

        # Top level
        for name in sorted(k for k in root_map if k != "__files__"):
            top = QtWidgets.QTreeWidgetItem(self.tree, [name + "/"])
            top.setData(0, QtCore.Qt.UserRole, None)
            _add(top, root_map[name], f"{name}/")
        for fname in sorted(root_map.get("__files__", [])):
            it = QtWidgets.QTreeWidgetItem(self.tree, [fname, "", ""])
            it.setData(0, QtCore.Qt.UserRole, fname)

    # --- Selection / versions list --------------------------------------

    def _selected_rel(self) -> Optional[str]:
        items = self.tree.selectedItems()
        if not items:
            return None
        return items[0].data(0, QtCore.Qt.UserRole)

    def _on_file_selected(self) -> None:
        self.versions_list.clear()
        rel = self._selected_rel()
        if not rel or not self.dest:
            return
        # Always show "Current at destination" first.
        current_stat = None
        try:
            current_stat = self.dest.stat(rel)
        except Exception:
            pass
        cur_item = QtWidgets.QListWidgetItem("● Current at destination")
        if current_stat:
            sz = current_stat.size
            mt = (
                datetime.fromtimestamp(current_stat.mtime).strftime("%Y-%m-%d %H:%M")
                if current_stat.mtime else "?"
            )
            cur_item.setText(f"● Current at destination — {_human_size(sz)}, {mt}")
        cur_item.setData(QtCore.Qt.UserRole, _CURRENT_SENTINEL)
        self.versions_list.addItem(cur_item)

        versions = self._versions_cache.get(rel)
        if versions is None:
            try:
                versions = self.dest.list_versions(rel)
            except Exception:
                versions = []
            self._versions_cache[rel] = versions

        for v in versions:
            ts = _format_version_id(v.version_id)
            mt = (
                datetime.fromtimestamp(v.mtime).strftime("%Y-%m-%d %H:%M")
                if v.mtime else "?"
            )
            text = f"○ {ts} — {_human_size(v.size)}, archived at {mt}"
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, v)
            self.versions_list.addItem(item)

        # Default selection: current
        self.versions_list.setCurrentRow(0)

    # --- Restore --------------------------------------------------------

    def _restore(self, to_alt: bool) -> None:
        rel = self._selected_rel()
        if not rel:
            QtWidgets.QMessageBox.information(
                self, "No file selected",
                "Pick a file in the tree on the left first.")
            return
        chosen = self.versions_list.currentItem()
        if chosen is None:
            QtWidgets.QMessageBox.information(
                self, "No version selected",
                "Pick a version on the right (the current copy is selected by default).")
            return
        version_data = chosen.data(QtCore.Qt.UserRole)

        # Resolve source rel path: either the live file, or an archived version.
        if version_data is _CURRENT_SENTINEL:
            src_rel = rel
        elif isinstance(version_data, FileVersion):
            src_rel = version_data.archive_rel
        else:
            return

        # Resolve target.
        if to_alt:
            target_dir = QtWidgets.QFileDialog.getExistingDirectory(
                self, "Choose a folder to restore into",
            )
            if not target_dir:
                return
            # Strip the "<sub-label>/" prefix when restoring to an alternate dir
            # so users get back a sensible local tree (e.g. "Documents/file.txt"
            # not "C__Users_<you>_Documents/file.txt"). Best-effort: if the rel
            # path has no slash, keep it as-is.
            tail = rel.split("/", 1)[1] if "/" in rel else rel
            target = os.path.join(target_dir, tail.replace("/", os.sep))
        else:
            # Reconstruct the original absolute path from the sub-label:
            # "C__Users_<you>_Docs/foo/bar.txt" -> "C:\Users\<you>\Docs\foo\bar.txt"
            target = _reconstruct_original_path(rel)
            if not target:
                QtWidgets.QMessageBox.warning(
                    self, "Cannot reconstruct original path",
                    "The destination layout doesn't carry enough info to know "
                    "where this file originally lived. Use 'Restore to folder…' instead.",
                )
                return
            ok = QtWidgets.QMessageBox.question(
                self, "Confirm restore",
                f"Restore to original location?\n\n{target}\n\n"
                "Any existing file there will be overwritten.",
            )
            if ok != QtWidgets.QMessageBox.Yes:
                return

        label = os.path.basename(target)
        self._start_worker([(src_rel, target, label)])

    def _start_worker(self, jobs: List[Tuple[str, str, str]]) -> None:
        if not self.dest_cfg:
            return
        self._worker = _RestoreWorker(self.dest_cfg, self.profile.preserve_metadata, jobs, self)
        self._worker.progress.connect(self._on_worker_progress)
        self._worker.finished_ok.connect(self._on_worker_ok)
        self._worker.finished_err.connect(self._on_worker_err)
        self.restore_original_btn.setEnabled(False)
        self.restore_alt_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self._worker.start()

    def _cancel_restore(self) -> None:
        if self._worker:
            self._worker.request_cancel()
            self.status_label.setText("Cancelling…")

    def _on_worker_progress(self, done: int, total: int, label: str) -> None:
        self.status_label.setText(f"Restoring {done + 1}/{total}: {label}")

    def _on_worker_ok(self, ok: int, failed: int) -> None:
        self._worker = None
        self.restore_original_btn.setEnabled(True)
        self.restore_alt_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        msg = f"Restore complete: {ok} ok, {failed} failed."
        self.status_label.setText(msg)
        if failed:
            QtWidgets.QMessageBox.warning(self, "Restore finished with errors", msg)
        else:
            QtWidgets.QMessageBox.information(self, "Restore complete", msg)

    def _on_worker_err(self, msg: str) -> None:
        self._worker = None
        self.restore_original_btn.setEnabled(True)
        self.restore_alt_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.status_label.setText(f"Restore failed: {msg}")
        QtWidgets.QMessageBox.critical(self, "Restore failed", msg)

    # --- Cleanup --------------------------------------------------------

    def closeEvent(self, ev: QtGui.QCloseEvent) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.request_cancel()
            self._worker.wait(3000)
        if self.dest is not None:
            try:
                self.dest.close()
            except Exception:
                pass
        super().closeEvent(ev)


# --- Helpers -----------------------------------------------------------------

def _human_size(n: int) -> str:
    f = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if abs(f) < 1024 or u == "TB":
            return f"{f:.0f} {u}" if u == "B" else f"{f:.1f} {u}"
        f /= 1024
    return f"{f:.1f} TB"


def _format_version_id(vid: str) -> str:
    """Render `20260520T143005` → `2026-05-20 14:30:05`."""
    try:
        return f"{vid[0:4]}-{vid[4:6]}-{vid[6:8]} {vid[9:11]}:{vid[11:13]}:{vid[13:15]}"
    except Exception:
        return vid


def _reconstruct_original_path(rel: str) -> Optional[str]:
    """Best-effort inverse of walker.source_label().

    Sub-label conventions from walker.source_label():
       "C:\\Users\\<you>\\Docs"   -> "C__Users_<you>_Docs"
       "\\\\NAS\\share\\stuff"    -> "UNC_NAS_share_stuff"
    Everything after the first "/" in `rel` is the file's path relative to
    that root. We try to reverse the encoding well enough that the round-trip
    works for typical Windows paths.
    """
    if "/" not in rel:
        return None
    sub, tail = rel.split("/", 1)
    if sub.startswith("UNC_"):
        # "UNC_NAS_share_stuff" -> "\\NAS\share\stuff"
        return ("\\\\" + sub[4:].replace("_", "\\") + "\\"
                + tail.replace("/", "\\"))
    # Windows drive form: "C__Users_..." -> "C:\Users\..."
    if len(sub) >= 3 and sub[1:3] == "__":
        return sub[0] + ":\\" + sub[3:].replace("_", "\\") + "\\" + tail.replace("/", "\\")
    return None
