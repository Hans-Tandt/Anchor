"""Profile editor dialog — configure sources, destinations, exclusions, options."""
from __future__ import annotations

import os
from typing import List, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from ..core.profile import BackupProfile, DestinationConfig
from ..destinations import test_destination
from ..drives import list_drives


# --- Exclusion presets -------------------------------------------------------
#
# Each category is (title, items). Each item is (label, patterns, kind, tip):
#   kind="file" -> saved into BackupProfile.exclude_globs (matched by fnmatch
#                  on file basename and on the file's rel-path)
#   kind="dir"  -> saved into BackupProfile.exclude_dirs (matched by basename
#                  equality in the walker; absolute paths also supported via
#                  the folder-exclusions list below the presets).
#
# A preset ticks when ALL of its patterns are present in either exclusion
# list of the profile (the "right" list by kind, or the other one — old
# profiles that pre-date the split still work). On save, the preset's
# patterns are routed into the correct list by kind.
EXCLUSION_PRESETS: List = [
    ("System junk", [
        ("Thumbs.db", ["Thumbs.db"], "file", "Windows thumbnail cache"),
        (".DS_Store", [".DS_Store"], "file", "macOS folder metadata"),
        ("Office lock files (~$*)", ["~$*"], "file",
         "Office/Word lock files created while a document is open"),
        ("Temp files (*.tmp)", ["*.tmp"], "file", "Generic temp files"),
        ("Log files (*.log)", ["*.log"], "file", "Log files"),
        ("Swap files (*.swp)", ["*.swp"], "file", "Vim/Neovim swap files"),
        ("Backup files (*.bak)", ["*.bak"], "file", "Generic .bak files"),
    ]),
    ("Build and cache folders", [
        ("node_modules", ["node_modules"], "dir",
         "Node.js dependencies — regenerate with `npm install`"),
        ("__pycache__", ["__pycache__"], "dir", "Python bytecode cache"),
        (".venv", [".venv"], "dir", "Python virtual environment"),
        ("venv", ["venv"], "dir", "Python virtual environment (alternative name)"),
        (".tox", [".tox"], "dir", "Tox test environments"),
        ("dist", ["dist"], "dir",
         "Generic build output — may match legitimate 'dist' folders you want to keep"),
        ("build", ["build"], "dir",
         "Generic build output — may match legitimate 'build' folders you want to keep"),
        ("target", ["target"], "dir",
         "Rust/Java build output — may match folders you want to keep"),
        (".gradle", [".gradle"], "dir", "Gradle cache"),
        (".next", [".next"], "dir", "Next.js build cache"),
        (".pytest_cache", [".pytest_cache"], "dir", "pytest cache"),
        (".mypy_cache", [".mypy_cache"], "dir", "mypy cache"),
    ]),
    ("IDE metadata", [
        (".idea", [".idea"], "dir", "JetBrains IDE project settings"),
        (".vscode", [".vscode"], "dir", "VS Code workspace settings"),
        (".vs", [".vs"], "dir", "Visual Studio IDE files"),
    ]),
    ("Version control  (⚠ dangerous)", [
        (".git", [".git"], "dir",
         "⚠ Git history — ticking this drops EVERY commit, branch and tag from your backup"),
        (".svn", [".svn"], "dir", "⚠ Subversion history"),
        (".hg", [".hg"], "dir", "⚠ Mercurial history"),
        (".bzr", [".bzr"], "dir", "⚠ Bazaar history"),
    ]),
]

_VCS_RISKY = {".git", ".svn", ".hg", ".bzr"}


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
        # Three sections, top to bottom:
        #   1. Preset grid — the common cases, one checkbox each.
        #   2. Folder exclusions — specific absolute folder paths to skip.
        #   3. Custom patterns — free-form glob textarea for anything else.
        # The red VCS warning banner sits below everything (not scrolled)
        # so it is always visible when a VCS preset is ticked or a VCS
        # name appears in the textarea or folder list.
        ex_w = QtWidgets.QWidget()
        ex_outer = QtWidgets.QVBoxLayout(ex_w)
        ex_outer.setContentsMargins(0, 0, 0, 0)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        inner = QtWidgets.QWidget()
        el = QtWidgets.QVBoxLayout(inner)

        # 1. Preset grid
        self._preset_checkboxes: List[QtWidgets.QCheckBox] = []
        for category, items in EXCLUSION_PRESETS:
            group = QtWidgets.QGroupBox(category)
            grid = QtWidgets.QGridLayout(group)
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(6)
            for i, (label, patterns, kind, tip) in enumerate(items):
                cb = QtWidgets.QCheckBox(label)
                cb.setToolTip(tip)
                cb.setProperty("patterns", list(patterns))
                cb.setProperty("kind", kind)
                grid.addWidget(cb, i // 3, i % 3)
                self._preset_checkboxes.append(cb)
            el.addWidget(group)

        # 2. Folder exclusions — specific absolute paths
        folder_group = QtWidgets.QGroupBox("Specific folders to skip (absolute paths)")
        fg = QtWidgets.QVBoxLayout(folder_group)
        self.folder_excludes_list = QtWidgets.QListWidget()
        self.folder_excludes_list.setToolTip(
            "Specific folders that should NEVER be backed up, by absolute path.\n"
            "Unlike the preset basenames (which match the folder by name anywhere\n"
            "in the source tree), these only match the one folder you pick."
        )
        fg.addWidget(self.folder_excludes_list, 1)
        fbtns = QtWidgets.QHBoxLayout()
        add_fex = QtWidgets.QPushButton("Add folder...")
        add_fex.clicked.connect(self._add_folder_exclude)
        rm_fex = QtWidgets.QPushButton("Remove")
        rm_fex.clicked.connect(self._remove_folder_exclude)
        fbtns.addWidget(add_fex); fbtns.addWidget(rm_fex); fbtns.addStretch(1)
        fg.addLayout(fbtns)
        el.addWidget(folder_group)

        # 3. Custom patterns (free-form)
        custom_label = QtWidgets.QLabel(
            "Custom patterns (advanced — glob syntax, one per line):"
        )
        el.addWidget(custom_label)
        self.excludes_edit = QtWidgets.QPlainTextEdit()
        self.excludes_edit.setPlaceholderText("e.g. *.iso, archive_*, oldstuff/*")
        self.excludes_edit.setMaximumHeight(100)
        el.addWidget(self.excludes_edit)

        scroll.setWidget(inner)
        ex_outer.addWidget(scroll, 1)

        # 4. VCS warning banner — sits below the scroll area so it is always
        # visible regardless of how far down the user has scrolled.
        self.excludes_warn = QtWidgets.QLabel()
        self.excludes_warn.setWordWrap(True)
        self.excludes_warn.setStyleSheet(
            "QLabel { background-color: #4a1a1a; color: #ffd0d0; "
            "border: 1px solid #a04040; padding: 8px; border-radius: 4px; }"
        )
        self.excludes_warn.setVisible(False)
        ex_outer.addWidget(self.excludes_warn)

        # Load current profile values into the UI
        self._load_exclusions_into_ui()

        # Wire warning refresh to every input
        for cb in self._preset_checkboxes:
            cb.toggled.connect(self._refresh_excludes_warning)
        self.excludes_edit.textChanged.connect(self._refresh_excludes_warning)
        self.folder_excludes_list.model().rowsInserted.connect(
            lambda *_: self._refresh_excludes_warning()
        )
        self.folder_excludes_list.model().rowsRemoved.connect(
            lambda *_: self._refresh_excludes_warning()
        )
        self._refresh_excludes_warning()

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
        # Confirm-before-copy: after the scan phase, the engine pauses and
        # the GUI shows a "Start copy" button instead of auto-proceeding.
        # Lets the user eyeball the "N files to copy" summary before any
        # write happens.
        self.confirm_copy = QtWidgets.QCheckBox(
            "Wait for me to confirm before copying"
        )
        self.confirm_copy.setChecked(self.profile.confirm_before_copy)
        self.confirm_copy.setToolTip(
            "When scanning finishes, pause and wait for you to click\n"
            "'Start copy' before anything is written to the destination.\n"
            "Off (default): copy starts automatically after a short pause."
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
        ol.addRow(self.confirm_copy)
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

    # --- exclusions helpers ---------------------------------------------

    def _add_folder_exclude(self) -> None:
        d = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Pick a folder to exclude from backups"
        )
        if not d:
            return
        # Avoid duplicates (case-insensitive on Windows)
        existing = {
            os.path.normcase(self.folder_excludes_list.item(i).text())
            for i in range(self.folder_excludes_list.count())
        }
        if os.path.normcase(d) in existing:
            return
        self.folder_excludes_list.addItem(d)

    def _remove_folder_exclude(self) -> None:
        for it in self.folder_excludes_list.selectedItems():
            self.folder_excludes_list.takeItem(self.folder_excludes_list.row(it))

    def _load_exclusions_into_ui(self) -> None:
        """Tick preset boxes, fill the folder list and the custom textarea
        from BackupProfile.exclude_globs / .exclude_dirs.

        A preset's pattern may live in either list (old profiles pre-date
        the split) — we look in both when deciding to tick, and remove the
        matched entries from the "leftover" pool so they don't also appear
        as duplicates in the textarea / folder list.
        """
        file_pats = list(self.profile.exclude_globs)
        dir_pats = list(self.profile.exclude_dirs)

        for cb in self._preset_checkboxes:
            patterns = cb.property("patterns") or []
            # all patterns must be present in SOME exclusion list
            if all((p in file_pats) or (p in dir_pats) for p in patterns):
                cb.setChecked(True)
                for p in patterns:
                    if p in file_pats:
                        file_pats.remove(p)
                    elif p in dir_pats:
                        dir_pats.remove(p)

        # Remaining dir_pats: absolute paths -> folder list;
        # basenames (plain names) -> keep in textarea so the user still sees
        # them. On save they'll be routed back to exclude_globs (fnmatch with
        # a literal pattern still matches the basename — behavior unchanged).
        leftover_text: List[str] = []
        for d in dir_pats:
            if os.path.isabs(d) or d.startswith("\\\\"):
                self.folder_excludes_list.addItem(d)
            else:
                leftover_text.append(d)
        leftover_text.extend(file_pats)
        self.excludes_edit.setPlainText("\n".join(leftover_text))

    def _refresh_excludes_warning(self) -> None:
        """Show the red VCS banner when the exclusion set names a VCS folder,
        no matter where it came from (preset, textarea or folder list)."""
        found: set = set()
        for cb in self._preset_checkboxes:
            if cb.isChecked():
                for p in (cb.property("patterns") or []):
                    if p in _VCS_RISKY:
                        found.add(p)
        for line in self.excludes_edit.toPlainText().splitlines():
            s = line.strip()
            if s in _VCS_RISKY:
                found.add(s)
        for i in range(self.folder_excludes_list.count()):
            # basename of an absolute path like D:/repo/.git also costs history
            name = os.path.basename(
                self.folder_excludes_list.item(i).text().rstrip("/\\")
            )
            if name in _VCS_RISKY:
                found.add(name)

        if found:
            names = ", ".join(sorted(found))
            self.excludes_warn.setText(
                "⚠  WARNING: " + names
                + " is in the exclusion list. The version-control history "
                "(commits, branches, tags) of your repositories will NOT "
                "be backed up. Untick the box above (or remove the line) "
                "if you want Anchor to protect your Git history."
            )
            self.excludes_warn.setVisible(True)
        else:
            self.excludes_warn.setVisible(False)

    def _collect_exclusions(self) -> tuple:
        """Return (exclude_globs, exclude_dirs) built from the UI state."""
        file_globs: List[str] = []
        dir_names: List[str] = []

        for cb in self._preset_checkboxes:
            if not cb.isChecked():
                continue
            kind = cb.property("kind")
            for p in (cb.property("patterns") or []):
                if kind == "file":
                    if p not in file_globs:
                        file_globs.append(p)
                else:
                    if p not in dir_names:
                        dir_names.append(p)

        for line in self.excludes_edit.toPlainText().splitlines():
            s = line.strip()
            if s and s not in file_globs:
                file_globs.append(s)

        for i in range(self.folder_excludes_list.count()):
            p = self.folder_excludes_list.item(i).text().strip()
            if p and p not in dir_names:
                dir_names.append(p)

        return file_globs, dir_names

    def _accept(self) -> None:
        name = self.name_edit.text().strip() or "Unnamed"
        sources = [self.sources_list.item(i).text() for i in range(self.sources_list.count())]
        file_globs, dir_names = self._collect_exclusions()
        self.profile.name = name
        self.profile.sources = sources
        self.profile.destinations = list(self._destinations)
        self.profile.exclude_globs = file_globs
        self.profile.exclude_dirs = dir_names
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
        self.profile.confirm_before_copy = self.confirm_copy.isChecked()
        self.profile.preserve_metadata = self.preserve_meta.isChecked()
        self.profile.follow_symlinks = self.follow_links.isChecked()
        self.accept()
