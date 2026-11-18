import pytest

from taskpill.platform.base import (
    FALLBACK_TRAY_WIDTH,
    GAP_TO_ARROW,
    Edge,
    Rect,
    ScreenInfo,
    TaskbarInfo,
    WindowInfo,
    choose_window,
    corner_spot,
    fallback_platform,
    looks_fullscreen,
    spot_from_taskbar,
    to_logical,
)

# Measured on Manasvi's laptop, 2026-11-17: 1920×1200 at 125% (Qt sees 1536×960).
SCREEN = ScreenInfo(Rect(0, 0, 1536, 960), 1.25)
TASKBAR = Rect(0, 1140, 1920, 1200)
ARROW = Rect(1585, 1140, 1625, 1200)
TRAY = Rect(1585, 1140, 1920, 1200)
APPS = Rect(728, 1140, 1192, 1200)


def test_spot_sits_left_of_the_arrow_centered_on_the_taskbar():
    info = TaskbarInfo(TASKBAR, Edge.BOTTOM, False, arrow=ARROW, tray=TRAY, apps=APPS)
    spot = spot_from_taskbar(info, [SCREEN])
    assert spot.x == pytest.approx((1585 - GAP_TO_ARROW) / 1.25)
    assert spot.y == pytest.approx(1170 / 1.25)
    # room up to the app icons, in logical px
    assert spot.room == pytest.approx((1585 - GAP_TO_ARROW - 1192 - GAP_TO_ARROW) / 1.25)


def test_without_ui_automation_the_tray_start_is_used():
    info = TaskbarInfo(TASKBAR, Edge.BOTTOM, False, tray=TRAY)
    spot = spot_from_taskbar(info, [SCREEN])
    assert spot.x == pytest.approx((1585 - GAP_TO_ARROW) / 1.25)
    assert spot.room is None


def test_without_tray_a_fixed_distance_from_the_end():
    info = TaskbarInfo(TASKBAR, Edge.BOTTOM, False)
    spot = spot_from_taskbar(info, [SCREEN])
    assert spot.x == pytest.approx((1920 - FALLBACK_TRAY_WIDTH) / 1.25)


def test_top_taskbar_works_too():
    info = TaskbarInfo(Rect(0, 0, 1920, 60), Edge.TOP, False, arrow=Rect(1585, 0, 1625, 60))
    spot = spot_from_taskbar(info, [SCREEN])
    assert spot.y == pytest.approx(30 / 1.25)


@pytest.mark.parametrize(
    "info",
    [
        TaskbarInfo(Rect(0, 0, 60, 1200), Edge.LEFT, False),
        TaskbarInfo(Rect(1860, 0, 1920, 1200), Edge.RIGHT, False),
        TaskbarInfo(TASKBAR, Edge.BOTTOM, True, arrow=ARROW),  # auto-hide
    ],
)
def test_vertical_or_autohide_taskbars_give_no_spot(info):
    assert spot_from_taskbar(info, [SCREEN]) is None


def test_corner_spot():
    spot = corner_spot([SCREEN])
    assert spot.x == pytest.approx(1536 - 12)
    assert corner_spot([]) is None


def test_to_logical_on_a_second_screen_with_its_own_scale():
    # primary 1920×1080 at 100%, second 2560×1440 at 150% to its right
    primary = ScreenInfo(Rect(0, 0, 1920, 1080), 1.0)
    second = ScreenInfo(Rect(1920, 0, 1920 + 1707, 960), 1.5)
    x, y, ratio = to_logical(1920 + 300, 150, [primary, second])
    assert ratio == 1.5
    assert x == pytest.approx(1920 + 200)
    assert y == pytest.approx(100)


def test_to_logical_outside_every_screen_uses_the_primary_ratio():
    assert to_logical(-500, 10, [SCREEN])[2] == 1.25


# ---- choosing the window to focus ---------------------------------------------------------
TERMINAL = 900  # WindowsTerminal.exe
CODE = 700  # Code.exe (main process)


def windows():
    return [
        WindowInfo(1, CODE, "app.py - couchwave - Visual Studio Code"),
        WindowInfo(2, CODE, "login.py - taskpill - Visual Studio Code"),
        WindowInfo(3, TERMINAL, "Windows PowerShell"),
        WindowInfo(4, 555, "Spotify"),
    ]


def test_walks_up_the_chain_to_the_first_process_with_a_window():
    # claude (100) → pwsh (200) → OpenConsole (300) → WindowsTerminal (900)
    assert choose_window(windows(), [100, 200, 300, TERMINAL], "taskpill").handle == 3


def test_prefers_the_window_whose_title_names_the_project():
    # claude (100) → extension host (650) → Code.exe main (700)
    assert choose_window(windows(), [100, 650, CODE], "taskpill").handle == 2
    assert choose_window(windows(), [100, 650, CODE], "COUCHWAVE").handle == 1


def test_without_a_title_match_the_topmost_window_of_that_process():
    assert choose_window(windows(), [100, CODE], "other-project").handle == 1


def test_no_window_in_the_chain():
    assert choose_window(windows(), [100, 200], "taskpill") is None
    assert choose_window(windows(), [], "taskpill") is None


# ---- full screen -------------------------------------------------------------------------
MONITOR = Rect(0, 0, 1920, 1200)
GAME = WindowInfo(9, 42, "", "UnityWndClass")


def test_windows_busy_state_wins():
    assert looks_fullscreen(None, None, None, busy_state=True)


def test_window_covering_the_monitor_is_fullscreen():
    assert looks_fullscreen(GAME, Rect(0, 0, 1920, 1200), MONITOR, False)


def test_maximized_window_is_not_fullscreen():
    # maximized windows stop at the taskbar (and overhang the sides by 8 px)
    assert not looks_fullscreen(GAME, Rect(-8, -8, 1928, 1148), MONITOR, False)


@pytest.mark.parametrize("cls", ["Progman", "WorkerW", "Shell_TrayWnd"])
def test_the_desktop_and_taskbar_never_count(cls):
    desktop = WindowInfo(1, 2, "", cls)
    assert not looks_fullscreen(desktop, MONITOR, MONITOR, False)


def test_nothing_in_front():
    assert not looks_fullscreen(None, None, MONITOR, False)


def test_fallback_platform_is_harmless():
    p = fallback_platform()
    assert p.placement.spot([SCREEN]) is not None
    assert p.focuser.focus([1, 2], "x") is False
    assert p.fullscreen.is_fullscreen() is False
    p.topmost.keep_on_top(123)
