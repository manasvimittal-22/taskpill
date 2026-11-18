"""The whole app with fakes: temp settings, temp ~/.claude/settings.json, fake platform."""

import json

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication

from taskpill.adapters.hooks_installer import HookCommand, HooksInstaller
from taskpill.adapters.settings_store import Settings, SettingsStore
from taskpill.app import TaskPillApp
from taskpill.platform.base import fallback_platform
from taskpill.ui.icon import TrayState
from tests.conftest import FakeClock, make_event


@pytest.fixture
def env(tmp_path):
    return {
        "settings": tmp_path / "config" / "settings.json",
        "claude": tmp_path / ".claude" / "settings.json",
    }


def build(qtbot, env, demo=False):
    quits = []
    clock = FakeClock()
    app = TaskPillApp(
        QApplication.instance(),
        fallback_platform(),
        SettingsStore(env["settings"]),
        HooksInstaller(env["claude"], HookCommand("hook.exe", ("--app", "TaskPill.exe"))),
        clock,
        quit_app=lambda: quits.append(True),
        demo=demo,
        show_tray=False,
    )
    qtbot.addWidget(app.row)
    return app, clock, quits


def test_start_when_not_connected_opens_settings(qtbot, env):
    app, _, _ = build(qtbot, env)
    app.start()
    window = app._settings_window
    assert window is not None and window.isVisible()
    assert window.status_text.text() == "Not connected"
    assert window.connect_button.text() == "Connect"
    window.close()


def test_settings_quit_button_quits(qtbot, env):
    app, _, quits = build(qtbot, env)
    window = app.open_settings()
    window.quit_button.click()
    assert quits == [True]
    window.close()


def test_connect_installs_the_hooks(qtbot, env):
    app, _, _ = build(qtbot, env)
    app.start()
    app._settings_window.close()
    app.ask_to_connect()
    app._connect_dialog.connect_button.click()
    assert app.is_connected()
    hooks = json.loads(env["claude"].read_text(encoding="utf-8"))["hooks"]
    assert "PreToolUse" in hooks
    assert app._connect_dialog is None  # closed after success


def test_connect_problem_is_shown_and_nothing_changes(qtbot, env):
    env["claude"].parent.mkdir(parents=True)
    env["claude"].write_text("{broken", encoding="utf-8")
    app, _, _ = build(qtbot, env)
    app.start()
    app._settings_window.close()
    dialog = app.ask_to_connect()
    dialog.connect_button.click()
    assert dialog.isVisible()
    assert "isn't valid JSON" in dialog.error.text()
    assert "Nothing was changed" in dialog.error.text()
    assert env["claude"].read_text(encoding="utf-8") == "{broken"


def test_disconnect_from_settings(qtbot, env):
    app, _, _ = build(qtbot, env)
    app._connect()
    window = app.open_settings()
    assert window.connect_button.text() == "Disconnect"
    window.connect_button.click()
    assert not app.is_connected()
    assert window.connect_button.text() == "Connect"


def test_settings_changes_apply_and_are_saved(qtbot, env):
    app, _, _ = build(qtbot, env)
    window = app.open_settings()
    window.glow.click()
    window.reduced.click()
    saved = SettingsStore(env["settings"]).load()
    assert saved.glow is False and saved.reduced_motion is True
    assert app.row._options.glow is False
    assert app.row._options.reduced_motion is True


def test_accent_changes_the_working_color(qtbot, env):
    app, _, _ = build(qtbot, env)
    before = app.row._palette.working
    app.open_settings().swatches._choose("rose")
    assert app.row._palette.working != before
    assert SettingsStore(env["settings"]).load().accent == "rose"


def test_dragged_position_is_remembered_and_reset(qtbot, env):
    app, _, _ = build(qtbot, env)
    app.row.moved.emit(QPoint(400, 300))
    key = app._screen_key()
    assert SettingsStore(env["settings"]).load().positions[key] == [400, 300]

    again, _, _ = build(qtbot, env)
    assert again.driver.user_placed
    assert again.row.anchor() == QPoint(400, 300)

    again.reset_position()
    assert key not in SettingsStore(env["settings"]).load().positions
    assert not again.driver.user_placed


def test_tray_follows_the_sessions(qtbot, env):
    app, _, _ = build(qtbot, env)
    assert app.tray.state is TrayState.IDLE
    app.handle_event(make_event("UserPromptSubmit", "a"))
    assert app.tray.state is TrayState.WORKING
    app.handle_event(make_event("PermissionRequest", "a", tool_name="Bash"))
    assert app.tray.state is TrayState.NEEDS_YOU
    app.handle_event(make_event("SessionEnd", "a"))
    assert app.tray.state is TrayState.IDLE


def test_quits_after_being_idle(qtbot, env):
    app, clock, quits = build(qtbot, env)
    clock.advance(9 * 60)
    app._check_idle()
    assert quits == []
    clock.advance(60)
    app._check_idle()
    assert quits == [True]


def test_never_quits_while_settings_are_open(qtbot, env):
    app, clock, quits = build(qtbot, env)
    app.open_settings()
    clock.advance(3600)
    app._check_idle()
    assert quits == []


def test_working_sessions_keep_it_running(qtbot, env):
    app, clock, quits = build(qtbot, env)
    app.handle_event(make_event("UserPromptSubmit", "a"))
    clock.advance(3600)
    app._check_idle()
    assert quits == []


def test_demo_never_asks_and_never_quits(qtbot, env):
    app, clock, quits = build(qtbot, env, demo=True)
    app.start()
    assert app._connect_dialog is None
    clock.advance(10**6)
    app._check_idle()
    assert quits == []


def test_start_when_connected_refreshes_quietly(qtbot, env):
    app, _, _ = build(qtbot, env)
    app._connect()
    app.settings = Settings()  # connect_asked is False, but we're connected
    app.start()
    assert app._connect_dialog is None


def test_snapshots_are_published_for_the_vs_code_extension(qtbot, env):
    app, _, _ = build(qtbot, env)
    sent = []
    app.set_publisher(sent.append)
    assert sent[-1] == {"version": 1, "sessions": []}
    app.handle_event(make_event("UserPromptSubmit", "a", cwd="C:/code/taskpill", prompt="Fix it"))
    session = sent[-1]["sessions"][0]
    assert session["id"] == "a"
    assert session["project"] == "taskpill"
    assert session["kind"] == "working"
    assert session["prompt"] == "Fix it"
    app.handle_event(make_event("PermissionRequest", "a", tool_name="Bash",
                                tool_input={"command": "npm i"}))
    assert sent[-1]["sessions"][0]["kind"] == "needs_you"
    assert sent[-1]["sessions"][0]["detail"] == "Needs permission to run npm i"


def test_snapshot_ignores_the_fullscreen_filter(qtbot, env):
    app, _, _ = build(qtbot, env)
    sent = []
    app.set_publisher(sent.append)
    app.handle_event(make_event("UserPromptSubmit", "a"))
    app.controller.set_quiet(True)
    assert len(sent[-1]["sessions"]) == 1


def test_click_from_vs_code_acknowledges_done(qtbot, env):
    app, _, _ = build(qtbot, env)
    app.handle_event(make_event("UserPromptSubmit", "a"))
    app.handle_event(make_event("Stop", "a"))
    app.click("a")
    assert app.store.visible() == []
    app.click("unknown")  # harmless


def test_out_of_usage_shows_in_the_tray_and_a_click_clears_it(qtbot, env):
    app, _, _ = build(qtbot, env)
    states = []
    app.tray.set_state = states.append
    app.handle_event(make_event("UserPromptSubmit", "a"))
    app.handle_event(make_event("StopFailure", "a", error="rate_limit"))
    assert states[-1] is TrayState.LIMITED
    menu = app.open_pill_menu("a", QRect(800, 900, 232, 32))
    assert "Clear" in [a.text() for a in menu.actions()]
    menu.close()
    app.click("a")
    assert app.store.visible() == []


def test_settings_and_tray_show_the_real_connection_after_an_outside_change(qtbot, env):
    """Bug (Manasvi, 2026-11-17): Settings still said "Connected" after the hooks
    were removed outside the app, because the window was built once and reused."""
    app, _, _ = build(qtbot, env)
    app._connect()
    window = app.open_settings()
    assert window.status_text.text() == "Connected"
    window.hide()
    app._installer.uninstall()  # e.g. another copy, or a manual edit
    window = app.open_settings()
    assert window.status_text.text() == "Not connected"
    app.tray.menu_opening.emit()
    assert app.tray._connect_action.text() == "Connect to Claude Code"


def test_a_failed_disconnect_is_reported_not_swallowed(qtbot, env, monkeypatch):
    app, _, _ = build(qtbot, env)
    app._connect()
    notes = []
    app.tray.notify = lambda title, text: notes.append((title, text))

    def denied():
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(app._installer, "uninstall", denied)
    app._toggle_connection()
    assert notes and "Access is denied" in notes[0][1]
    assert app.is_connected()  # nothing changed, and the app says so


def test_sounds_play_when_a_session_needs_you_or_finishes(qtbot, env):
    """Manasvi, 2026-11-17: subtle sounds on needs-you and done, each can be off."""

    class Recorder:
        played: list = []

        def play(self, name):
            self.played.append(name)

    quits = []
    clock = FakeClock()
    rec = Recorder()
    app = TaskPillApp(QApplication.instance(), fallback_platform(), SettingsStore(env["settings"]),
                      HooksInstaller(env["claude"], HookCommand("h.exe", ())), clock,
                      quit_app=lambda: quits.append(1), show_tray=False, sound_player=rec)
    qtbot.addWidget(app.row)
    app.handle_event(make_event("UserPromptSubmit", "a"))
    app.handle_event(make_event("PermissionRequest", "a", tool_name="Bash"))
    clock.t += 5
    app.handle_event(make_event("PostToolUse", "a", tool_name="Bash"))  # back to working: quiet
    clock.t += 5
    app.handle_event(make_event("Stop", "a"))
    assert rec.played == ["needs_you", "done"]
    app._save(Settings(sound_done=False))  # turned off in Settings
    clock.t += 5
    app.handle_event(make_event("UserPromptSubmit", "a"))
    app.handle_event(make_event("Stop", "a"))
    assert rec.played == ["needs_you", "done"]


def test_update_available_shows_in_tray_and_settings(qtbot, env, monkeypatch):
    """Phase 10 (Manasvi, 2026-11-17): the installed app finds a newer release."""
    from pathlib import Path as P

    from taskpill.domain.updates import Release
    from taskpill.services.updates import UpdateService

    release = Release("0.2.0", "https://github.com/manasvimittal-22/taskpill/releases/v0.2.0",
                      "https://github.com/x/TaskPill-Setup-0.2.0.exe")
    launched = []
    service = UpdateService("0.1.0", lambda: release, lambda r: P("C:/t/setup.exe"),
                            launched.append, lambda: 50_000.0,
                            run_in_background=lambda fn: fn())
    app = TaskPillApp(QApplication.instance(), fallback_platform(), SettingsStore(env["settings"]),
                      HooksInstaller(env["claude"], HookCommand("h.exe", ())), FakeClock(),
                      quit_app=lambda: None, show_tray=False, updates=service)
    qtbot.addWidget(app.row)
    notes = []
    app.tray.inform = lambda title, text: notes.append(title)
    app.check_updates_now()
    assert notes == ["TaskPill 0.2.0 is available"]
    assert app.tray._update_action.isVisible()
    assert SettingsStore(env["settings"]).load().last_update_check > 0
    window = app.open_settings()
    assert "0.2.0 is available" in window.update_text.text()
    assert window.update_button.text() == "Update to 0.2.0"
    window.update_button.click()
    assert launched == [P("C:/t/setup.exe")]


def test_portable_opens_the_download_page(qtbot, env, monkeypatch):
    from taskpill.domain.updates import Release
    from taskpill.services.updates import UpdateService

    release = Release("0.2.0", "https://github.com/manasvimittal-22/taskpill/releases/v0.2.0", None)
    service = UpdateService("0.1.0", lambda: release, lambda r: None, lambda p: None,
                            lambda: 50_000.0, run_in_background=lambda fn: fn())
    app = TaskPillApp(QApplication.instance(), fallback_platform(), SettingsStore(env["settings"]),
                      HooksInstaller(env["claude"], HookCommand("h.exe", ())), FakeClock(),
                      quit_app=lambda: None, show_tray=False, updates=service, portable=True)
    qtbot.addWidget(app.row)
    opened = []
    monkeypatch.setattr("taskpill.app.QDesktopServices.openUrl", lambda url: opened.append(url))
    app.check_updates_now()
    app.install_update()
    assert [u.toString() for u in opened] == [release.page_url]


def test_from_source_there_is_no_update_check(qtbot, env):
    app, _, _ = build(qtbot, env)
    assert app.updates is None
    window = app.open_settings()
    assert "come with git" in window.update_text.text()
    assert window.update_button.isHidden()
