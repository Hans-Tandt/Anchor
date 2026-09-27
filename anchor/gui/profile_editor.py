"""Profile editor dialog — configure sources, destinations, exclusions, options."""
from __future__ import annotations

import os
from typing import List, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from ..core.profile import BackupProfile, DestinationConfig
from ..destinations import test_destination
from ..drives import list_drives


# --- Destination dialog ------------------------------------------------------

class DestinationDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, cfg: Optional[DestinationConfig] = None):
        super().__init__(parent)
        self.setWindowTitle("Destination")
        self.setMinimumWidth(520)
        self.cfg = cfg or DestinationConfig()

        layout = QtWidgets.QFormLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        self.kind = QtWidgets.QComboBox()
        self.kind.addItems(["Local / USB / UNC", "OneDrive folder", "SFTP (QNAP / NAS remote)", "WebDAV"])
        layout.addRow("Type:", self.kind)

        self.label = QtWidgets.QLineEdit()
        self.label.setPlaceholderText("Friendly name (optional)")
        layout.addRow("Label:", self.label)

        # Local path row
        self.path = QtWidgets.QLineEdit()
        path_row = QtWidgets.QHBoxLayout()
        path_row.addWidget(self.path)
        browse_btn = QtWidgets.QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse)
        path_row.addWidget(browse_btn)
        self.path_widget = QtWidgets.QWidget(); self.path_widget.setLayout(path_row)
        layout.addRow("Folder path:", self.path_widget)

        # Drive suggestions
        self.drive_combo = QtWidgets.QComboBox()
        self.drive_combo.addItem("(pick a detected drive)", "")
        for d in list_drives():
            free_gb = d.free_bytes / (1024**3) if d.free_bytes else 0
            total_gb = d.total_bytes / (1024**3) if d.total_bytes else 0
            text = f"{d.letter}  {d.label}  [{d.drive_type}]  {free_gb:.0f}/{total_gb:.0f} GB free"
            self.drive_combo.addItem(text, d.letter)
        self.drive_combo.currentIndexChanged.connect(self._pick_drive)
        layout.addRow("Detected drives:", self.drive_combo)

        # Remote group (SFTP / WebDAV)
        self.remote_box = QtWidgets.QGroupBox("Remote settings")
        rb = QtWidgets.QFormLayout(self.remote_box)
        self.host = QtWidgets.QLineEdit(); self.host.setPlaceholderText("e.g. qnap.mydomain.com")
        self.port = QtWidgets.QSpinBox(); self.port.setRange(1, 65535); self.port.setValue(22)
        self.username = QtWidgets.QLineEdit()
        self.password = QtWidgets.QLineEdit(); self.password.setEchoMode(QtWidgets.QLineEdit.Password)
        self.password.setPlaceholderText("Will be saved to Windows Credential Manager")
        self.remote_path = QtWidgets.QLineEdit(); self.remote_path.setPlaceholderText("/share/Backup")
        self.use_https = QtWidgets.QCheckBox("Use HTTPS"); self.use_https.setChecked(True)
        self.verify_tls = QtWidgets.QCheckBox("Verify TLS certificate"); self.verify_tls.setChecked(True)

        rb.addRow("Host:", self.host)
        rb.addRow("Port:", self.port)
        rb.addRow("Username:", self.username)
        rb.addRow("Password:", self.password)
        rb.addRow("Remote path:", self.remote_path)
        rb.addRow(self.use_https)
        rb.addRow(self.verify_tls)
        layout.addRow(self.remote_box)

        # Buttons
        btns = QtWidgets.QHBoxLayout()
        self.test_btn = QtWidgets.QPushButton("Test connection")
        self.test_btn.clicked.connect(self._test)
        btns.addWidget(self.test_btn)
        btns.addStretch(1)
        cancel_btn = QtWidgets.QPushButton("Cancel"); cancel_btn.clicked.connect(self.reject)
        ok_btn = QtWidgets.QPushButton("Save"); ok_btn.setObjectName("primary"); ok_btn.clicked.connect(self._accept)
        btns.addWidget(cancel_btn); btns.addWidget(ok_btn)
        layout.addRow(btns)

        self.kind.currentIndexChanged.connect(self._kind_changed)
        self._load_from_cfg(self.cfg)
        self._kind_changed()

    # --- helpers ---------------------------------------------------------

    def _kind_idx_to_str(self, idx: int) -> str:
        return ["local", "local", "sftp", "webdav"][idx]

    def _kind_str_to_idx(self, k: str) -> int:
        return {"local": 0, "sftp": 2, "webdav": 3}.get(k, 0)

    def _load_from_cfg(self, c: DestinationConfig) -> None:
        idx = self._kind_str_to_idx(c.kind)
        # OneDrive heuristic: a local kind whose path contains "OneDrive"
        if c.kind == "local" and "onedrive" in (c.path or "").lower():
            idx = 1
        self.kind.setCurrentIndex(idx)
        self.label.setText(c.label)
        self.path.setText(c.path)
        self.host.setText(c.host)
        self.port.setValue(c.port or 22)
        self.username.setText(c.username)
        self.remote_path.setText(c.remote_path)
        self.use_https.setChecked(c.use_https)
        self.verify_tls.setChecked(c.verify_tls)

    def _kind_changed(self) -> None:
        idx = self.kind.currentIndex()
        is_local = idx in (0, 1)
        self.path_widget.setEnabled(is_local)
        self.drive_combo.setEnabled(idx == 0)
        self.remote_box.setVisible(idx in (2, 3))
        # Sensible default port
        if idx == 2:
            self.port.setValue(22)
        elif idx == 3:
            self.port.setValue(443 if self.use_https.isChecked() else 80)

        if idx == 1 and not self.path.text():
            # Suggest the user's OneDrive folder
            od = os.environ.get("OneDrive") or os.environ.get("OneDriveCommercial")
            if od:
                self.path.setText(os.path.join(od, "Backups"))

    def _browse(self) -> None:
        start = self.path.text() or os.path.expanduser("~")
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose destination folder", start)
        if d:
            self.path.setText(d)

    def _pick_drive(self, i: int) -> None:
        letter = self.drive_combo.itemData(i)
        if letter:
            self.path.setText(os.path.join(letter, "Backups"))

    def _build_cfg(self) -> DestinationConfig:
        idx = self.kind.currentIndex()
        c = DestinationConfig(
            id=self.cfg.id,
            kind=self._kind_idx_to_str(idx),
            label=self.label.text().strip(),
            path=self.path.text().strip(),
            host=self.host.text().strip(),
            port=int(self.port.value()),
            username=self.username.text().strip(),
            remote_path=self.remote_path.text().strip() or "/",
            use_https=self.use_https.isChecked(),
            verify_tls=self.verify_tls.isChecked(),
        )
        return c

    def _save_password(self, cfg: DestinationConfig) -> None:
        pw = self.password.text()
        if not pw or cfg.kind == "local":
            return
        try:
            import keyring  # type: ignore
            keyring.set_password("Anchor", cfg.id, pw)
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self, "Password not saved",
                f"Could not save password to Windows Credential Manager: {e}\n"
                "Install with: pip install keyring"
            )

    def _test(self) -> None:
        cfg = self._build_cfg()
        if cfg.kind != "local":
            self._save_password(cfg)
        err = test_destination(cfg, password=self.password.text() or None)
        if err:
            QtWidgets.QMessageBox.warning(self, "Connection failed", err)
        else:
            QtWidgets.QMessageBox.information(self, "Success", "Destination is reachable.")

    def _accept(self) -> None:
        cfg = self._build_cfg()
        if cfg.kind == "local" and not cfg.path:
            QtWidgets.QMessageBox.warning(self, "Missing path", "Please choose a folder.")
            return
        if cfg.kind in ("sftp", "webdav") and not cfg.host:
            QtWidgets.QMessageBox.warning(self, "Missing host", "Please enter the server host.")
            return
        self._save_password(cfg)
        self.cfg = cfg
        self.accept()


# --- Profile editor ----------------------------------------------------------

class ProfileEditor(QtWidgets.QDialog):
    def __init__(self, parent=None, profile: Optional[BackupProfile] = None):
        super().__init__(parent)
        self.setWindowTitle("Backup Profile")
        self.resize(720, 640)
        self.profile = profile or BackupProfile()

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18); root.setSpacing(12)

        # Name
        name_row = QtWidgets.QHBoxLayout()
        name_row.addWidget(QtWidgets.QLabel("Name:"))
        self.name_edit = QtWidgets.QLineEdit(self.profile.name)
        name_row.addWidget(self.name_edit, 1)
        root.addLayout(name_row)

        tabs = QtWidgets.QTabWidget()
        root.addWidget(tabs, 1)

        # --- Sources tab ---
        sources_w = QtWidgets.QWidget()
        sl = QtWidgets.QVBoxLayout(sources_w)
        self.sources_list = QtWidgets.QListWidget()
        for s in self.profile.sources:
            self.sources_list.addItem(s)
        sl.addWidget(self.sources_list, 1)
        sbtns = QtWidgets.QHBoxLayout()
        add_folder = QtWidgets.QPushButton("Add folder...")
        add_folder.clicked.connect(self._add_source_folder)
        add_file = QtWidgets.QPushButton("Add file...")
        add_file.clicked.connect(self._add_source_file)
        rm_src = QtWidgets.QPushButton("Remove")
        rm_src.clicked.connect(self._remove_source)
        sbtns.addWidget(add_folder); sbtns.addWidget(add_file); sbtns.addWidget(rm_src); sbtns.addStretch(1)
        sl.addLayout(sbtns)
        tabs.addTab(sources_w, "Sources")

        # --- Destinations tab ---
        dest_w = QtWidgets.QWidget()
        dl = QtWidgets.QVBoxLayout(dest_w)
        self.dest_list = QtWidgets.QListWidget()
        for d in self.profile.destinations:
            self.dest_list.addItem(d.display())
        dl.addWidget(self.dest_list, 1)
        self._destinations: List[DestinationConfig] = list(self.profile.destinations)
        dbtns = QtWidgets.QHBoxLayout()
        add_d = QtWidgets.QPushButton("Add..."); add_d.clicked.connect(self._add_dest)
        edit_d = QtWidgets.QPushButton("Edit..."); edit_d.clicked.connect(self._edit_dest)
        rm_d = QtWidgets.QPushButton("Remove"); rm_d.clicked.connect(self._remove_dest)
        dbtns.addWidget(add_d); dbtns.addWidget(edit_d); dbtns.addWidget(rm_d); dbtns.addStretch(1)
        dl.addLayout(dbtns)
        tabs.addTab(dest_w, "Destinations")

        # --- Exclusions tab ---
        ex_w = QtWidgets.QWidget()
        el = QtWidgets.QVBoxLayout(ex_w)
        el.addWidget(QtWidgets.QLabel("File/folder patterns to skip (one per line, glob syntax):"))
        self.excludes_edit = QtWidgets.QPlainTextEdit()
        self.excludes_edit.setPlainText("\n".join(self.profile.exclude_globs))
        el.addWidget(self.excludes_edit, 1)
        tabs.addTab(ex_w, "Exclusions")

        # --- Options tab ---
        opt_w = QtWidgets.QWidget()
        ol = QtWidgets.QFormLayout(opt_w)
        self.verify_hash = QtWidgets.QCheckBox("Verify with SHA-256 hashes (slower, bulletproof)")
        self.verify_hash.setChecked(self.profile.verify_with_hash)
        self.mirror_del = QtWidgets.QCheckBox(
            "Mirror deletions (remove files from destination when deleted from source)"
        )
        self.mirror_del.setChecked(self.profile.mirror_deletions)

        # Safety cap for mirror-delete: abort if a run would remove more than
        # this fraction of known files (e.g. a source went missing). Lives in
        # an indented row so it visually belongs to the checkbox above.
        cap_row = QtWidgets.QHBoxLayout()
        cap_row.setContentsMargins(24, 0, 0, 0)
        self.mirror_cap = QtWidgets.QSpinBox()
        self.mirror_cap.setRange(0, 100)
        self.mirror_cap.setSuffix(" %")
        self.mirror_cap.setValue(self.profile.mirror_max_delete_pct)
        self.mirror_cap.setToolTip(
            "Abort mirror-delete if it would remove more than this percent of\n"
            "the known files at a destination. Set to 0 to disable the cap.\n"
            "Recommended: 25%."
        )
        cap_label = QtWidgets.QLabel("Safety cap — abort mirror-delete above:")
        cap_row.addWidget(cap_label)
        cap_row.addWidget(self.mirror_cap)
        cap_row.addStretch(1)
        cap_wrap = QtWidgets.QWidget(); cap_wrap.setLayout(cap_row)

        def _sync_cap_enabled() -> None:
            on = self.mirror_del.isChecked()
            cap_label.setEnabled(on)
            self.mirror_cap.setEnabled(on)
        self.mirror_del.toggled.connect(lambda _=False: _sync_cap_enabled())
        _sync_cap_enabled()

        # Versioning: keep N previous copies of each file. When > 0, the engine
        # archives the file being overwritten (or mirror-deleted) into a
        # _anchor_versions subtree before writing, then prunes to this count.
        self.keep_versions = QtWidgets.QSpinBox()
        self.keep_versions.setRange(0, 999)
        self.keep_versions.setValue(self.profile.keep_versions)
        self.keep_versions.setToolTip(
            "Number of previous versions to keep per file under _anchor_versions/.\n"
            "0 disables versioning (overwrites are lost — original Anchor behavior).\n"
            "Recommended: 5 for personal use; 10–20 for source code."
        )

        self.preserve_meta = QtWidgets.QCheckBox("Preserve file timestamps and metadata")
        self.preserve_meta.setChecked(self.profile.preserve_metadata)
        self.follow_links = QtWidgets.QCheckBox("Follow symbolic links")
        self.follow_links.setChecked(self.profile.follow_symlinks)
        # Flat layout: files go straight into the destination root with no
        # per-source subfolder. Only valid for single-source profiles.
        self.flat_layout = QtWidgets.QCheckBox(
            "Place files directly in destination (no per-source subfolder)"
        )
        self.flat_layout.setChecked(self.profile.flat_destination_layout)
        # Post-copy verify: catch "engine thought it copied but bytes never
        # landed" scenarios. Adds time proportional to source size but
        # provides hard confirmation that source ↔ destination match.
        self.verify_after = QtWidgets.QCheckBox(
            "After backup, verify every source file is present at destination"
        )
        self.verify_after.setChecked(self.profile.verify_after_copy)
        self.verify_after.setToolTip(
            "Re-walks the source and stats every file at the destination,\n"
            "reporting any that are missing or have the wrong size. Highly\n"
            "recommended — catches silent failures."
        )
        self.flat_layout.setToolTip(
            "OFF (default): files go to <destination>/<source-label>/...\n"
            "ON: files go directly into <destination>/...\n\n"
            "Only valid for single-source profiles — multiple sources would\n"
            "collide. Turning this on for an existing profile means the next\n"
            "backup will re-copy everything to the new layout."
        )
        ol.addRow(self.verify_hash)
        ol.addRow(self.mirror_del)
        ol.addRow(cap_wrap)
        ol.addRow("Keep previous versions:", self.keep_versions)
        ol.addRow(self.flat_layout)
        ol.addRow(self.verify_after)
        ol.addRow(self.preserve_meta)
        ol.addRow(self.follow_links)
        tabs.addTab(opt_w, "Options")

        # Bottom buttons
        bot = QtWidgets.QHBoxLayout()
        bot.addStretch(1)
        cancel = QtWidgets.QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        save = QtWidgets.QPushButton("Save profile"); save.setObjectName("primary")
        save.clicked.connect(self._accept)
        bot.addWidget(cancel); bot.addWidget(save)
        root.addLayout(bot)

    # --- handlers --------------------------------------------------------

    def _add_source_folder(self) -> None:
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Pick a folder to back up")
        if d:
            self.sources_list.addItem(d)

    def _add_source_file(self) -> None:
        f, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Pick a file to back up")
        if f:
            self.sources_list.addItem(f)

    def _remove_source(self) -> None:
        for it in self.sources_list.selectedItems():
            self.sources_list.takeItem(self.sources_list.row(it))

    def _add_dest(self) -> None:
        dlg = DestinationDialog(self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._destinations.append(dlg.cfg)
            self.dest_list.addItem(dlg.cfg.display())

    def _edit_dest(self) -> None:
        row = self.dest_list.currentRow()
        if row < 0:
            return
        dlg = DestinationDialog(self, self._destinations[row])
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._destinations[row] = dlg.cfg
            self.dest_list.item(row).setText(dlg.cfg.display())

    def _remove_dest(self) -> None:
        row = self.dest_list.currentRow()
        if row < 0:
            return
        self._destinations.pop(row)
        self.dest_list.takeItem(row)

    def _accept(self) -> None:
        name = self.name_edit.text().strip() or "Unnamed"
        sources = [self.sources_list.item(i).text() for i in range(self.sources_list.count())]
        excludes = [l.strip() for l in self.excludes_edit.toPlainText().splitlines() if l.strip()]
        self.profile.name = name
        self.profile.sources = sources
        self.profile.destinations = list(self._destinations)
        self.profile.exclude_globs = excludes
        self.profile.verify_with_hash = self.verify_hash.isChecked()
        self.profile.mirror_deletions = self.mirror_del.isChecked()
        self.profile.mirror_max_delete_pct = int(self.mirror_cap.value())
        self.profile.keep_versions = int(self.keep_versions.value())
        # Guard: flat layout + multiple sources is invalid. Warn and refuse
        # to save until the user resolves it.
        if self.flat_layout.isChecked() and len(sources) > 1:
            QtWidgets.QMessageBox.warning(
                self, "Flat layout needs a single source",
                "'Place files directly in destination' is only safe with one "
                "source folder, otherwise files from different sources would "
                "overwrite each other.\n\n"
                "Either uncheck that option or reduce the Sources list to one.",
            )
            return
        self.profile.flat_destination_layout = self.flat_layout.isChecked()
        self.profile.verify_after_copy = self.verify_after.isChecked()
        self.profile.preserve_metadata = self.preserve_meta.isChecked()
        self.profile.follow_symlinks = self.follow_links.isChecked()
        self.accept()
