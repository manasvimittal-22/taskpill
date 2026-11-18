import sys
from pathlib import Path

import pytest

from taskpill import paths
from tests.helpers import load_hook_helper

hook = load_hook_helper()


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
@pytest.mark.parametrize(
    "env",
    [
        {},
        {"APPDATA": "C:\\Users\\m\\AppData\\Roaming"},  # publish-scan: ok (fake path)
        {"XDG_CONFIG_HOME": "/tmp/xdg"},
        {"TASKPILL_CONFIG_DIR": "/custom/place"},
    ],
)
def test_hook_helper_and_app_agree_on_the_config_dir(monkeypatch, platform, env):
    for key in ("APPDATA", "XDG_CONFIG_HOME", "TASKPILL_CONFIG_DIR"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, "platform", platform)
    assert hook.config_dir() == paths.config_dir()


def test_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("TASKPILL_CONFIG_DIR", str(tmp_path))
    assert paths.config_dir() == tmp_path
    assert paths.runtime_file() == tmp_path / "runtime.json"


def test_claude_settings_location():
    assert paths.claude_settings_file() == Path.home() / ".claude" / "settings.json"
