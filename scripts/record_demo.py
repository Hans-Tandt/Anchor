"""Record the README / docs screenshots and animated GIFs.

    python scripts/record_demo.py            # writes docs/images/*.png|*.gif
    python scripts/record_demo.py --onscreen # use the real window system

Everything runs in a throw-away sandbox: APPDATA points at a temp folder, demo
source files and a fake "backup drive" are generated there, so your real
profiles and logs are never touched. The copy step is slowed down a little
so the progress UI is visible in the recording.

Needs Pillow (pip install pillow).
"""
from __future__ import annotations

import argparse
import os
import random
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
sys.path.insert(0, str(ROOT))

# Sandbox lives at "<drive>:\AnchorDemo" (not under %TEMP%) so screenshots
# don't show the recording machine's user name in paths. Removed at the end.
SANDBOX = Path(ROOT.anchor) / "AnchorDemo"
if SANDBOX.exists():
    shutil.rmtree(SANDBOX)
SANDBOX.mkdir()
os.environ["APPDATA"] = str(SANDBOX / "AppData")

ap = argparse.ArgumentParser()
ap.add_argument("--onscreen", action="store_true", help="render on the real desktop instead of offscreen")
ARGS = ap.parse_args()
if not ARGS.onscreen:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QPA_FONTDIR", str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"))

from PIL import Image, ImageDraw  # noqa: E402
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from anchor.app_config import AppSettings, ensure_dirs  # noqa: E402
from anchor.core.profile import BackupProfile, DestinationConfig, save_profile  # noqa: E402
from anchor.logging_setup import setup_logging  # noqa: E402

W, H = 1240, 780
GIF_W = 1000
FPS_MS = 70


# ---------------------------------------------------------------------------
# Sandbox data
# ---------------------------------------------------------------------------

def make_files(folder: Path, n: int, lo: int, hi: int, exts) -> None:
    rnd = random.Random(folder.name)
    for i in range(n):
        sub = folder / rnd.choice(["", "2025", "2026", "Archive", "Shared"])
        sub.mkdir(parents=True, exist_ok=True)
        p = sub / f"{rnd.choice(['report', 'notes', 'invoice', 'plan', 'IMG', 'scan', 'draft'])}_{i:03d}{rnd.choice(exts)}"
        p.write_bytes(os.urandom(rnd.randint(lo, hi)))


def build_sandbox():
    ensure_dirs()
    home = SANDBOX / "Users" / "alex"
    docs = home / "Documents"
    photos = home / "Pictures"
    code = home / "Projects"
    make_files(docs, 160, 20_000, 400_000, [".docx", ".xlsx", ".pdf", ".txt"])
    make_files(photos, 90, 300_000, 900_000, [".jpg", ".png", ".heic"])
    make_files(code, 60, 2_000, 60_000, [".py", ".md", ".json"])
    drive = SANDBOX / "Backup Drive (E)"
    drive.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    profiles = [
        BackupProfile(
            name="Documents", sources=[str(docs)],
            destinations=[DestinationConfig(kind="local", label="Backup drive (E:)", path=str(drive / "Anchor"))],
            keep_versions=5, verify_after_copy=True,
            schedule_enabled=True, schedule_cron="Daily at 03:00",
            last_run_iso=(now - timedelta(days=1, hours=3)).isoformat(timespec="seconds"),
            last_status="ok", last_files_copied=0, last_bytes_copied=0,
        ),
        BackupProfile(
            name="Photos", sources=[str(photos)],
            destinations=[
                DestinationConfig(kind="local", label="Backup drive (E:)", path=str(drive / "Photos")),
                DestinationConfig(kind="sftp", label="QNAP NAS (offsite)", host="nas.example.net",
                                  username="anchor", remote_path="/share/Backup"),
            ],
            last_run_iso=(now - timedelta(hours=5)).isoformat(timespec="seconds"),
            last_status="warning", last_files_copied=42, last_bytes_copied=31_400_000,
            schedule_enabled=True, schedule_cron="Weekly SUN at 10:00",
        ),
        BackupProfile(
            name="Source code", sources=[str(code)],
            destinations=[DestinationConfig(kind="webdav", label="Nextcloud (WebDAV)", host="cloud.example.net",
                                            username="anchor", remote_path="/remote.php/dav/files/anchor")],
            keep_versions=20, verify_with_hash=True,
            last_run_iso=(now - timedelta(minutes=40)).isoformat(timespec="seconds"),
            last_status="ok", last_files_copied=7, last_bytes_copied=180_000,
        ),
        BackupProfile(
            name="Tax papers 2025", sources=[str(docs / "2025")],
            destinations=[DestinationConfig(kind="local", label="USB stick (F:)", path="Z:\\NotPluggedIn")],
            last_status="never",
        ),
    ]
    for p in profiles:
        save_profile(p)
    s = AppSettings(theme="dark", scan_pause_seconds=1, last_profile=profiles[0].id)
    s.save()
    return s, profiles


def slow_down_copies():
    """Make the copy phase take a few seconds so it shows up in the GIF."""
    from anchor.destinations import local as local_mod
    cls = local_mod.LocalDestination
    orig = cls.put_file

    def put_file(self, *a, **kw):
        time.sleep(0.09)
        return orig(self, *a, **kw)
    cls.put_file = put_file


# ---------------------------------------------------------------------------
# Recorder
# ---------------------------------------------------------------------------

CURSOR = [(0, 0), (0, 17), (4.5, 13), (7.5, 20), (10, 19), (7, 12.5), (12.5, 12.5)]


def qimage_to_pil(img: QtGui.QImage) -> Image.Image:
    img = img.convertToFormat(QtGui.QImage.Format_RGBA8888)
    ptr = img.constBits()
    return Image.frombuffer("RGBA", (img.width(), img.height()), bytes(ptr), "raw", "RGBA", 0, 1).copy()


class Recorder:
    def __init__(self, win: QtWidgets.QWidget):
        self.win = win
        self.frames = []
        self.cursor = QtCore.QPointF(W * 0.6, H * 0.6)
        self.click_flash = 0

    def grab(self) -> Image.Image:
        QtWidgets.QApplication.processEvents()
        img = qimage_to_pil(self.win.grab().toImage())
        # Composite any visible dialog on top at its position.
        for w in QtWidgets.QApplication.topLevelWidgets():
            if w is not self.win and w.isVisible() and isinstance(w, QtWidgets.QDialog):
                d = qimage_to_pil(w.grab().toImage())
                pos = w.pos() - self.win.pos()
                shadow = Image.new("RGBA", (d.width + 40, d.height + 40), (0, 0, 0, 0))
                ImageDraw.Draw(shadow).rounded_rectangle([20, 24, d.width + 20, d.height + 24], 12, fill=(0, 0, 0, 90))
                img.alpha_composite(shadow, (max(0, pos.x() - 20), max(0, pos.y() - 20)))
                img.alpha_composite(d, (max(0, pos.x()), max(0, pos.y())))
        return img

    def _draw_cursor(self, img: Image.Image) -> Image.Image:
        img = img.copy()
        d = ImageDraw.Draw(img)
        x, y = self.cursor.x(), self.cursor.y()
        if self.click_flash:
            r = 10 + (4 - self.click_flash) * 4
            d.ellipse([x - r, y - r, x + r, y + r], outline=(212, 168, 90, 220), width=3)
            self.click_flash -= 1
        pts = [(x + px * 1.25, y + py * 1.25) for px, py in CURSOR]
        d.polygon(pts, fill=(255, 255, 255, 255), outline=(0, 0, 0, 255))
        return img

    def frame(self, n: int = 1) -> None:
        img = self._draw_cursor(self.grab())
        for _ in range(n):
            self.frames.append(img)

    def wait(self, ms: int) -> None:
        end = time.time() + ms / 1000
        while time.time() < end:
            t0 = time.time()
            self.frame()
            QtWidgets.QApplication.processEvents()
            dt = FPS_MS / 1000 - (time.time() - t0)
            if dt > 0:
                QtCore.QThread.msleep(int(dt * 1000))
                QtWidgets.QApplication.processEvents()

    def wait_until(self, cond, timeout_ms: int = 30000) -> None:
        end = time.time() + timeout_ms / 1000
        while time.time() < end and not cond():
            self.wait(FPS_MS)

    def target(self, w: QtWidgets.QWidget) -> QtCore.QPointF:
        c = w.mapTo(self.win, w.rect().center()) if w.window() is self.win else (
            w.mapToGlobal(w.rect().center()) - self.win.mapToGlobal(QtCore.QPoint(0, 0)))
        return QtCore.QPointF(c)

    def move_to(self, w: QtWidgets.QWidget, steps: int = 10) -> None:
        start = QtCore.QPointF(self.cursor)
        end = self.target(w)
        for i in range(1, steps + 1):
            t = i / steps
            t = 1 - (1 - t) ** 3
            self.cursor = start + (end - start) * t
            self.frame()
            QtWidgets.QApplication.processEvents()

    def click(self, w: QtWidgets.QWidget, steps: int = 10) -> None:
        self.move_to(w, steps)
        self.click_flash = 4
        self.frame(2)
        if isinstance(w, QtWidgets.QAbstractButton):
            w.click()
        else:
            QtCore.QMetaObject.invokeMethod(w, "click")
        self.frame()

    def save_gif(self, path: Path, keep_last_ms: int = 1500) -> None:
        if not self.frames:
            return
        scale = GIF_W / self.frames[0].width
        size = (GIF_W, int(self.frames[0].height * scale))
        # Collapse identical consecutive frames into longer durations.
        out, durs = [], []
        prev = None
        for f in self.frames:
            small = f.resize(size, Image.LANCZOS).convert("RGB")
            if prev is not None and small.tobytes() == prev.tobytes():
                durs[-1] += FPS_MS
                continue
            out.append(small)
            durs.append(FPS_MS)
            prev = small
        durs[-1] += keep_last_ms
        pal = out[len(out) // 2].quantize(colors=255, method=Image.MEDIANCUT)
        q = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in out]
        q[0].save(path, save_all=True, append_images=q[1:], duration=durs, loop=0, optimize=True, disposal=1)
        print(f"  {path.relative_to(ROOT)}  {len(q)} frames  {path.stat().st_size / 1e6:.1f} MB")
        self.frames = []

    def screenshot(self, name: str) -> None:
        img = self.grab()
        p = OUT / name
        img.save(p)
        print(f"  {p.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# Scenes
# ---------------------------------------------------------------------------

def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    setup_logging()
    settings, profiles = build_sandbox()
    slow_down_copies()

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Anchor")
    font = QtGui.QFont("Segoe UI", 10)
    app.setFont(font)

    from anchor.gui import MainWindow, apply_theme
    apply_theme(app, "dark")
    win = MainWindow(settings)
    win.resize(W, H)
    win.move(40, 40)
    win.show()
    if win.tray is not None:
        win.tray.hide()
    win.settings.notifications = False
    rec = Recorder(win)
    rec.wait(400)
    d = win.dashboard

    # Disable the scheduler call for the demo (no real scheduled tasks).
    import anchor.scheduler as sched
    sched.create_or_update = lambda *a, **k: None
    sched.delete = lambda *a, **k: None

    print("Screenshots:")
    rec.screenshot("screenshot-dashboard-dark.png")

    # --- GIF 1: run a backup ---------------------------------------------
    print("GIF: backup run")
    rec.frames = []
    rec.wait(600)
    rec.click(d.run_btn, steps=14)
    rec.wait_until(lambda: not win.controller.is_busy(), 60000)
    rec.wait(2200)
    rec.save_gif(OUT / "demo-backup.gif", keep_last_ms=2500)
    rec.screenshot("screenshot-run-complete.png")

    # --- GIF 2: tour (profiles, activity, settings, theme, compact nav) ---
    print("GIF: tour")
    for it in list(win.toasts.toasts):
        it.dismiss()
    rec.wait(300)
    rec.frames = []
    item_widgets = [d._items[p.id] for p in d.profiles]
    for w in item_widgets[1:3]:
        rec.move_to(w, 8)
        rec.click_flash = 4
        d.list.setCurrentRow(d.profiles.index(d.profile_by_id(w.profile_id)))
        rec.wait(900)
    act_item = win.nav._items["activity"]
    rec.move_to(act_item, 10)
    rec.click_flash = 4
    win.nav.set_current("activity")
    rec.wait(1100)
    set_item = win.nav._items["settings"]
    rec.move_to(set_item, 10)
    rec.click_flash = 4
    win.nav.set_current("settings")
    rec.wait(1000)
    rec.move_to(win.theme_item, 8)
    rec.click_flash = 4
    win.theme_item.click()
    rec.wait(1100)
    rec.move_to(win.nav._items["backups"], 10)
    rec.click_flash = 4
    win.nav.set_current("backups")
    rec.wait(900)
    rec.move_to(win.nav.menu_btn, 8)
    rec.click_flash = 4
    win.nav.menu_btn.click()
    rec.wait(900)
    win.nav.menu_btn.click()
    rec.wait(700)
    rec.save_gif(OUT / "demo-tour.gif")

    # --- light-theme screenshots -----------------------------------------
    print("Screenshots (light):")
    d.list.setCurrentRow(0)
    rec.wait(300)
    rec.screenshot("screenshot-dashboard-light.png")
    win.nav.set_current("settings")
    rec.wait(300)
    rec.screenshot("screenshot-settings-light.png")
    win.nav.set_current("backups")
    win.theme_item.click()  # back to dark
    rec.wait(300)

    print("Screenshots (dark):")
    win.nav.set_current("activity")
    rec.wait(300)
    rec.screenshot("screenshot-activity.png")
    win.nav.set_current("settings")
    rec.wait(300)
    rec.screenshot("screenshot-settings-dark.png")
    win.nav.set_current("backups")
    d.list.setCurrentRow(1)
    rec.wait(300)
    rec.screenshot("screenshot-dashboard-photos.png")

    # Profile editor (non-modal show so we can grab it)
    from anchor.gui.profile_editor import ProfileEditor
    d.list.setCurrentRow(0)
    rec.wait(200)
    ed = ProfileEditor(win, d.current)
    ed.move(win.pos() + QtCore.QPoint(260, 50))
    ed.show()
    rec.wait(300)
    rec.screenshot("screenshot-profile-editor.png")
    ed.reject()

    # Restore dialog
    from anchor.gui.restore_dialog import RestoreDialog
    rd = RestoreDialog(win, d.current)
    rd.move(win.pos() + QtCore.QPoint(140, 60))
    rd.show()
    rd.tree.expandAll()
    it = rd.tree.topLevelItem(0)
    while it is not None and it.childCount():
        it = it.child(it.childCount() - 1)
    if it is not None:
        rd.tree.setCurrentItem(it)
    rec.wait(400)
    rec.screenshot("screenshot-restore.png")
    rd.reject()

    win.close()
    shutil.rmtree(SANDBOX, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
