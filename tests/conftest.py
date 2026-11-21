import os
import sys
import tempfile

import pytest

# Belt and braces: before anything imports `anchor`, point APPDATA at a
# throw-away folder so no test can ever read or write the developer's real
# profiles, state DBs or settings — even through a module that copied a path
# constant at import time. Qt runs headless.
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="anchor-tests-")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def isolated_app_dir(tmp_path, monkeypatch):
    """Point every Anchor data directory at a throwaway folder."""
    from anchor import app_config

    app = tmp_path / "appdata"
    monkeypatch.setattr(app_config, "APP_DIR", app)
    monkeypatch.setattr(app_config, "PROFILES_DIR", app / "profiles")
    monkeypatch.setattr(app_config, "STATE_DIR", app / "state")
    monkeypatch.setattr(app_config, "LOGS_DIR", app / "logs")
    monkeypatch.setattr(app_config, "SETTINGS_FILE", app / "settings.json")
    app_config.ensure_dirs()
    return app
