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


def test_foreground_window_is_described(win):
    front = win.foreground_window()
    if front is None:
        pytest.skip("no window in front (locked screen?)")
    assert front.handle and front.pid > 0 and isinstance(front.class_name, str)


def test_noting_a_prompt_never_raises(win):
    # Whatever is in front, remembering it must be safe (read-only).
    win.WindowsActiveWindow().note_prompt([os.getpid()])
    win.WindowsActiveWindow().note_prompt([])


def test_fullscreen_probe_returns_a_bool(win):
    assert win.WindowsFullscreen(own_pid=os.getpid()).is_fullscreen() in (True, False)


def test_placement_spot_is_on_a_screen(win):
    from taskpill.platform.base import Rect, ScreenInfo

    # rough stand-in for Qt's screen list: a big 100% screen at the origin
    spot = win.WindowsPlacement().spot([ScreenInfo(Rect(0, 0, 10000, 10000), 1.0)])
    if spot is not None:
        assert 0 <= spot.x <= 10000 and 0 <= spot.y <= 10000


def test_reads_the_accessibility_choices(win):
    prefs = win.WindowsSystemPrefs().read()
    assert isinstance(prefs.reduce_motion, bool)
    if prefs.high_contrast is not None:
        for color in vars(prefs.high_contrast).values():
            assert len(color) == 7 and color.startswith("#")


class _FakeUser32:
    """Stands in for user32 so the high-contrast path runs on a normal desktop."""

    def __init__(self, struct, high_contrast, animations=True):
        self.struct, self.high_contrast, self.animations = struct, high_contrast, animations
        # COLORREF is 0xBBGGRR
        self.colors = {5: 0x000000, 8: 0xFFFFFF, 26: 0x00FFFF, 13: 0xFFEB1A, 17: 0x3FF23F}

    def SystemParametersInfoW(self, action, ui_param, pointer, flags):  # noqa: N802
        import ctypes

        if action == 0x1042:
            ctypes.cast(pointer, ctypes.POINTER(ctypes.c_int)).contents.value = int(self.animations)
        elif action == 0x0042:
            info = ctypes.cast(pointer, ctypes.POINTER(self.struct)).contents
            info.dwFlags = 1 if self.high_contrast else 0
        return 1

    def GetSysColor(self, index):  # noqa: N802
        return self.colors[index]


def test_high_contrast_colors_are_read_in_the_right_order(win, monkeypatch):
    monkeypatch.setattr(win, "user32", _FakeUser32(win._HighContrast, True, animations=False))
    prefs = win.WindowsSystemPrefs().read()
    assert prefs.reduce_motion is True
    colors = prefs.high_contrast
    assert (colors.window, colors.text) == ("#000000", "#FFFFFF")
    assert colors.hotlight == "#FFFF00" and colors.highlight == "#1AEBFF"
    assert colors.gray == "#3FF23F"


def test_no_high_contrast_means_none(win, monkeypatch):
    monkeypatch.setattr(win, "user32", _FakeUser32(win._HighContrast, False))
    prefs = win.WindowsSystemPrefs().read()
    assert prefs.high_contrast is None and prefs.reduce_motion is False


def test_hotkey_registers_and_lets_go(win):
    hotkey = win.WindowsHotkey()
    if not hotkey.register(lambda: None):
        pytest.skip("Ctrl+Alt+Space is in use by another app on this machine")
    try:
        assert hotkey._thread is not None and hotkey._thread.is_alive()
    finally:
        hotkey.unregister()
    assert hotkey._thread is None
    assert hotkey.register(lambda: None)  # the key was really released
    hotkey.unregister()
