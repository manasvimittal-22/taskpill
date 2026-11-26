"""The whole app with fakes: temp settings, temp ~/.claude/settings.json, fake platform."""

import json

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication

from taskpill.adapters.hooks_installer import HookCommand, HooksInstaller
from taskpill.adapters.settings_store import Settings, SettingsStore
from taskpill.app import TaskPillApp
from taskpill.platform.base import JUMP_KEYS, fallback_platform
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


class NotingPlatform:
    """The fallback platform, but its active-window probe records note_prompt calls."""

    def __init__(self, fail=False):
        self.platform = fallback_platform()
        self.noted = []
        self.fail = fail
        outer = self

        class Active:
            def foreground(self):
                return None

            def window_for(self, chain, project):
                return None

            def note_prompt(self, chain):
                if outer.fail:
                    raise OSError("boom")
                outer.noted.append(tuple(chain))

        self.platform.active = Active()


def build_with(qtbot, env, platform):
    app = TaskPillApp(
        QApplication.instance(), platform,
        SettingsStore(env["settings"]),
        HooksInstaller(env["claude"], HookCommand("hook.exe", ("--app", "TaskPill.exe"))),
        FakeClock(), quit_app=lambda: None, show_tray=False,
    )
    qtbot.addWidget(app.row)
    return app


def test_a_prompt_makes_the_app_remember_the_window_in_front(qtbot, env):
    fake = NotingPlatform()
    app = build_with(qtbot, env, fake.platform)
    app.handle_event(make_event("UserPromptSubmit", "a", pid_chain=[10, 20, 30]))
    app.handle_event(make_event("PreToolUse", "a", tool_name="Read", pid_chain=[10, 20, 30]))
    app.handle_event(make_event("UserPromptSubmit", "b"))  # no chain: nothing to remember
    assert fake.noted == [(10, 20, 30)]


def test_a_failing_window_probe_never_stops_the_event(qtbot, env):
    app = build_with(qtbot, env, NotingPlatform(fail=True).platform)
    app.handle_event(make_event("UserPromptSubmit", "a", pid_chain=[1, 2]))
    assert app.store.get("a") is not None


class FakeHotkey:
    def __init__(self, free=True):
        self.free = free
        self.callback = None
        self.registered = 0
        self.unregistered = 0

    def register(self, on_press):
        self.registered += 1
        if not self.free:
            return False
        self.callback = on_press
        return True

    def unregister(self):
        self.unregistered += 1
        self.callback = None


def hotkey_app(qtbot, env, hotkey, **settings):
    platform = fallback_platform()
    platform.hotkey = hotkey
    env["settings"].parent.mkdir(parents=True, exist_ok=True)
    SettingsStore(env["settings"]).save(Settings(connect_asked=True, **settings))
    app = build_with(qtbot, env, platform)
    app.start()
    return app


def test_the_shortcut_starts_listening_at_start(qtbot, env):
    hotkey = FakeHotkey()
    app = hotkey_app(qtbot, env, hotkey)
    assert app.hotkey_active and hotkey.callback is not None


def test_pressing_the_shortcut_goes_to_the_session_waiting_longest(qtbot, env):
    hotkey = FakeHotkey()
    app = hotkey_app(qtbot, env, hotkey)
    focused = []
    app.controller._focus = lambda s: focused.append(s.session_id)
    app.handle_event(make_event("UserPromptSubmit", "a"))
    app.handle_event(make_event("PermissionRequest", "a", tool_name="Bash", tool_input={}))
    app.handle_event(make_event("UserPromptSubmit", "b"))
    app.handle_event(make_event("PermissionRequest", "b", tool_name="Bash", tool_input={}))
    hotkey.callback()  # from the hotkey thread: the signal brings it to the main thread
    qtbot.waitUntil(lambda: focused == ["a"], timeout=1000)


def test_the_shortcut_does_nothing_when_no_session_needs_you(qtbot, env):
    hotkey = FakeHotkey()
    app = hotkey_app(qtbot, env, hotkey)
    focused = []
    app.controller._focus = focused.append
    app.handle_event(make_event("UserPromptSubmit", "a"))
    app.jump_to_waiting()
    assert focused == []


def test_turned_off_it_never_listens(qtbot, env):
    hotkey = FakeHotkey()
    app = hotkey_app(qtbot, env, hotkey, jump_hotkey=False)
    assert not app.hotkey_active and hotkey.registered == 0


def test_switching_it_off_and_on_in_settings(qtbot, env):
    hotkey = FakeHotkey()
    app = hotkey_app(qtbot, env, hotkey)
    window = app.open_settings()
    window.jump_hotkey.setChecked(False)
    assert not app.hotkey_active and hotkey.callback is None
    assert window.jump_hint.text() == "Turned off."
    window.jump_hotkey.setChecked(True)
    assert app.hotkey_active and hotkey.callback is not None
    assert "Works from any app" in window.jump_hint.text()
    assert SettingsStore(env["settings"]).load().jump_hotkey is True
    window.close()


def test_a_key_owned_by_another_app_is_explained(qtbot, env):
    hotkey = FakeHotkey(free=False)
    app = hotkey_app(qtbot, env, hotkey)
    assert not app.hotkey_active
    window = app.open_settings()
    assert f"Another app is using {'+'.join(JUMP_KEYS)}" in window.jump_hint.text()
    window.close()


def test_settings_lists_the_shortcuts(qtbot, env):
    app = build_with(qtbot, env, fallback_platform())
    window = app.open_settings()
    names = [caps.accessibleName() for caps in window.key_caps]
    assert names == [" plus ".join(JUMP_KEYS), "Tab", "Space", "← plus →"]
    window.close()


def test_start_when_not_connected_opens_settings(qtbot, env):
    app, _, _ = build(qtbot, env)
    app.start()
    window = app._settings_window
    assert window is not None and window.isVisible()
    assert window.status_text.text() == "Not connected to Claude Code"
    assert window.connect_button.text() == "Connect"
    window.close()


def test_connect_box_is_highlighted_only_when_not_connected(qtbot, env):
    app, _, _ = build(qtbot, env)
    window = app.open_settings()
    assert window.connect_box.property("needsConnect") is True
    window.set_connected(True)
    assert window.connect_box.property("needsConnect") is False
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
    app.start(background=True)
    assert app._connect_dialog is None
    assert app._settings_window is None  # a hook start stays quiet


def test_user_start_when_connected_opens_settings(qtbot, env):
    app, _, _ = build(qtbot, env)
    app._connect()
    app.start()  # the user double-clicked the app (bug 2026-11-26: nothing showed)
    window = app._settings_window
    assert window is not None and window.isVisible()
    assert window.status_text.text() == "Connected to Claude Code"
    window.close()


def test_settings_request_from_a_second_launch(qtbot, env):
    from taskpill.adapters.event_server import EventServer
    from taskpill.adapters.runtime_file import (
        RuntimeInfo,
        ask_running_app_to_show_settings,
        write_runtime,
    )

    app, _, _ = build(qtbot, env)
    asked = []
    server = EventServer(sink=lambda e: None, token="t" * 20, on_settings=lambda: asked.append(1))
    port = server.start()
    try:
        path = env["claude"].parent / "runtime.json"
        write_runtime(path, RuntimeInfo(port, server.token, 1, "0"))
        assert ask_running_app_to_show_settings(path)
        assert asked == [1]
    finally:
        server.stop()
    assert not ask_running_app_to_show_settings(path)  # nobody is listening now


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
    assert window.status_text.text() == "Connected to Claude Code"
    window.hide()
    app._installer.uninstall()  # e.g. another copy, or a manual edit
    window = app.open_settings()
    assert window.status_text.text() == "Not connected to Claude Code"
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


def test_tray_menu_items_really_fire_their_signals(qtbot, env):
    """Regression: the menu items were wired to Signal objects and did nothing."""
    app, _, _ = build(qtbot, env)
    hits = []
    app.tray.connect_toggled.connect(lambda: hits.append("connect"))
    app.tray.settings_requested.connect(lambda: hits.append("settings"))
    app.tray.reset_position_requested.connect(lambda: hits.append("reset"))
    app.tray.quit_requested.connect(lambda: hits.append("quit"))
    for action in app.tray._menu.actions():
        if action.text() in ("Settings…", "Reset position", "Quit TaskPill"):
            action.trigger()
    app.tray._connect_action.trigger()
    assert hits == ["settings", "reset", "quit", "connect"]
