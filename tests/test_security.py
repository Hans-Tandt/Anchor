import json
import os
import stat as _stat
from types import SimpleNamespace

import pytest

from anchor import app_config, scheduler
from anchor.app_config import AppSettings
from anchor.core.locking import RunLock
from anchor.core.profile import (
    BackupProfile, delete_profile, list_profiles, load_profile, save_profile,
)
from anchor.core.state import StateDB
from anchor.destinations.base import (
    DestinationError, check_rel_path, is_safe_name, is_safe_rel_path,
    safe_local_target,
)
from anchor.destinations.local import LocalDestination


# --- path helpers -------------------------------------------------------------

@pytest.mark.parametrize("name", ["..", ".", "", "a/b", "a\\b", "C:", "x\x00y", "a\nb"])
def test_unsafe_names_rejected(name):
    assert not is_safe_name(name)


def test_safe_rel_path():
    assert is_safe_rel_path("C__Users_me_Docs/sub/file.txt")
    assert not is_safe_rel_path("sub/../../evil.txt")
    assert not is_safe_rel_path("/abs/path")
    assert not is_safe_rel_path("C:/Windows/evil.dll")


def test_check_rel_path_rejects_traversal():
    assert check_rel_path("/a/b") == "a/b"
    with pytest.raises(DestinationError):
        check_rel_path("a/../../b")
    with pytest.raises(DestinationError):
        check_rel_path("..\\..\\b")


def test_safe_local_target(tmp_path):
    base = str(tmp_path / "restore")
    assert safe_local_target(base, "a/b.txt") == os.path.join(base, "a", "b.txt")
    for bad in ("../x", "a/../../x", "C:/x", "/etc/passwd", "\\\\srv\\share\\x", ""):
        with pytest.raises(DestinationError):
            safe_local_target(base, bad)


def test_local_destination_refuses_escape(tmp_path):
    dest = LocalDestination(str(tmp_path / "dest"))
    dest.connect()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    for bad in ("../outside.txt", "sub/../../outside.txt"):
        with pytest.raises(DestinationError):
            dest.get_file(bad, str(tmp_path / "copy.txt"))
    with pytest.raises(DestinationError):
        dest.remove("../outside.txt")
    assert outside.exists()
    if os.name == "nt":
        with pytest.raises(DestinationError):
            dest._abs("Z:evil.txt")


# --- SFTP --------------------------------------------------------------------

class _Attr:
    def __init__(self, name, is_dir=False):
        self.filename = name
        self.st_mode = (_stat.S_IFDIR if is_dir else _stat.S_IFREG) | 0o644
        self.st_size = 1
        self.st_mtime = 0


class _FakeSFTP:
    def __init__(self, tree):
        self.tree = tree

    def listdir_attr(self, path):
        return self.tree.get(path, [])


def _sftp_dest():
    from anchor.destinations.sftp import SFTPDestination
    return SFTPDestination("h", 22, "u", "/backup", "d1", password="x")


def test_sftp_iter_files_drops_malicious_names():
    d = _sftp_dest()
    d._sftp = _FakeSFTP({
        "/backup": [_Attr("sub", True), _Attr("../../evil.txt"), _Attr(".."),
                    _Attr("C:\\Windows\\x.dll"), _Attr("ok.txt")],
        "/backup/sub": [_Attr("a.txt"), _Attr("..\\..\\b.txt")],
    })
    assert sorted(d.iter_files()) == ["ok.txt", "sub/a.txt"]


def test_sftp_list_versions_drops_malicious_names():
    d = _sftp_dest()
    d._sftp = _FakeSFTP({
        "/backup/_anchor_versions/sub": [
            _Attr("f.txt__20260101T000000.bak"),
            _Attr("f.txt__/../../x__20260101T000001.bak"),
        ],
    })
    vs = d.list_versions("sub/f.txt")
    assert [v.version_id for v in vs] == ["20260101T000000"]


def test_sftp_abs_refuses_traversal():
    d = _sftp_dest()
    assert d._abs("a/b") == "/backup/a/b"
    with pytest.raises(DestinationError):
        d._abs("../../etc/passwd")


def test_sftp_tofu_policy_stores_and_detects_change(tmp_path):
    import paramiko
    from anchor.destinations import sftp as sftp_mod

    kh = str(tmp_path / "known_hosts")
    k1 = paramiko.RSAKey.generate(1024)
    k2 = paramiko.RSAKey.generate(1024)

    c = paramiko.SSHClient()
    sftp_mod._TrustOnFirstUsePolicy(kh).missing_host_key(c, "[nas]:2222", k1)
    assert os.path.exists(kh)

    c2 = paramiko.SSHClient()
    c2.load_host_keys(kh)
    hk = c2.get_host_keys()
    assert hk.check("[nas]:2222", k1)
    assert not hk.check("[nas]:2222", k2)  # changed key -> BadHostKeyException in connect


def test_sftp_connect_does_not_use_autoadd(monkeypatch):
    import paramiko
    from anchor.destinations import sftp as sftp_mod

    seen = {}

    class FakeClient:
        def load_host_keys(self, p):
            seen["loaded"] = p

        def set_missing_host_key_policy(self, pol):
            seen["policy"] = pol

        def connect(self, **kw):
            raise paramiko.BadHostKeyException("h", paramiko.RSAKey.generate(1024),
                                               paramiko.RSAKey.generate(1024))

        def close(self):
            pass

    monkeypatch.setattr(sftp_mod.paramiko, "SSHClient", FakeClient)
    d = _sftp_dest()
    with pytest.raises(DestinationError, match="CHANGED"):
        d.connect()
    assert isinstance(seen["policy"], sftp_mod._TrustOnFirstUsePolicy)
    assert not isinstance(seen["policy"], paramiko.AutoAddPolicy)


# --- WebDAV ------------------------------------------------------------------

def _webdav_dest():
    from anchor.destinations.webdav import WebDAVDestination
    return WebDAVDestination("h", 443, "u", "/backup", "d1", password="x")


def test_webdav_iter_files_drops_malicious_names():
    d = _webdav_dest()
    dirs = {"/backup/sub"}
    listing = {
        "/backup": ["backup/", "sub/", "..", "C:", "ok.txt"],
        "/backup/sub": ["sub/", "a.txt", "..\\x.txt"],
    }
    d._client = SimpleNamespace(
        list=lambda p: listing.get(p, []),
        is_dir=lambda p: p in dirs,
    )
    assert sorted(d.iter_files()) == ["ok.txt", "sub/a.txt"]


def test_webdav_remove_surfaces_errors():
    from anchor.destinations.webdav import RemoteResourceNotFound
    d = _webdav_dest()

    def boom(p):
        raise RuntimeError("403 Forbidden")
    d._client = SimpleNamespace(clean=boom)
    with pytest.raises(DestinationError):
        d.remove("a.txt")

    def missing(p):
        raise RemoteResourceNotFound(p)
    d._client = SimpleNamespace(clean=missing)
    d.remove("a.txt")  # missing is fine


# --- ids / scheduler ---------------------------------------------------------

BAD_IDS = ["../evil", "a b", 'x" --cwd C:\\evil', "*", "a/b", "", "x" * 65]


@pytest.mark.parametrize("bad", BAD_IDS)
def test_scheduler_rejects_bad_ids(bad):
    with pytest.raises(ValueError):
        scheduler.task_command(bad)
    spec = scheduler.ScheduleSpec("DAILY", "03:00")
    assert scheduler.create_or_update(bad, spec) is not None


@pytest.mark.parametrize("spec", [
    scheduler.ScheduleSpec("DAILY", "03:00 /RU SYSTEM"),
    scheduler.ScheduleSpec("HOURLY; calc", "03:00"),
    scheduler.ScheduleSpec("WEEKLY", "03:00", days="MON /RU x"),
])
def test_scheduler_rejects_bad_spec(spec):
    assert scheduler.create_or_update("abcd1234", spec) is not None


def test_scheduler_command_for_valid_id():
    assert scheduler.task_command("abcd1234").endswith("--profile abcd1234 --silent")


@pytest.mark.parametrize("bad", BAD_IDS)
def test_state_and_lock_reject_bad_ids(bad):
    with pytest.raises(ValueError):
        StateDB(bad)
    with pytest.raises(ValueError):
        RunLock(bad)


def test_profile_with_traversal_id_not_loaded(isolated_app_dir):
    p = app_config.PROFILES_DIR / "x__evil.json"
    p.write_text(json.dumps({"id": "../../evil", "name": "x"}), encoding="utf-8")
    assert load_profile(p) is None
    with pytest.raises(ValueError):
        delete_profile(BackupProfile(id="*"))


def test_profile_wrong_types_fall_back_to_defaults(isolated_app_dir):
    p = app_config.PROFILES_DIR / "x__abc.json"
    p.write_text(json.dumps({
        "id": "abc", "name": "x",
        "sources": "C:\\not-a-list",
        "mirror_max_delete_pct": "5",
        "keep_versions": True,
        "mirror_deletions": "yes",
        "destinations": [{"id": "d1", "kind": "local", "path": "D:\\b",
                          "future_field": 1, "port": "22"}],
    }), encoding="utf-8")
    prof = load_profile(p)
    assert prof is not None
    assert prof.sources == []
    assert prof.mirror_max_delete_pct == 25
    assert prof.keep_versions == 0
    assert prof.mirror_deletions is False
    assert prof.destinations[0].path == "D:\\b"
    assert prof.destinations[0].port == 22


def test_save_profile_rename_keeps_one_file(isolated_app_dir):
    prof = BackupProfile(id="abc123", name="First")
    save_profile(prof)
    prof.name = "Second"
    path = save_profile(prof)
    files = list(app_config.PROFILES_DIR.glob("*.json"))
    assert files == [path]
    assert [p.name for p in list_profiles()] == ["Second"]


def test_app_settings_bad_types(isolated_app_dir):
    app_config.SETTINGS_FILE.write_text(json.dumps({
        "parallel_workers": "lots", "scan_pause_seconds": 1, "theme": 5,
    }), encoding="utf-8")
    s = AppSettings.load()
    assert s.parallel_workers == 4
    assert s.scan_pause_seconds == 1
    assert s.theme == "dark"
    s.save()
    assert json.loads(app_config.SETTINGS_FILE.read_text())["parallel_workers"] == 4
