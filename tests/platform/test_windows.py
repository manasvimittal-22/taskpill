"""Real Win32 calls on this machine. Read-only: nothing is moved or focused."""

import os
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


@pytest.fixture(scope="module")
def win():
    from taskpill.platform import windows

    return windows


def test_reads_the_taskbar(win):
    info = win.read_taskbar()
    assert info is not None
    assert info.rect.width > 0 and info.rect.height > 0
    if info.tray is not None:
        assert info.rect.left <= info.tray.left < info.rect.right


def test_ui_automation_finds_the_arrow_inside_the_taskbar(win):
    uia = win._UiaTaskbar()
    info = win.read_taskbar(uia)
    if info.arrow is None:
        pytest.skip("this taskbar has no '^' arrow (or UI Automation is unavailable)")
    assert info.rect.left <= info.arrow.left < info.arrow.right <= info.rect.right
    if info.tray is not None:
        assert abs(info.arrow.left - info.tray.left) < 80


def test_lists_windows(win):
    found = win.list_windows()
    assert all(isinstance(w.handle, int) and w.pid > 0 and w.title for w in found)


def test_fullscreen_probe_returns_a_bool(win):
    assert win.WindowsFullscreen(own_pid=os.getpid()).is_fullscreen() in (True, False)


def test_placement_spot_is_on_a_screen(win):
    from taskpill.platform.base import Rect, ScreenInfo

    # rough stand-in for Qt's screen list: a big 100% screen at the origin
    spot = win.WindowsPlacement().spot([ScreenInfo(Rect(0, 0, 10000, 10000), 1.0)])
    if spot is not None:
        assert 0 <= spot.x <= 10000 and 0 <= spot.y <= 10000
