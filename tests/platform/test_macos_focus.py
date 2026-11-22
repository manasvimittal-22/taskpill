"""macOS click focus and "which window is in front" (Phase 5 task 3), with fakes."""

import sys
from types import SimpleNamespace as NS

import pytest

from taskpill.platform import macos
from taskpill.platform.base import WindowInfo, WindowMemory, choose_window
from tests.platform.test_macos import fake_mac  # noqa: F401 (fixture)


def app_window(number, pid, *, layer=0, w=800, h=600, alpha=1.0, onscreen=True):
    return {"kCGWindowNumber": number, "kCGWindowOwnerPID": pid, "kCGWindowLayer": layer,
            "kCGWindowAlpha": alpha, "kCGWindowIsOnscreen": onscreen,
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": w, "Height": h}}


def win(handle, pid):
    return WindowInfo(handle, pid, "")


# ---- pure rules (base.py) ------------------------------------------------------------------
def test_the_preferred_window_is_a_last_resort_only_when_asked():
    windows = [WindowInfo(1, 900, "Safari"), WindowInfo(2, 700, "")]
    chain = [300, 650, 1]  # never reaches pid 700 (iTerm2's server is launchd's child)
    assert choose_window(windows, chain, "api", preferred=2) is None  # Windows: strict
    found = choose_window(windows, chain, "api", preferred=2, preferred_as_last_resort=True)
    assert found.handle == 2


def test_a_window_in_the_chain_still_beats_the_last_resort():
    windows = [WindowInfo(1, 500, ""), WindowInfo(2, 700, "")]
    found = choose_window(windows, [300, 500], "api", preferred=2, preferred_as_last_resort=True)
    assert found.handle == 1


def test_a_closed_last_resort_window_gives_nothing():
    found = choose_window([WindowInfo(1, 900, "")], [300], "api", preferred=2,
                          preferred_as_last_resort=True)
    assert found is None


def test_a_loose_memory_keeps_windows_outside_the_chain():
    strict, loose = WindowMemory(), WindowMemory(strict=False)
    front = WindowInfo(30, 700, "")
    strict.remember([300, 1], front)
    loose.remember([300, 1], front)
    assert strict.recall([300, 1]) is None
    assert loose.recall([300, 1]) == 30
    loose.remember([], front)  # no chain: nothing to key it by
    assert loose.recall([]) is None


# ---- reading windows ------------------------------------------------------------------------
def test_only_real_app_windows_are_listed():
    infos = [
        app_window(10, 500),  # Terminal
        app_window(11, 600, layer=macos.STATUS_ITEM_LAYER),  # a menu-bar icon
        app_window(12, 700, w=1, h=1),  # a helper window
        app_window(13, 800, alpha=0.0),  # invisible
        app_window(14, 42),  # our own window
        app_window(15, 500, onscreen=False),  # Terminal, on another Space or minimized
        {"kCGWindowNumber": 16, "kCGWindowLayer": 0},  # no owner
    ]
    windows = macos.windows_from_quartz(infos, own_pid=42)
    assert [(w.handle, w.pid, w.minimized) for w in windows] == [(10, 500, False), (15, 500, True)]
    assert all(w.title == "" for w in windows)  # titles need a permission we don't ask for


def test_list_windows_asks_quartz(fake_mac):  # noqa: F811
    fake_mac.windows = [app_window(10, 500), app_window(11, 600, layer=25)]
    assert [w.handle for w in macos.list_windows()] == [10]


def test_front_window_is_the_frontmost_apps_first_window(fake_mac):  # noqa: F811
    fake_mac.windows = [app_window(20, 900), app_window(10, 500), app_window(11, 500)]
    sys.modules["AppKit"].NSWorkspace = NS(sharedWorkspace=lambda: NS(
        frontmostApplication=lambda: NS(processIdentifier=lambda: 500)))
    assert macos.front_window().handle == 10
    sys.modules["AppKit"].NSWorkspace = NS(sharedWorkspace=lambda: NS(
        frontmostApplication=lambda: None))
    assert macos.front_window() is None


# ---- focus and the window in front ----------------------------------------------------------
# A session in Terminal: hook → claude (300) → zsh (301) → login (302) → Terminal (500) → launchd
TERMINAL_CHAIN = [300, 301, 302, 500, 1]


@pytest.fixture
def desktop(monkeypatch):
    state = NS(windows=[], front=None, activated=[])
    monkeypatch.setattr(macos, "list_windows", lambda on_screen_only=False: state.windows)
    monkeypatch.setattr(macos, "front_window", lambda: state.front)
    monkeypatch.setattr(macos, "activate_app", lambda pid: state.activated.append(pid) or True)
    return state


def test_a_click_brings_the_terminal_forward(desktop):
    desktop.windows = [win(20, 900), win(10, 500)]  # Safari in front, then Terminal
    focuser = macos.MacFocuser(WindowMemory(strict=False))
    assert focuser.focus(TERMINAL_CHAIN, "api") is True
    assert desktop.activated == [500]


def test_a_click_with_no_window_does_nothing(desktop):
    desktop.windows = [win(20, 900)]
    assert macos.MacFocuser(WindowMemory(strict=False)).focus([300, 1], "api") is False
    assert desktop.activated == []


def test_iterm2_sessions_are_found_through_the_window_in_front_at_the_prompt(desktop):
    chain = [300, 301, 650, 1]  # the chain never reaches iTerm2 (pid 700)
    memory = WindowMemory(strict=False)
    active = macos.MacActiveWindow(memory)
    desktop.front = win(30, 700)
    active.note_prompt(chain)
    desktop.windows = [win(20, 900), win(30, 700)]
    assert active.window_for(chain, "api") == 30
    macos.MacFocuser(memory).focus(chain, "api")
    assert desktop.activated == [700]


def test_the_remembered_terminal_window_wins_over_its_other_windows(desktop):
    memory = WindowMemory(strict=False)
    active = macos.MacActiveWindow(memory)
    desktop.front = win(11, 500)
    active.note_prompt(TERMINAL_CHAIN)
    desktop.windows = [win(10, 500), win(11, 500)]
    assert active.window_for(TERMINAL_CHAIN, "api") == 11


def test_foreground_is_the_front_window_number(desktop):
    active = macos.MacActiveWindow(WindowMemory(strict=False))
    assert active.foreground() is None
    desktop.front = win(10, 500)
    assert active.foreground() == 10


# ---- activating an app ----------------------------------------------------------------------
class FakeApp:
    def __init__(self, activates=True, path="/System/Applications/Utilities/Terminal.app"):
        self.activates, self.path, self.options = activates, path, None

    def activateWithOptions_(self, options):  # noqa: N802 (AppKit naming)
        self.options = options
        return self.activates

    def bundleURL(self):  # noqa: N802
        return NS(path=lambda: self.path) if self.path else None


TERMINAL_APP = "/System/Applications/Utilities/Terminal.app"


@pytest.fixture
def running(monkeypatch, fake_mac):  # noqa: F811
    state = NS(apps={}, opened=[])
    sys.modules["AppKit"].NSRunningApplication = NS(
        runningApplicationWithProcessIdentifier_=lambda pid: state.apps.get(pid))
    monkeypatch.setattr(macos.subprocess, "Popen", lambda args, **kw: state.opened.append(args))
    return state


def test_activate_on_macos_13_asks_the_app_directly(running, monkeypatch):
    monkeypatch.setattr(macos, "macos_major", lambda: 13)
    running.apps[500] = app = FakeApp()
    assert macos.activate_app(500) is True
    assert app.options == macos.ACTIVATE_IGNORING_OTHER_APPS
    assert running.opened == []


def test_activate_on_macos_14_also_asks_launchservices(running, monkeypatch):
    monkeypatch.setattr(macos, "macos_major", lambda: 14)
    running.apps[500] = FakeApp()
    assert macos.activate_app(500) is True
    assert running.opened == [["open", "-a", TERMINAL_APP]]


def test_a_refused_activation_falls_back_to_launchservices(running, monkeypatch):
    monkeypatch.setattr(macos, "macos_major", lambda: 13)
    running.apps[500] = FakeApp(activates=False)
    assert macos.activate_app(500) is True
    assert running.opened == [["open", "-a", TERMINAL_APP]]


def test_activate_a_process_that_is_gone(running):
    assert macos.activate_app(12345) is False


def test_a_refused_activation_without_a_bundle_reports_failure(running, monkeypatch):
    monkeypatch.setattr(macos, "macos_major", lambda: 13)
    running.apps[500] = FakeApp(activates=False, path=None)
    assert macos.activate_app(500) is False


def test_macos_major_reads_the_version(monkeypatch):
    monkeypatch.setattr(macos._platform, "mac_ver", lambda: ("14.5", ("", "", ""), "arm64"))
    assert macos.macos_major() == 14
    monkeypatch.setattr(macos._platform, "mac_ver", lambda: ("", ("", "", ""), ""))
    assert macos.macos_major() == 0
