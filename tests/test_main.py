import json
import sys

import pytest

from taskpill import __version__, main


@pytest.fixture
def claude_settings(tmp_path, monkeypatch):
    path = tmp_path / ".claude" / "settings.json"
    monkeypatch.setattr(main.paths, "claude_settings_file", lambda: path)
    return path


def test_disconnect_removes_only_our_hooks(claude_settings):
    claude_settings.parent.mkdir(parents=True)
    claude_settings.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": "ding.sh"},
        {"type": "command", "command": "x", "args": ["--taskpill-hook"]},
    ]}]}}), encoding="utf-8")
    assert main.main(["--disconnect"]) == 0
    data = json.loads(claude_settings.read_text(encoding="utf-8"))
    assert data == {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "ding.sh"}]}]}}


def test_disconnect_without_settings_is_fine(claude_settings):
    assert main.main(["--disconnect"]) == 0
    assert not claude_settings.exists()


def test_disconnect_reports_a_broken_file(claude_settings):
    claude_settings.parent.mkdir(parents=True)
    claude_settings.write_text("{broken", encoding="utf-8")
    assert main.main(["--disconnect"]) == 1
    assert claude_settings.read_text(encoding="utf-8") == "{broken"


def test_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main.main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"TaskPill {__version__}"


def test_no_console_does_not_crash(monkeypatch):
    # In the installed (windowless) app, Python leaves stdout/stderr as None.
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    with pytest.raises(SystemExit):
        main.main(["--version"])
