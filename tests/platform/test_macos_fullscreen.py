"""macOS full screen (Phase 5 task 4), with fakes."""

import sys
from types import SimpleNamespace as NS

import pytest

from taskpill.platform import macos
from taskpill.platform.base import Rect, WindowInfo, screen_containing
from tests.platform.test_macos import FakeScreen, fake_mac, rect  # noqa: F401 (fixture)

MBP = Rect(0, 0, 1512, 982)
MONITOR = Rect(1512, -98, 3432, 982)  # a 1920 × 1080 monitor to the right, a bit higher


def test_screen_containing_uses_the_window_middle():
    assert screen_containing(Rect(100, 100, 900, 700), [MBP, MONITOR]) == MBP
    assert screen_containing(Rect(1600, 0, 3000, 900), [MBP, MONITOR]) == MONITOR
    # mostly on the monitor, though it starts on the laptop
    assert screen_containing(Rect(1400, 0, 2400, 500), [MBP, MONITOR]) == MONITOR
    assert screen_containing(Rect(-900, 0, -100, 500), [MBP, MONITOR]) is None


def test_screen_rects_flip_every_screen_to_qt(fake_mac):  # noqa: F811
    fake_mac.screens = [FakeScreen(), FakeScreen(frame=rect(1512, 0, 1920, 1080))]
    assert macos.screen_rects() == [MBP, MONITOR]


def test_no_screens_no_rects(fake_mac):  # noqa: F811
    fake_mac.screens = []
    assert macos.screen_rects() == []


@pytest.fixture
def front(monkeypatch):
    state = NS(window=None, screens=[MBP, MONITOR])
    monkeypatch.setattr(macos, "front_window", lambda: state.window)
    monkeypatch.setattr(macos, "screen_rects", lambda: state.screens)
    return state


def test_a_full_screen_app_covers_its_whole_screen(front):
    front.window = WindowInfo(10, 900, "", rect=MBP)
    assert macos.MacFullscreen().is_fullscreen() is True


def test_full_screen_on_the_second_monitor(front):
    front.window = WindowInfo(10, 900, "", rect=MONITOR)
    assert macos.MacFullscreen().is_fullscreen() is True


def test_a_zoomed_window_stops_under_the_menu_bar(front):
    front.window = WindowInfo(10, 900, "", rect=Rect(0, 37, 1512, 982))
    assert macos.MacFullscreen().is_fullscreen() is False


def test_no_front_window_is_not_full_screen(front):
    assert macos.MacFullscreen().is_fullscreen() is False
    front.window = WindowInfo(10, 900, "")  # no bounds
    assert macos.MacFullscreen().is_fullscreen() is False


def test_window_bounds_come_with_the_list():
    infos = [{"kCGWindowNumber": 10, "kCGWindowOwnerPID": 500, "kCGWindowLayer": 0,
              "kCGWindowIsOnscreen": True,
              "kCGWindowBounds": {"X": 0, "Y": 37, "Width": 1512, "Height": 945}}]
    assert macos.windows_from_quartz(infos, own_pid=42)[0].rect == Rect(0, 37, 1512, 982)


def test_the_platform_has_full_screen(fake_mac):  # noqa: F811
    assert isinstance(macos.create_macos_platform().fullscreen, macos.MacFullscreen)


def test_a_full_screen_check_end_to_end(fake_mac):  # noqa: F811
    fake_mac.windows = [{"kCGWindowNumber": 10, "kCGWindowOwnerPID": 900, "kCGWindowLayer": 0,
                         "kCGWindowIsOnscreen": True,
                         "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 1512, "Height": 982}}]
    sys.modules["AppKit"].NSWorkspace = NS(sharedWorkspace=lambda: NS(
        frontmostApplication=lambda: NS(processIdentifier=lambda: 900)))
    assert macos.MacFullscreen().is_fullscreen() is True
