import os

import pytest

from anchor.app_config import AppSettings
from anchor.core import engine as engine_mod
from anchor.core.engine import BackupEngine
from anchor.core.profile import BackupProfile, DestinationConfig
from anchor.core.walker import ExclusionRules, walk_sources


SETTINGS = AppSettings(scan_pause_seconds=0, parallel_workers=1)


def _make_source(tmp_path, n=4):
    src = tmp_path / "src"
    src.mkdir()
    for i in range(n):
        (src / f"f{i}.txt").write_text(f"data {i}")
    return src


def _profile(src, dest, **kw):
    return BackupProfile(
        id="p1", name="t", sources=[str(src)],
        destinations=[DestinationConfig(id="d1", kind="local", path=str(dest))],
        flat_destination_layout=True, **kw,
    )


def test_basic_backup(tmp_path):
    src = _make_source(tmp_path)
    dest = tmp_path / "dest"
    r = BackupEngine(_profile(src, dest), settings=SETTINGS).run()
    assert r.status == "ok"
    assert r.files_copied == 4
    assert (dest / "f0.txt").read_text() == "data 0"


def test_unreachable_destination_is_error(tmp_path, monkeypatch):
    src = _make_source(tmp_path)
    from anchor.destinations.base import DestinationError
    from anchor.destinations.local import LocalDestination

    def fail(self):
        raise DestinationError("offline")
    monkeypatch.setattr(LocalDestination, "connect", fail)
    r = BackupEngine(_profile(src, tmp_path / "dest"), settings=SETTINGS).run()
    assert r.files_failed == 0
    assert r.status == "error"


def test_cancel_during_classify_does_not_mirror_delete(tmp_path, monkeypatch):
    src = _make_source(tmp_path)
    dest = tmp_path / "dest"
    prof = _profile(src, dest, mirror_deletions=True, mirror_max_delete_pct=0)
    assert BackupEngine(prof, settings=SETTINGS).run().files_copied == 4

    eng = BackupEngine(prof, settings=SETTINGS)
    orig = BackupEngine._needs_copy

    def needs_copy_then_cancel(self, *a, **kw):
        out = orig(self, *a, **kw)
        self.cancel_event.set()  # user hits Cancel after the first file
        return out
    monkeypatch.setattr(BackupEngine, "_needs_copy", needs_copy_then_cancel)
    eng.run()
    assert sorted(os.listdir(dest)) == ["f0.txt", "f1.txt", "f2.txt", "f3.txt"]


def test_partial_source_read_disables_mirror_delete(tmp_path, monkeypatch):
    src = _make_source(tmp_path)
    dest = tmp_path / "dest"
    prof = _profile(src, dest, mirror_deletions=True, mirror_max_delete_pct=0)
    BackupEngine(prof, settings=SETTINGS).run()

    # Simulate a walk where f3.txt sits in an unreadable folder.
    real_walk = engine_mod.walk_sources

    def walk_with_error(*a, errors=None, **kw):
        for sub, item in real_walk(*a, errors=errors, **kw):
            if item.rel_path == "f3.txt":
                errors.append((sub, "Access is denied"))
                continue
            yield sub, item
    monkeypatch.setattr(engine_mod, "walk_sources", walk_with_error)
    BackupEngine(prof, settings=SETTINGS).run()
    assert (dest / "f3.txt").exists()


def test_mirror_delete_still_works(tmp_path):
    src = _make_source(tmp_path)
    dest = tmp_path / "dest"
    prof = _profile(src, dest, mirror_deletions=True, mirror_max_delete_pct=0)
    BackupEngine(prof, settings=SETTINGS).run()
    (src / "f3.txt").unlink()
    BackupEngine(prof, settings=SETTINGS).run()
    assert not (dest / "f3.txt").exists()


def test_hash_error_during_classify_does_not_crash(tmp_path, monkeypatch):
    src = _make_source(tmp_path)
    dest = tmp_path / "dest"
    prof = _profile(src, dest, verify_with_hash=True)
    BackupEngine(prof, settings=SETTINGS).run()

    real = engine_mod._sha256

    def locked(path, *a, **kw):
        if path.endswith("f1.txt"):
            raise PermissionError("file is locked")
        return real(path, *a, **kw)
    monkeypatch.setattr(engine_mod, "_sha256", locked)
    r = BackupEngine(prof, settings=SETTINGS).run()
    assert r.files_failed == 1
    assert r.files_skipped == 3


def test_walker_reports_unreadable_dirs(tmp_path, monkeypatch):
    src = _make_source(tmp_path)
    (src / "sub").mkdir()
    real_scandir = os.scandir

    def deny(path="."):
        if os.fspath(path).endswith("sub"):
            raise PermissionError(13, "Access is denied", os.fspath(path))
        return real_scandir(path)
    monkeypatch.setattr(os, "scandir", deny)
    errors = []
    items = list(walk_sources([str(src)], ExclusionRules(), errors=errors))
    assert len(items) == 4
    assert errors and "denied" in errors[0][1]
