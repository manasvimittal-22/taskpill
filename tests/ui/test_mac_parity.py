"""The whole app, the way it runs on a Mac, checked against what the Windows app does.

Manasvi (2026-11-22): "make test cases and test yourself to all functionality that
works like in my windows app". This builds the real TaskPillApp with the real macOS
platform (platform/macos.py); only the OS underneath is fake: the menu bar, the
window list, which app is in front, activating an app, Carbon, System Settings.

Each test names the Windows behaviour it mirrors. What fakes can't prove (that the
real macOS calls are spelled right) is in tests/platform/test_macos_real.py, which
the release workflow runs on a real Mac.
"""

import sys
import types
from types import SimpleNamespace as NS

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from taskpill.adapters.hooks_installer import HookCommand, HooksInstaller
from taskpill.adapters.settings_store import Settings, SettingsStore
from taskpill.app import TaskPillApp
from taskpill.domain.session import SessionState
from taskpill.platform import macos
from taskpill.platform.base import MenuBarInfo, Rect, WindowInfo, increase_contrast_colors
from taskpill.ui import geometry as g
from taskpill.ui.theme import high_contrast_palette
from tests.conftest import FakeClock, make_event
from tests.platform.test_macos_extras import FakeCarbon

# The offscreen test screen is 800 × 600. A notch from 340 to 460, a 37 pt bar,
# Wi-Fi and the clock from x = 700.
SCREEN = Rect(0, 0, 800, 600)
NOTCH_RIGHT = 460.0
ICONS = (Rect(700, 0, 730, 37), Rect(735, 0, 795, 37))
TERMINAL, SAFARI = 500, 900
# hook → claude → zsh → login → Terminal → launchd
CHAIN = [300, 301, 302, TERMINAL, 1]
TERMINAL_WINDOW = WindowInfo(11, TERMINAL, "", rect=Rect(100, 37, 700, 500))
SAFARI_WINDOW = WindowInfo(21, SAFARI, "", rect=Rect(0, 37, 800, 600))


class Mac:
    """The fake OS under platform/macos.py."""

    def __init__(self):
        self.menu_bar = MenuBarInfo(SCREEN, 37.0, NOTCH_RIGHT, ICONS)
        self.windows = [SAFARI_WINDOW, TERMINAL_WINDOW]  # front to back
        self.front = SAFARI_WINDOW
        self.activated = []
        self.carbon = FakeCarbon()
        self.reduce_motion = False
        self.increase_contrast = False
        self.dark = True
        self.policy = None
        self.activations = 0


class Sounds:
    def __init__(self):
        self.played = []

    def play(self, name):
        self.played.append(name)


@pytest.fixture
def mac(monkeypatch):
    world = Mac()
    monkeypatch.setattr(macos, "read_menu_bar", lambda: world.menu_bar)
    monkeypatch.setattr(macos, "list_windows", lambda on_screen_only=False: list(world.windows))
    monkeypatch.setattr(macos, "front_window", lambda: world.front)
    monkeypatch.setattr(macos, "screen_rects", lambda: [SCREEN])
    monkeypatch.setattr(macos, "ns_window", lambda _id: None)  # no NSWindow offscreen

    def activate(pid):
        world.activated.append(pid)
        world.front = next((w for w in world.windows if w.pid == pid), world.front)
        return True

    monkeypatch.setattr(macos, "activate_app", activate)
    monkeypatch.setattr(macos, "load_carbon", lambda: world.carbon)
    monkeypatch.setattr(macos.MacHotkey.__init__, "__defaults__", (lambda: world.carbon,))

    appkit = types.ModuleType("AppKit")
    def activate():
        world.activations += 1

    appkit.NSApplication = NS(sharedApplication=lambda: NS(
        setActivationPolicy_=lambda p: setattr(world, "policy", p), activate=activate))
    appkit.NSWorkspace = NS(sharedWorkspace=lambda: NS(
        accessibilityDisplayShouldReduceMotion=lambda: world.reduce_motion,
        accessibilityDisplayShouldIncreaseContrast=lambda: world.increase_contrast))
    appkit.NSUserDefaults = NS(standardUserDefaults=lambda: NS(
        stringForKey_=lambda key: "Dark" if world.dark else None))
    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    return world


@pytest.fixture
def app(qtbot, tmp_path, mac):
    settings = tmp_path / "config" / "settings.json"
    settings.parent.mkdir(parents=True)
    SettingsStore(settings).save(Settings(connect_asked=True))
    sounds = Sounds()
    clock = FakeClock()
    taskpill = TaskPillApp(
        QApplication.instance(), macos.create_macos_platform(), SettingsStore(settings),
        HooksInstaller(tmp_path / ".claude" / "settings.json",
                       HookCommand("/Applications/TaskPill.app/Contents/MacOS/taskpill-hook",
                                   ("--app", "/Applications/TaskPill.app"))),
        clock, quit_app=lambda: None, show_tray=False, sound_player=sounds,
    )
    qtbot.addWidget(taskpill.row)
    taskpill.start()
    taskpill.sounds_played = sounds.played
    taskpill.test_clock = clock
    yield taskpill
    # Stop it before the fake Mac goes away: left running, its timers read the real
    # macOS on a Mac runner and broke later tests (found on GitHub's Mac, 2026-11-22).
    taskpill.shutdown()


def settle(app):
    app.row._tick()
    app.controller.refresh()


def start_session(app, mac, sid="a", chain=CHAIN):
    mac.front = TERMINAL_WINDOW  # you type the prompt in Terminal
    app.handle_event(make_event("SessionStart", sid, pid_chain=chain, cwd="/Users/me/api"))
    app.handle_event(make_event("UserPromptSubmit", sid, prompt="fix the login bug",
                                pid_chain=chain, cwd="/Users/me/api"))
    mac.front = SAFARI_WINDOW  # then you go and read something
    settle(app)


# ---- the app is a menu-bar app (Windows: a tray app with no taskbar button) -----------------
def test_no_dock_icon(app, mac):
    assert mac.policy == macos.ACCESSORY


# ---- placement (Windows: left of the "^" arrow, sized to the taskbar) -----------------------
def test_a_fresh_mac_starts_as_a_circle(app, mac):
    # Manasvi, 2026-11-22: "for mac, default it to the circle size"
    start_session(app, mac)
    assert app.row.dims.is_circle
    assert app.row.shown_dims() == g.Dims(31, 31, min_height=g.BAR_MIN_HEIGHT)
    app.row.set_dims(g.Dims(300, 32))
    app.reset_size()
    assert app.row.dims.is_circle  # Reset size goes back to the circle on a Mac
    app.row.set_dims(g.Dims(300, 32))
    app.row.reset_size()  # the Reset button in resize mode too
    assert app.row.dims.is_circle


def test_a_working_session_shows_a_pill_right_of_the_notch(app, mac):
    app.row.set_dims(g.Dims())  # someone who chose the full pill
    start_session(app, mac)
    assert app.row.has_pills()
    assert app.row.anchor().x() == round(NOTCH_RIGHT + 8)
    assert app.row.anchor().y() == round(37 / 2)
    shown = app.row.shown_dims()
    assert shown.height == 31  # fitted to the 37 pt bar
    # 224 pt between the notch and Wi-Fi (700 - 8 - 468): narrower than the 232 set
    assert shown.width == 224
    assert app.row.dims.width == g.FULL_WIDTH  # what the user set is kept


def test_a_wide_menu_bar_keeps_the_set_width(app, mac):
    mac.menu_bar = MenuBarInfo(SCREEN, 37.0, 300.0, ICONS)
    app.driver._last_spot = None
    app.driver.place()
    app.row.set_dims(g.Dims())  # someone who chose the full pill
    start_session(app, mac)
    assert app.row.shown_dims().width == g.FULL_WIDTH


def test_two_sessions_become_circles_growing_right(app, mac):
    start_session(app, mac, "a")
    start_session(app, mac, "b", chain=[400, 401, TERMINAL, 1])
    settle(app)
    items = [app.row._items[s] for s in app.row._order]
    assert all(round(i.width.target) == 31 for i in items)  # circles, bar height
    assert items[0].x.target < items[1].x.target  # the first stays by the notch


def test_a_crowded_menu_bar_keeps_a_circle_in_the_bar(app, mac):
    mac.menu_bar = MenuBarInfo(SCREEN, 37.0, NOTCH_RIGHT, (Rect(470, 0, 520, 37),))
    app.driver._last_spot = None
    app.driver.place()
    assert app.row.anchor().y() == round(37 / 2)  # never under the bar
    assert app.row.shown_dims().is_circle


def test_the_bar_sliding_in_does_not_move_the_pill(app, mac):
    # "Automatically hide and show the menu bar": while hidden, macOS reports no icons;
    # when it slides in, the icons and a whole-width strip appear (bug, 2026-11-22).
    start_session(app, mac)
    mac.menu_bar = MenuBarInfo(SCREEN, 37.0, NOTCH_RIGHT, ())
    app.driver.place()
    hidden = (app.row.anchor(), app.row.shown_dims())
    mac.menu_bar = MenuBarInfo(SCREEN, 37.0, NOTCH_RIGHT, (Rect(0, 0, 800, 37), *ICONS))
    app.driver.place()
    assert (app.row.anchor(), app.row.shown_dims()) == hidden


def test_drag_and_reset_position(app, mac):
    start_session(app, mac)
    app.row.moved.emit(QPoint(300, 300))
    assert app.row.shown_dims() == app.row.dims
    app.reset_position()
    assert app.row.anchor().x() == round(NOTCH_RIGHT + 8)
    assert app.row.shown_dims().height == 31


# ---- states (same on both: working → needs you → done) -------------------------------------
def test_needs_you_then_done_with_sounds(app, mac):
    start_session(app, mac)
    app.handle_event(make_event("PermissionRequest", "a", tool_name="Bash", tool_input={},
                                pid_chain=CHAIN))
    assert app.store.get("a").state is SessionState.NEEDS_YOU
    app.test_clock.advance(60)  # chimes never play back to back
    app.handle_event(make_event("Stop", "a", pid_chain=CHAIN))
    assert app.store.get("a").state is SessionState.DONE
    assert app.sounds_played == ["needs_you", "done"]


# ---- click focus (Windows: raises the session's terminal window) ----------------------------
def test_clicking_the_pill_brings_terminal_forward(app, mac):
    start_session(app, mac)
    app.click("a")
    assert mac.activated == [TERMINAL]


def test_clicking_a_done_pill_brings_terminal_forward_and_clears_it(app, mac):
    start_session(app, mac)
    app.handle_event(make_event("Stop", "a", pid_chain=CHAIN))
    app.click("a")
    assert mac.activated == [TERMINAL]
    session = app.store.get("a")
    assert session is None or session.state is not SessionState.DONE


def test_iterm2_session_is_found_by_the_window_at_the_prompt(app, mac):
    iterm = WindowInfo(31, 700, "", rect=Rect(0, 37, 600, 500))
    mac.windows.append(iterm)
    chain = [600, 601, 650, 1]  # iTerm2's server hangs off launchd
    mac.front = iterm
    app.handle_event(make_event("UserPromptSubmit", "i", prompt="hi", pid_chain=chain))
    mac.front = SAFARI_WINDOW
    app.click("i")
    assert mac.activated == [700]


# ---- Done clears when you switch to its window (Manasvi, 2026-11-17) --------------------------
def test_switching_to_terminal_clears_done(app, mac):
    start_session(app, mac)
    app.handle_event(make_event("Stop", "a", pid_chain=CHAIN))
    app.driver._check_foreground()  # Safari still in front: stays
    assert app.store.get("a").state is SessionState.DONE
    mac.front = TERMINAL_WINDOW
    app.driver._check_foreground()
    session = app.store.get("a")
    assert session is None or session.state is not SessionState.DONE


# ---- full screen (Windows: hides working/done, still shows needs-you) ------------------------
def test_full_screen_hides_working_but_not_needs_you(app, mac):
    start_session(app, mac)
    start_session(app, mac, "b", chain=[400, 401, TERMINAL, 1])
    app.handle_event(make_event("PermissionRequest", "b", tool_name="Bash", tool_input={},
                                pid_chain=[400, 401, TERMINAL, 1]))
    mac.front = WindowInfo(41, SAFARI, "", rect=SCREEN)  # Safari in full screen
    app.driver._check_fullscreen()
    settle(app)
    shown = [s for s in app.row._order if not app.row._items[s].leaving]
    assert shown == ["b"]
    mac.front = SAFARI_WINDOW  # back out of full screen
    app.driver._check_fullscreen()
    settle(app)
    assert {s for s in app.row._order if not app.row._items[s].leaving} == {"a", "b"}


# ---- the jump shortcut (Windows: Ctrl+Alt+Space; Mac: Control+Option+Space) -------------------
def test_the_shortcut_jumps_to_the_waiting_session(app, mac):
    assert app.hotkey_active
    key, modifiers, _, _ = mac.carbon.registered
    assert (key, modifiers) == (49, macos.CONTROL_KEY | macos.OPTION_KEY)
    start_session(app, mac)
    app.handle_event(make_event("PermissionRequest", "a", tool_name="Bash", tool_input={},
                                pid_chain=CHAIN))
    mac.carbon.handler(None, None, None)  # the key is pressed
    QApplication.processEvents()
    assert mac.activated == [TERMINAL]


def test_a_key_owned_elsewhere_is_left_alone(qtbot, tmp_path, mac):
    mac.carbon = FakeCarbon(register=macos.HOT_KEY_EXISTS)
    settings = tmp_path / "s.json"
    SettingsStore(settings).save(Settings(connect_asked=True))
    app = TaskPillApp(QApplication.instance(), macos.create_macos_platform(),
                      SettingsStore(settings),
                      HooksInstaller(tmp_path / "c.json", HookCommand("h", ())),
                      FakeClock(), quit_app=lambda: None, show_tray=False)
    qtbot.addWidget(app.row)
    app.start()
    assert app.hotkey_active is False
    app.shutdown()


# ---- accessibility (Windows: animation effects + high-contrast themes, live) ------------------
def test_reduce_motion_follows_system_settings_live(app, mac):
    assert app._row_options().reduced_motion is False
    mac.reduce_motion = True
    app._check_system_prefs()
    assert app._row_options().reduced_motion is True


def test_increase_contrast_uses_accessible_colors_and_drops_the_glow(app, mac):
    mac.increase_contrast = True
    app._check_system_prefs()
    assert app._palette() == high_contrast_palette(increase_contrast_colors(dark=True))
    assert app._row_options().glow is False
    mac.dark = False
    app._check_system_prefs()
    assert app._palette() == high_contrast_palette(increase_contrast_colors(dark=False))


# ---- the right-click menu, resize mode and Settings take clicks (bug, 2026-11-22) -------------
def test_the_menu_makes_taskpill_active_first(app, mac):
    start_session(app, mac)
    before = mac.activations  # Settings opens by itself at start while not connected
    menu = app.open_pill_menu("a", app.row.geometry())
    assert mac.activations == before + 1
    menu.close()


def test_resize_and_settings_make_taskpill_active(app, mac):
    start_session(app, mac)
    before = mac.activations
    assert app.begin_resize("a")
    app.row.cancel_resize()
    app.open_settings().close()
    assert mac.activations == before + 2


def test_the_menu_items_still_do_their_job(app, mac):
    start_session(app, mac)
    menu = app.open_pill_menu("a", app.row.geometry())
    actions = {a.text(): a for a in menu.actions() if a.text()}
    actions["Go to api"].trigger()
    assert mac.activated == [TERMINAL]
    actions["Resize…"].trigger()
    assert app.row.resizing
    app.row.cancel_resize()
    menu.close()
