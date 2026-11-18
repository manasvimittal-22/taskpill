import json
from datetime import datetime, timedelta

import pytest

from taskpill.adapters.hooks_installer import (
    EVENTS,
    KEEP_BACKUPS,
    MARKER,
    HookCommand,
    HooksInstaller,
    SettingsFileError,
)

HOOK = HookCommand(
    command="C:\\TaskPill\\taskpill-hook.exe", args=("--app", "C:\\TaskPill\\TaskPill.exe")
)


class Ticker:
    """A clock that moves 1 s per call, so backups get distinct names."""

    def __init__(self):
        self.t = datetime(2026, 11, 17, 12, 0, 0)

    def __call__(self):
        self.t += timedelta(seconds=1)
        return self.t


@pytest.fixture
def settings(tmp_path):
    return tmp_path / ".claude" / "settings.json"


def installer(path, hook=HOOK):
    return HooksInstaller(path, hook, now=Ticker())


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def user_hook(command="echo hi"):
    return {"type": "command", "command": command}


def test_install_into_missing_file_creates_it(settings):
    result = installer(settings).install()
    assert result.changed
    assert result.backup is None  # nothing to back up
    data = read(settings)
    assert set(data["hooks"]) == {spec.name for spec in EVENTS}


def test_installed_handlers_have_the_expected_shape(settings):
    installer(settings).install()
    hooks = read(settings)["hooks"]

    pre = hooks["PreToolUse"][0]
    assert pre["matcher"] == "*"
    handler = pre["hooks"][0]
    assert handler == {
        "type": "command",
        "command": HOOK.command,
        "args": [*HOOK.args, MARKER],
        "timeout": 10,
        "async": True,
    }
    assert "matcher" not in hooks["UserPromptSubmit"][0]  # event has no matchers
    assert "async" not in hooks["SessionEnd"][0]["hooks"][0]  # must finish before exit


def test_keeps_everything_else_untouched(settings):
    settings.parent.mkdir(parents=True)
    original = {
        "model": "opus",
        "permissions": {"allow": ["Bash(git status)"]},
        "hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [user_hook("lint.sh")]}],
            "PreCompact": [{"hooks": [user_hook("save.sh")]}],
        },
    }
    settings.write_text(json.dumps(original), encoding="utf-8")

    installer(settings).install()
    data = read(settings)
    assert data["model"] == "opus"
    assert data["permissions"] == original["permissions"]
    assert data["hooks"]["PreCompact"] == original["hooks"]["PreCompact"]
    assert data["hooks"]["PreToolUse"][0] == original["hooks"]["PreToolUse"][0]
    assert len(data["hooks"]["PreToolUse"]) == 2


def test_install_twice_changes_nothing(settings):
    inst = installer(settings)
    inst.install()
    first = settings.read_text(encoding="utf-8")
    result = inst.install()
    assert not result.changed
    assert settings.read_text(encoding="utf-8") == first


def test_reinstall_with_a_new_path_replaces_ours(settings):
    installer(settings).install()
    moved = HookCommand(command="D:\\New\\taskpill-hook.exe", args=())
    installer(settings, moved).install()
    pre = read(settings)["hooks"]["PreToolUse"]
    assert len(pre) == 1
    assert pre[0]["hooks"][0]["command"] == "D:\\New\\taskpill-hook.exe"


def test_is_installed(settings):
    inst = installer(settings)
    assert not inst.is_installed()
    inst.install()
    assert inst.is_installed()
    inst.uninstall()
    assert not inst.is_installed()


def test_uninstall_restores_the_users_hooks_exactly(settings):
    settings.parent.mkdir(parents=True)
    original = {
        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [user_hook("lint.sh")]}]},
        "theme": "dark",
    }
    settings.write_text(json.dumps(original), encoding="utf-8")
    inst = installer(settings)
    inst.install()
    result = inst.uninstall()
    assert result.changed
    assert read(settings) == original


def test_uninstall_drops_empty_hooks_key(settings):
    settings.parent.mkdir(parents=True)
    settings.write_text('{"theme": "dark"}', encoding="utf-8")
    inst = installer(settings)
    inst.install()
    inst.uninstall()
    assert read(settings) == {"theme": "dark"}


def test_uninstall_keeps_user_handlers_that_share_our_group(settings):
    settings.parent.mkdir(parents=True)
    ours = {"type": "command", "command": "x", "args": [MARKER]}
    shared = {"hooks": {"Stop": [{"hooks": [user_hook("ding.sh"), ours]}]}}
    settings.write_text(json.dumps(shared), encoding="utf-8")
    installer(settings).uninstall()
    assert read(settings) == {"hooks": {"Stop": [{"hooks": [user_hook("ding.sh")]}]}}


def test_recognises_old_entries_with_the_marker_in_the_command(settings):
    settings.parent.mkdir(parents=True)
    legacy = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": f"hook {MARKER}"}]}]}}
    settings.write_text(json.dumps(legacy), encoding="utf-8")
    installer(settings).uninstall()
    assert read(settings) == {}


def test_uninstall_without_file_or_hooks_is_a_no_op(settings):
    assert not installer(settings).uninstall().changed
    settings.parent.mkdir(parents=True)
    settings.write_text('{"theme": "dark"}', encoding="utf-8")
    assert not installer(settings).uninstall().changed
    assert read(settings) == {"theme": "dark"}


def test_backup_is_made_before_each_change(settings):
    settings.parent.mkdir(parents=True)
    settings.write_text('{"theme": "dark"}', encoding="utf-8")
    result = installer(settings).install()
    assert result.backup is not None
    assert json.loads(result.backup.read_text(encoding="utf-8")) == {"theme": "dark"}


def test_only_the_newest_backups_are_kept(settings):
    settings.parent.mkdir(parents=True)
    settings.write_text("{}", encoding="utf-8")
    inst = installer(settings)
    for _ in range(KEEP_BACKUPS + 2):
        inst.install()
        inst.uninstall()
    backups = list(settings.parent.glob("settings.json.taskpill-backup-*"))
    assert len(backups) == KEEP_BACKUPS


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[1, 2]",
        '{"hooks": []}',
        '{"hooks": {"Stop": {"hooks": []}}}',
    ],
)
def test_refuses_to_touch_files_it_does_not_understand(settings, content):
    settings.parent.mkdir(parents=True)
    settings.write_text(content, encoding="utf-8")
    with pytest.raises(SettingsFileError):
        installer(settings).install()
    assert settings.read_text(encoding="utf-8") == content
    assert list(settings.parent.glob("*backup*")) == []


def test_empty_file_and_bom_are_fine(settings):
    settings.parent.mkdir(parents=True)
    settings.write_text("", encoding="utf-8")
    assert installer(settings).install().changed
    settings.write_text('\ufeff{"theme": "dark"}', encoding="utf-8")
    installer(settings).install()
    assert read(settings)["theme"] == "dark"


def test_non_ascii_is_kept_readable(settings):
    settings.parent.mkdir(parents=True)
    settings.write_text('{"note": "héllo ✓"}', encoding="utf-8")
    installer(settings).install()
    assert '"héllo ✓"' in settings.read_text(encoding="utf-8")


def test_a_failed_write_leaves_no_backup_behind(settings, monkeypatch):
    import taskpill.adapters.hooks_installer as hi

    settings.parent.mkdir(parents=True)
    settings.write_text('{"theme": "dark"}', encoding="utf-8")

    def denied(*_args, **_kwargs):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(hi, "write_text_atomic", denied)
    with pytest.raises(PermissionError):
        installer(settings).install()
    assert read(settings) == {"theme": "dark"}
    assert list(settings.parent.glob("*backup*")) == []
