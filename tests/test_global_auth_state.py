import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from launcher_app.app import MainWindow


def test_global_auth_state_defaults_to_offline(tmp_path, monkeypatch):
    profile_path = tmp_path / "profiles.json"
    profile_path.write_text(json.dumps({"profiles": [], "global_auth": {}}), encoding="utf-8")

    monkeypatch.setattr("launcher_app.app.PROFILES_PATH", str(profile_path))

    window = MainWindow.__new__(MainWindow)
    state = window._default_global_auth_state()

    assert state["auth_mode"] == "Offline"
    assert state["ms_refresh_token"] == ""
