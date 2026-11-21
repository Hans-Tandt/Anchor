"""Backups page — the profile list (task-list style) plus the selected
profile's detail: header with command bar, stat tiles, live run card,
sources and destinations.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Dict, List, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from ...core.profile import BackupProfile, DestinationConfig
from ...drives import is_path_available
from .. import icons
from ..controller import RunController
from ..progress_widgets import CopyProgressDonut, PhaseStripWidget, VerifyBanner
from ..theme import color, theme_manager
from ..widgets import (
    Card, EmptyState, SmoothProgressBar, StatTile, StatusPill, button, hline,
    human_bytes, human_time, icon_label, label, tool_button,
)

_PHASE_KEY = {"scanning": "scan", "scan-done": "scan", "copying": "copy", "verifying": "verify"}


def relative_time(iso: str) -> str:
    if not iso:
        return "Never run"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    secs = (datetime.now() - dt).total_seconds()
    if secs < 0:
        return dt.strftime("%Y-%m-%d %H:%M")
    if secs < 60:
        return "Just now"
    if secs < 3600:
        m = int(secs // 60)
        return f"{m} minute{'s' if m != 1 else ''} ago"
    if secs < 86400:
        h = int(secs // 3600)
        return f"{h} hour{'s' if h != 1 else ''} ago"
    d = int(secs // 86400)
    if d < 14:
        return f"{d} day{'s' if d != 1 else ''} ago"
    return dt.strftime("%Y-%m-%d")


def dest_icon(d: DestinationConfig) -> str:
    if d.kind == "sftp":
        return "server"
    if d.kind == "webdav" or "onedrive" in (d.path or "").lower():
        return "cloud"
    return "drive"


def dest_available(d: DestinationConfig) -> Optional[bool]:
    """True/False for local paths, None (unknown) for remote destinations —
    probing a server every 5 seconds would be rude and slow."""
    if d.kind == "local":
        return is_path_available(d.path)
    return None


# ---------------------------------------------------------------------------
# Profile list item
# ---------------------------------------------------------------------------

class ProfileItem(QtWidgets.QWidget):
    def __init__(self, profile: BackupProfile, parent=None):
        super().__init__(parent)
        self.profile_id = profile.id
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(10, 9, 10, 9)
        lay.setSpacing(12)
        self.tile = QtWidgets.QLabel()
        self.tile.setFixedSize(36, 36)
        self.tile.setAlignment(QtCore.Qt.AlignCenter)
        lay.addWidget(self.tile)
        col = QtWidgets.QVBoxLayout()
        col.setSpacing(3)
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(6)
        self.name = label("")
        self.name.setStyleSheet("font-weight: 600;")
        top.addWidget(self.name, 1)
        self.dot = QtWidgets.QLabel()
        self.dot.setFixedSize(10, 10)
        top.addWidget(self.dot)
        col.addLayout(top)
        self.sub = label("", "caption")
        col.addWidget(self.sub)
        self.bar = SmoothProgressBar(height=3)
        self.bar.setVisible(False)
        col.addWidget(self.bar)
        lay.addLayout(col, 1)
        self._status = "never"
        self._running = False
        theme_manager.changed.connect(self._restyle)
        self.update_from(profile)

    def update_from(self, p: BackupProfile) -> None:
        self.name.setText(p.name)
        self.setToolTip(p.name)
        self._status = p.last_status
        self._kind_icon = dest_icon(p.destinations[0]) if p.destinations else "folder"
        if not self._running:
            n_src, n_dst = len(p.sources), len(p.destinations)
            self.sub.setText(
                f"{relative_time(p.last_run_iso)}  ·  {n_src} source{'s' if n_src != 1 else ''}"
                f" → {n_dst} dest{'s' if n_dst != 1 else ''}"
            )
        self._restyle()

    def set_running(self, running: bool, fraction: float = 0.0, text: str = "") -> None:
        self._running = running
        self.bar.setVisible(running)
        if running:
            self.bar.set_fraction(fraction)
            if text:
                self.sub.setText(text)
        self._restyle()

    def _restyle(self) -> None:
        c = color("accent_soft")
        self.tile.setStyleSheet(
            f"background: rgba({c.red()},{c.green()},{c.blue()},{c.alphaF():.2f}); border-radius: 8px;"
        )
        self.tile.setPixmap(icons.pixmap(getattr(self, "_kind_icon", "folder"), 18, "accent"))
        key = "accent" if self._running else {"ok": "ok", "warning": "warn", "error": "err"}.get(self._status, "text_disabled")
        self.dot.setStyleSheet(f"background: {color(key).name()}; border-radius: 5px;")
        self.dot.setToolTip("Running" if self._running else {
            "ok": "Last run OK", "warning": "Last run had warnings",
            "error": "Last run failed", "never": "Never run"}.get(self._status, ""))
        self.bar.set_chunk_color("accent")


# ---------------------------------------------------------------------------
# Path list card (sources / destinations)
# ---------------------------------------------------------------------------

class PathListCard(Card):
    def __init__(self, title: str, icon_name: str, parent=None):
        super().__init__(parent, padding=16, spacing=8)
        head = QtWidgets.QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(icon_label(icon_name, "text_secondary", 16))
        self.title = label(title)
        self.title.setStyleSheet("font-weight: 600;")
        head.addWidget(self.title)
        head.addStretch(1)
        self.pill = StatusPill("ok", "")
        head.addWidget(self.pill)
        self.lay.addLayout(head)
        self.rows = QtWidgets.QVBoxLayout()
        self.rows.setSpacing(2)
        self.lay.addLayout(self.rows)
        self.lay.addStretch(1)

    def clear(self) -> None:
        while self.rows.count():
            it = self.rows.takeAt(0)
            w = it.widget()
            if w is not None:
                # Hide now: deleteLater only runs on the next event-loop
                # pass, and until then the old row would paint underneath
                # the new one.
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def add_row(self, icon_name: str, text: str, state: Optional[bool], tooltip: str = "",
                note: str = "") -> None:
        row = QtWidgets.QWidget()
        rl = QtWidgets.QHBoxLayout(row)
        rl.setContentsMargins(4, 5, 4, 5)
        rl.setSpacing(10)
        ic_key = "text_muted" if state is not False else "err"
        rl.addWidget(icon_label(icon_name, ic_key, 16))
        t = label(text)
        t.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        t.setToolTip(tooltip or text)
        t.setMinimumWidth(10)
        t.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        rl.addWidget(t, 1)
        if note:
            rl.addWidget(label(note, "caption"))
        if state is True:
            rl.addWidget(icon_label("check-circle", "ok", 14))
        elif state is False:
            w = icon_label("warning", "err", 14)
            w.setToolTip("Not reachable right now")
            rl.addWidget(w)
        self.rows.addWidget(row)

    def add_placeholder(self, text: str) -> None:
        self.rows.addWidget(label(text, "muted"))


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

class DashboardPage(QtWidgets.QWidget):
    new_profile_requested = QtCore.Signal()
    edit_requested = QtCore.Signal()
    delete_requested = QtCore.Signal()
    schedule_requested = QtCore.Signal()
    restore_requested = QtCore.Signal()
    issues_requested = QtCore.Signal()
    run_requested = QtCore.Signal()
    verify_requested = QtCore.Signal()
    group_run_requested = QtCore.Signal(list)      # [BackupProfile]
    current_changed = QtCore.Signal(object)        # BackupProfile | None

    def __init__(self, controller: RunController, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.controller = controller
        self.profiles: List[BackupProfile] = []
        self.current: Optional[BackupProfile] = None
        self._items: Dict[str, ProfileItem] = {}
        self._copy_total_files = 0
        self._copy_total_bytes = 0
        self._prev_phase = ""
        self._phase_started_at: Dict[str, datetime] = {}
        self._progress_full_text = ""

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_list_pane())
        self.stack = QtWidgets.QStackedWidget()
        self.stack.setObjectName("pages")
        root.addWidget(self.stack, 1)

        self.empty = EmptyState(
            "anchor", "Create your first backup",
            "A profile says which folders to protect and where the copies go — a USB "
            "drive, a network share, OneDrive, or a NAS over SFTP / WebDAV.",
            action=self._make_new_btn("Create a backup profile"),
        )
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self._build_detail())

        controller.started.connect(self._on_started)
        controller.busy_changed.connect(lambda _b: self._sync_buttons())
        controller.progress.connect(self._on_progress)
        controller.cancelling.connect(self._on_cancelling)
        controller.group_profile_started.connect(lambda _pid: self._sync_list_running())

    # --- construction ----------------------------------------------------

    def _make_new_btn(self, text: str = "New profile") -> QtWidgets.QPushButton:
        b = button(text, "plus", "primary")
        b.clicked.connect(self.new_profile_requested)
        return b

    def _build_list_pane(self) -> QtWidgets.QWidget:
        pane = QtWidgets.QWidget()
        pane.setFixedWidth(330)
        lay = QtWidgets.QVBoxLayout(pane)
        lay.setContentsMargins(24, 24, 12, 20)
        lay.setSpacing(12)
        head = QtWidgets.QHBoxLayout()
        head.addWidget(label("Backups", "title"))
        head.addStretch(1)
        self.count_lbl = label("", "caption")
        head.addWidget(self.count_lbl, 0, QtCore.Qt.AlignBottom)
        lay.addLayout(head)

        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search profiles")
        self.search.setClearButtonEnabled(True)
        act = self.search.addAction(icons.icon("search", "text_muted"), QtWidgets.QLineEdit.LeadingPosition)
        theme_manager.changed.connect(lambda: act.setIcon(icons.icon("search", "text_muted")))
        self.search.textChanged.connect(self._apply_filter)
        lay.addWidget(self.search)

        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("profileList")
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.list.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.list.setSpacing(2)
        self.list.setStyleSheet("QListWidget#profileList { background: transparent; border: none; padding: 0; }")
        self.list.currentItemChanged.connect(self._on_current_item)
        self.list.itemSelectionChanged.connect(self._sync_buttons)
        self.list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._list_menu)
        lay.addWidget(self.list, 1)

        lay.addWidget(label("Ctrl / Shift-click to select several for a group run", "caption", wrap=True))
        self.group_btn = button("Run selected", "play", "primary")
        self.group_btn.setVisible(False)
        self.group_btn.clicked.connect(lambda: self.group_run_requested.emit(self.selected_profiles()))
        lay.addWidget(self.group_btn)
        lay.addWidget(self._make_new_btn())
        return pane

    def _build_detail(self) -> QtWidgets.QWidget:
        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        inner = QtWidgets.QWidget()
        inner.setObjectName("pageInner")
        scroll.setWidget(inner)
        lay = QtWidgets.QVBoxLayout(inner)
        lay.setContentsMargins(12, 24, 28, 24)
        lay.setSpacing(14)

        # --- hero header -------------------------------------------------
        hero = Card(padding=20, spacing=14)
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(16)
        self.hero_tile = QtWidgets.QLabel()
        self.hero_tile.setFixedSize(56, 56)
        self.hero_tile.setAlignment(QtCore.Qt.AlignCenter)
        top.addWidget(self.hero_tile, 0, QtCore.Qt.AlignTop)
        tcol = QtWidgets.QVBoxLayout()
        tcol.setSpacing(4)
        trow = QtWidgets.QHBoxLayout()
        trow.setSpacing(10)
        self.title = label("", "title")
        self.title.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        trow.addWidget(self.title)
        self.pill = StatusPill("never")
        trow.addWidget(self.pill, 0, QtCore.Qt.AlignVCenter)
        trow.addStretch(1)
        tcol.addLayout(trow)
        self.subtitle = label("", "muted")
        tcol.addWidget(self.subtitle)
        top.addLayout(tcol, 1)
        hero.lay.addLayout(top)

        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(8)
        self.run_btn = button("Back up now", "play", "primary", "Run this backup now (F5)")
        self.run_btn.clicked.connect(self.run_requested)
        self.cancel_btn = button("Stop", "stop", "danger", "Cancel the running job (Esc)")
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.cancel_btn.setVisible(False)
        self.verify_btn = button("Verify", "shield", tooltip=(
            "Check every backed-up file is still at the destination with the expected "
            "size (and hash, if the profile uses hash verification)."))
        self.verify_btn.clicked.connect(self.verify_requested)
        self.restore_btn = button("Restore", "restore", tooltip="Browse the destination and restore files or older versions.")
        self.restore_btn.clicked.connect(self.restore_requested)
        self.schedule_btn = button("Schedule", "calendar", tooltip="Run this backup automatically with Windows Task Scheduler.")
        self.schedule_btn.clicked.connect(self.schedule_requested)
        self.edit_btn = button("Edit", "edit", tooltip="Sources, destinations, exclusions and options.")
        self.edit_btn.clicked.connect(self.edit_requested)
        self.issues_btn = button("0 issues", "warning", "warnButton")
        self.issues_btn.setVisible(False)
        self.issues_btn.clicked.connect(self.issues_requested)
        self.more_btn = tool_button("more", "More actions")
        self.more_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        more = QtWidgets.QMenu(self.more_btn)
        self.delete_act = more.addAction("Delete profile…")
        self.delete_act.triggered.connect(self.delete_requested)
        theme_manager.changed.connect(lambda: self.delete_act.setIcon(icons.icon("trash", "err")))
        self.delete_act.setIcon(icons.icon("trash", "err"))
        self.more_btn.setMenu(more)
        self.more_btn.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }")
        for b in (self.run_btn, self.cancel_btn, self.verify_btn, self.restore_btn,
                  self.schedule_btn, self.edit_btn, self.issues_btn):
            bar.addWidget(b)
        bar.addStretch(1)
        bar.addWidget(self.more_btn)
        hero.lay.addLayout(bar)
        lay.addWidget(hero)

        # --- stat tiles ----------------------------------------------------
        tiles = QtWidgets.QGridLayout()
        tiles.setSpacing(12)
        self.tile_last = StatTile("clock", "Last run")
        self.tile_files = StatTile("files", "Files copied")
        self.tile_bytes = StatTile("database", "Data copied")
        self.tile_sched = StatTile("calendar", "Schedule")
        for i, t in enumerate((self.tile_last, self.tile_files, self.tile_bytes, self.tile_sched)):
            tiles.addWidget(t, 0, i)
        lay.addLayout(tiles)

        # --- run card ------------------------------------------------------
        run = Card(padding=18, spacing=10)
        rh = QtWidgets.QHBoxLayout()
        rh.addWidget(icon_label("activity", "text_secondary", 16))
        self.run_title = label("Current run")
        self.run_title.setStyleSheet("font-weight: 600;")
        rh.addWidget(self.run_title)
        rh.addStretch(1)
        self.speed_lbl = label("", "caption")
        rh.addWidget(self.speed_lbl)
        run.lay.addLayout(rh)

        prow = QtWidgets.QHBoxLayout()
        prow.setSpacing(18)
        self.phase_strip = PhaseStripWidget()
        prow.addWidget(self.phase_strip, 1)
        dcol = QtWidgets.QVBoxLayout()
        dcol.setSpacing(4)
        self.donut = CopyProgressDonut(diameter=104)
        self.donut.setToolTip(
            "Copy progress for this run. The scan decides how much must be copied (100%);\n"
            "the ring fills as files are written. Green 'Done' = all OK, red 'Issues' =\n"
            "failed files or verify problems, amber 'Stopped' = cancelled."
        )
        dcol.addWidget(self.donut, 0, QtCore.Qt.AlignHCenter)
        self.legend_done = label("", "caption")
        self.legend_left = label("", "caption")
        for lg in (self.legend_done, self.legend_left):
            lg.setAlignment(QtCore.Qt.AlignHCenter)
            dcol.addWidget(lg)
        prow.addLayout(dcol)
        run.lay.addLayout(prow)

        self.confirm_btn = button("Start copy", "play", "primary")
        self.confirm_btn.setVisible(False)
        self.confirm_btn.clicked.connect(self._on_confirm)
        run.lay.addWidget(self.confirm_btn)
        self.verify_banner = VerifyBanner()
        run.lay.addWidget(self.verify_banner)
        run.lay.addWidget(hline())
        self.progress_label = label("Idle.", "caption")
        self.progress_label.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        run.lay.addWidget(self.progress_label)
        lay.addWidget(run)
        self._show_donut(False)

        # --- sources / destinations ---------------------------------------
        sd = QtWidgets.QHBoxLayout()
        sd.setSpacing(12)
        self.sources_card = PathListCard("Sources", "folder")
        self.dest_card = PathListCard("Destinations", "drive")
        sd.addWidget(self.sources_card, 1)
        sd.addWidget(self.dest_card, 1)
        lay.addLayout(sd)
        lay.addStretch(1)

        theme_manager.changed.connect(self._restyle_hero)
        return scroll

    def _restyle_hero(self) -> None:
        c = color("accent_soft")
        self.hero_tile.setStyleSheet(
            f"background: rgba({c.red()},{c.green()},{c.blue()},{c.alphaF():.2f}); border-radius: 12px;"
        )
        p = self.current
        ic = dest_icon(p.destinations[0]) if p and p.destinations else "folder"
        self.hero_tile.setPixmap(icons.pixmap(ic, 28, "accent"))

    # --- profile list ----------------------------------------------------

    def set_profiles(self, profiles: List[BackupProfile], select_id: str = "") -> None:
        prev = select_id or (self.current.id if self.current else "")
        self.profiles = list(profiles)
        self.list.blockSignals(True)
        try:
            self.list.clear()
            self._items.clear()
            target = None
            for p in self.profiles:
                it = QtWidgets.QListWidgetItem()
                it.setData(QtCore.Qt.UserRole, p.id)
                w = ProfileItem(p)
                it.setSizeHint(QtCore.QSize(10, 64))
                self.list.addItem(it)
                self.list.setItemWidget(it, w)
                self._items[p.id] = w
                if p.id == prev:
                    target = it
        finally:
            self.list.blockSignals(False)
        n = len(self.profiles)
        self.count_lbl.setText(f"{n} profile{'s' if n != 1 else ''}")
        self._apply_filter(self.search.text())
        if target is None and self.list.count():
            target = self.list.item(0)
        if target is not None:
            self.list.setCurrentItem(target)
            self._on_current_item(target, None)
        else:
            self._set_current(None)
        self._sync_list_running()

    def _apply_filter(self, text: str) -> None:
        t = text.strip().lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            p = self.profile_by_id(it.data(QtCore.Qt.UserRole))
            it.setHidden(bool(t) and p is not None and t not in p.name.lower())

    def profile_by_id(self, pid: str) -> Optional[BackupProfile]:
        for p in self.profiles:
            if p.id == pid:
                return p
        return None

    def selected_profiles(self) -> List[BackupProfile]:
        out = []
        for it in self.list.selectedItems():
            p = self.profile_by_id(it.data(QtCore.Qt.UserRole))
            if p is not None:
                out.append(p)
        return out

    def _on_current_item(self, cur, _prev) -> None:
        p = self.profile_by_id(cur.data(QtCore.Qt.UserRole)) if cur is not None else None
        self._set_current(p)

    def _set_current(self, p: Optional[BackupProfile]) -> None:
        changed = (p is None) != (self.current is None) or (p and self.current and p.id != self.current.id)
        self.current = p
        if p is None:
            self.stack.setCurrentWidget(self.empty)
        else:
            self.stack.setCurrentIndex(1)
            self.render_current()
            # Switching to another profile while idle: clear the old run view.
            if changed and not self.controller.is_running_profile(p.id):
                self._reset_run_view(p.verify_after_copy)
        self._sync_buttons()
        self.current_changed.emit(p)

    def _list_menu(self, pos: QtCore.QPoint) -> None:
        it = self.list.itemAt(pos)
        if it is None:
            return
        m = QtWidgets.QMenu(self)
        busy = self.controller.is_busy()
        a_run = m.addAction(icons.icon("play"), "Back up now")
        a_run.setEnabled(not busy)
        a_ver = m.addAction(icons.icon("shield"), "Verify")
        a_ver.setEnabled(not busy)
        m.addSeparator()
        a_edit = m.addAction(icons.icon("edit"), "Edit…")
        a_edit.setEnabled(not busy)
        a_del = m.addAction(icons.icon("trash", "err"), "Delete…")
        a_del.setEnabled(not busy)
        chosen = m.exec(self.list.viewport().mapToGlobal(pos))
        if chosen is a_run:
            self.run_requested.emit()
        elif chosen is a_ver:
            self.verify_requested.emit()
        elif chosen is a_edit:
            self.edit_requested.emit()
        elif chosen is a_del:
            self.delete_requested.emit()

    # --- rendering -------------------------------------------------------

    def render_current(self) -> None:
        p = self.current
        if p is None:
            return
        self.title.setText(p.name)
        if self.controller.is_running_profile(p.id):
            self.pill.set_status("running")
        else:
            self.pill.set_status(p.last_status)
        n_src, n_dst = len(p.sources), len(p.destinations)
        self.subtitle.setText(
            f"{n_src} source{'s' if n_src != 1 else ''} → {n_dst} destination{'s' if n_dst != 1 else ''}"
            + ("   ·   SHA-256 verification" if p.verify_with_hash else "")
            + (f"   ·   keeps {p.keep_versions} versions" if p.keep_versions else "")
            + ("   ·   mirror deletions" if p.mirror_deletions else "")
        )
        self._restyle_hero()

        if p.last_run_iso:
            try:
                dt = datetime.fromisoformat(p.last_run_iso)
                self.tile_last.set(relative_time(p.last_run_iso), f"{dt:%a %d %b %Y, %H:%M}")
            except ValueError:
                self.tile_last.set(p.last_run_iso, "")
            self.tile_files.set(f"{p.last_files_copied:,}", "in the last run")
            self.tile_bytes.set(human_bytes(p.last_bytes_copied), "in the last run")
        else:
            self.tile_last.set("Never", "Run it once to create the first copy")
            self.tile_files.set("—", "")
            self.tile_bytes.set("—", "")
        if p.schedule_enabled:
            self.tile_sched.set(p.schedule_cron or "On", "Windows Task Scheduler")
        else:
            self.tile_sched.set("Manual", "No schedule set")

        self.render_paths()
        if p.id in self._items:
            self._items[p.id].update_from(p)

    def render_paths(self) -> None:
        p = self.current
        if p is None:
            return
        self.sources_card.clear()
        missing = 0
        for s in p.sources:
            ok = os.path.exists(s)
            missing += 0 if ok else 1
            self.sources_card.add_row("folder" if not os.path.isfile(s) else "files", s, ok,
                                      note="" if ok else "missing")
        if not p.sources:
            self.sources_card.add_placeholder("No sources yet — click Edit to add folders.")
            self.sources_card.pill.set_status("never", "Empty")
        elif missing:
            self.sources_card.pill.set_status("error", f"{missing} missing")
        else:
            self.sources_card.pill.set_status("ok", "All present")

        self.dest_card.clear()
        dmiss = 0
        for d in p.destinations:
            avail = dest_available(d)
            dmiss += 1 if avail is False else 0
            note = {"sftp": "SFTP", "webdav": "WebDAV"}.get(d.kind, "offline" if avail is False else "")
            self.dest_card.add_row(dest_icon(d), d.display(), avail, tooltip=d.display(), note=note)
        if not p.destinations:
            self.dest_card.add_placeholder("No destinations yet — click Edit to add one.")
            self.dest_card.pill.set_status("never", "Empty")
        elif dmiss:
            self.dest_card.pill.set_status("warning", f"{dmiss} offline")
        else:
            self.dest_card.pill.set_status("ok", "Ready")

    def refresh_availability(self) -> None:
        """Called by the window's drive poll."""
        if self.current is not None:
            self.render_paths()

    def _sync_buttons(self) -> None:
        busy = self.controller.is_busy()
        has = self.current is not None
        running_this = has and self.controller.is_running_profile(self.current.id)
        self.run_btn.setVisible(not running_this)
        self.cancel_btn.setVisible(bool(running_this))
        self.cancel_btn.setEnabled(not self.controller.is_cancelling())
        for b in (self.run_btn, self.verify_btn, self.edit_btn):
            b.setEnabled(has and not busy)
        self.restore_btn.setEnabled(has and not busy)
        self.schedule_btn.setEnabled(has)
        self.delete_act.setEnabled(has and not busy)
        sel = self.selected_profiles()
        self.group_btn.setVisible(len(sel) >= 2)
        self.group_btn.setEnabled(not busy)
        self.group_btn.setText(f"Run selected ({len(sel)})")
        if has:
            self.pill.set_status("running" if running_this else self.current.last_status)
        if not busy:
            self.confirm_btn.setVisible(False)
        self._sync_list_running()

    def _sync_list_running(self) -> None:
        cur = self.controller.current_profile_id if self.controller.kind != "verify" else ""
        for pid, w in self._items.items():
            if pid == cur and self.controller.is_busy():
                w.set_running(True)
            elif w._running:
                w.set_running(False)
                p = self.profile_by_id(pid)
                if p:
                    w.update_from(p)

    # --- issues button ---------------------------------------------------

    def set_issue_count(self, n: int) -> None:
        self.issues_btn.setVisible(n > 0)
        self.issues_btn.setText(f"{n} issue{'s' if n != 1 else ''}")

    # --- run view ---------------------------------------------------------

    def _reset_run_view(self, verify_enabled: bool = True) -> None:
        self.phase_strip.reset(verify_enabled=verify_enabled)
        self.donut.reset()
        self._show_donut(False)
        self.verify_banner.dismiss()
        self.confirm_btn.setVisible(False)
        self.speed_lbl.setText("")
        self.run_title.setText("Current run")
        self.set_progress_text("Idle — press Back up now to start.")
        self._prev_phase = ""
        self._phase_started_at = {}

    def _on_started(self, kind: str, ids: list) -> None:
        verify_enabled = True
        if kind == "group":
            verify_enabled = any(p.verify_after_copy for p in self.profiles if p.id in ids)
        elif self.current is not None:
            verify_enabled = self.current.verify_after_copy
        self._reset_run_view(verify_enabled)
        if kind == "verify":
            self.phase_strip.set_verify_only_mode()
            self.run_title.setText("Verifying destination")
            self.set_progress_text("Verifying…")
        elif kind == "group":
            self.run_title.setText(f"Group run — {len(ids)} profiles")
            self.set_progress_text(f"Group run starting — {len(ids)} profile(s)…")
        else:
            self.run_title.setText("Backing up")
            self.set_progress_text("Scanning…")
        self._sync_buttons()

    def _show_donut(self, visible: bool) -> None:
        self.donut.setVisible(visible)
        self.legend_done.setVisible(visible)
        self.legend_left.setVisible(visible)

    def _set_donut(self, files_done: int, bytes_done: int) -> None:
        tb, tf = self._copy_total_bytes, self._copy_total_files
        if tb > 0:
            frac = bytes_done / tb
        elif tf > 0:
            frac = files_done / tf
        else:
            frac = 1.0
        self.donut.set_progress(frac)
        acc = color("accent").name()
        mut = color("text_disabled").name()
        self.legend_done.setText(f'<span style="color:{acc}">●</span> done <b>{files_done:,}</b> · {human_bytes(bytes_done)}')
        self.legend_left.setText(
            f'<span style="color:{mut}">●</span> left <b>{max(0, tf - files_done):,}</b> · '
            f'{human_bytes(max(0, tb - bytes_done))}'
        )
        cur = self.controller.current_profile_id
        if cur in self._items:
            self._items[cur].set_running(True, frac, f"Copying — {int(frac * 100)}%")

    def finish_donut(self, cancelled: bool, had_issues: bool) -> None:
        if self.donut.isHidden():
            return
        if cancelled:
            self.donut.show_stopped()
        elif had_issues:
            self.donut.show_issues()
        else:
            self.donut.show_finished()

    def _on_cancel(self) -> None:
        self.controller.cancel()

    def _on_cancelling(self) -> None:
        self.set_progress_text("Stopping after the current file…")
        self._sync_buttons()

    def _on_confirm(self) -> None:
        self.confirm_btn.setVisible(False)
        self.controller.confirm_copy()

    def _confirm_wanted(self) -> bool:
        p = self.profile_by_id(self.controller.current_profile_id)
        return bool(p and p.confirm_before_copy)

    def _on_progress(self, p) -> None:
        phase = getattr(p, "phase", "copying") or "copying"
        now = datetime.now()
        if phase != self._prev_phase:
            self._phase_transition(self._prev_phase, phase, now)
            self._prev_phase = phase

        if phase == "scanning":
            self._show_donut(False)
            if p.files_total > 0:
                self.phase_strip.set_phase("scan", "running", p.files_done * 100.0 / max(1, p.files_total),
                                           f"{p.files_done:,} / {p.files_total:,}")
            else:
                self.phase_strip.set_phase("scan", "running", 0, f"walking… {p.files_done:,} found")
            cur = self.controller.current_profile_id
            if cur in self._items:
                self._items[cur].set_running(True, 0.0, "Scanning…")
        elif phase == "scan-done":
            self.phase_strip.set_phase("scan", "done", 100, f"{p.files_total:,} files · {human_bytes(p.bytes_total)}")
            self._copy_total_files = p.files_to_copy
            self._copy_total_bytes = p.bytes_to_copy
            self._set_donut(0, 0)
            self._show_donut(True)
            if self._confirm_wanted():
                self.confirm_btn.setText(f"Start copy — {p.files_to_copy:,} files, {human_bytes(p.bytes_to_copy)}")
                self.confirm_btn.setVisible(True)
        elif phase == "copying":
            self.confirm_btn.setVisible(False)
            if p.bytes_total > 0:
                pct = p.bytes_done * 100.0 / p.bytes_total
            elif p.files_total > 0:
                pct = p.files_done * 100.0 / p.files_total
            else:
                pct = 100.0
            self.phase_strip.set_phase(
                "copy", "running", pct,
                f"{p.files_done:,} / {p.files_total:,} · {human_bytes(p.bytes_done)} / {human_bytes(p.bytes_total)}",
            )
            self._copy_total_files = p.files_total
            self._copy_total_bytes = p.bytes_total
            self._set_donut(p.files_done, p.bytes_done)
            self._show_donut(True)
        elif phase == "verifying":
            pct = p.files_done * 100.0 / p.files_total if p.files_total > 0 else 100.0
            self.phase_strip.set_phase("verify", "running", pct, f"{p.files_done:,} / {p.files_total:,} files")

        speed = human_bytes(p.speed_bps) + "/s" if p.speed_bps > 1 else ""
        eta = human_time(p.eta_seconds) if p.eta_seconds > 0 else ""
        self.speed_lbl.setText("   ".join(x for x in (speed, ("ETA " + eta) if eta else "") if x) if phase == "copying" else "")

        if phase == "scanning":
            tally = (f"Scanning source — {p.files_done:,} files found ({human_bytes(p.bytes_done)})"
                     if p.files_total <= 0 else
                     f"Scanning — {p.files_done:,} of {p.files_total:,} checked · {p.files_skipped:,} unchanged so far")
        elif phase == "scan-done":
            tally = (f"Scan complete — {p.files_to_copy:,} to copy ({human_bytes(p.bytes_to_copy)}), "
                     f"{p.files_skipped:,} unchanged. "
                     + ("Click 'Start copy' to proceed." if self._confirm_wanted() else "Starting copy…"))
        elif phase == "verifying":
            tally = f"Verifying — {p.files_done:,} of {p.files_total:,} files"
        else:
            tally = f"Copying — {p.files_done:,} of {p.files_total:,} files · {p.files_skipped:,} unchanged"
            if p.files_failed:
                tally += f" · {p.files_failed:,} failed"
        parts = [x for x in (p.dest_label, tally, p.current_file) if x]
        self.set_progress_text("  ·  ".join(parts))

    def _phase_transition(self, prev: str, now_phase: str, at: datetime) -> None:
        self._phase_started_at[now_phase] = at
        if not prev or prev == now_phase:
            return
        key = _PHASE_KEY.get(prev)
        new_key = _PHASE_KEY.get(now_phase)
        if not key or key == new_key:
            return
        started = self._phase_started_at.get(prev)
        # Durations: scan-done shares the "scan" row, so measure from scanning.
        if prev == "scan-done":
            started = self._phase_started_at.get("scanning", started)
        detail = f"({human_time((at - started).total_seconds())})" if started else ""
        if key == "scan":
            # Keep the scan summary, just append the duration.
            row = self.phase_strip.rows["scan"]
            detail = f"{row.detail_lbl.text()}  {detail}".strip()
        self.phase_strip.mark_done(key, detail)

    def set_progress_text(self, text: str) -> None:
        self._progress_full_text = text
        self.progress_label.setToolTip(text)
        self._reelide()

    def _reelide(self) -> None:
        fm = self.progress_label.fontMetrics()
        avail = max(40, self.progress_label.width() - 8)
        self.progress_label.setText(fm.elidedText(self._progress_full_text, QtCore.Qt.ElideMiddle, avail))

    def resizeEvent(self, ev: QtGui.QResizeEvent) -> None:
        super().resizeEvent(ev)
        QtCore.QTimer.singleShot(0, self._reelide)
