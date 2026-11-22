"""macOS placement rules (pure): in the menu bar, right of the notch, fitted to it."""

import pytest

from taskpill.platform.base import (
    NOTCH_GAP,
    NOTCHLESS_HALF,
    PLAIN_BAR_HEIGHT,
    MenuBarInfo,
    Rect,
    ScreenInfo,
    cocoa_to_qt,
    guess_menu_bar,
    spot_beside_notch,
)
from taskpill.ui.geometry import MAX_HEIGHT

# A 14" MacBook Pro at its default "looks like" size: 1512 × 982 pt, a 37 pt menu bar,
# the notch from x = 663 to 849 (186 pt wide, centred).
MBP = Rect(0, 0, 1512, 982)
NOTCH_RIGHT = 849.0
CLOCK = Rect(1380, 0, 1505, 37)
WIFI = Rect(1340, 0, 1372, 37)


def test_the_row_starts_just_right_of_the_notch_centred_on_the_bar():
    spot = spot_beside_notch(MenuBarInfo(MBP, 37.0, NOTCH_RIGHT, (CLOCK, WIFI)))
    assert spot.x == NOTCH_RIGHT + NOTCH_GAP
    assert spot.y == pytest.approx(18.5)
    assert spot.max_height == 31  # 3 pt above and below


def test_room_reaches_to_the_first_menu_bar_icon():
    spot = spot_beside_notch(MenuBarInfo(MBP, 37.0, NOTCH_RIGHT, (CLOCK, WIFI)))
    assert spot.room == WIFI.left - NOTCH_GAP - (NOTCH_RIGHT + NOTCH_GAP)


def test_no_icons_means_room_up_to_the_screen_edge():
    spot = spot_beside_notch(MenuBarInfo(MBP, 37.0, NOTCH_RIGHT))
    assert spot.room == MBP.right - NOTCH_GAP - (NOTCH_RIGHT + NOTCH_GAP)


def test_icons_left_of_the_row_are_not_in_the_way():
    # An icon whose right end is left of the row (e.g. on the far side of the notch)
    left_icon = Rect(600, 0, 640, 37)
    spot = spot_beside_notch(MenuBarInfo(MBP, 37.0, NOTCH_RIGHT, (left_icon, CLOCK)))
    assert spot.room == CLOCK.left - NOTCH_GAP - (NOTCH_RIGHT + NOTCH_GAP)


def test_an_icon_straddling_the_start_leaves_no_room_so_the_row_drops_under_the_bar():
    straddling = Rect(850, 0, 900, 37)
    spot = spot_beside_notch(MenuBarInfo(MBP, 37.0, NOTCH_RIGHT, (straddling,)))
    assert spot.x == NOTCH_RIGHT + NOTCH_GAP  # same x, so it still reads as "by the notch"
    assert spot.y == 37.0 + NOTCH_GAP + MAX_HEIGHT / 2
    assert spot.room is None and spot.max_height is None


def test_a_crowded_bar_too_narrow_for_a_circle_drops_under_the_bar():
    # 20 pt free: a 31 pt circle doesn't fit
    icon = Rect(round(NOTCH_RIGHT + NOTCH_GAP + 20 + NOTCH_GAP), 0, 1500, 37)
    spot = spot_beside_notch(MenuBarInfo(MBP, 37.0, NOTCH_RIGHT, (icon,)))
    assert spot.max_height is None


def test_just_room_for_a_circle_stays_in_the_bar():
    left = NOTCH_RIGHT + NOTCH_GAP
    icon = Rect(round(left + 31 + NOTCH_GAP), 0, 1500, 37)
    spot = spot_beside_notch(MenuBarInfo(MBP, 37.0, NOTCH_RIGHT, (icon,)))
    assert spot.room == 31
    assert spot.max_height == 31


def test_without_a_notch_it_sits_where_the_notch_would_end():
    # A 27" monitor at 2560 × 1440 pt with a 24 pt menu bar (Manasvi's pick, 2026-11-22)
    screen = Rect(0, 0, 2560, 1440)
    spot = spot_beside_notch(MenuBarInfo(screen, 24.0))
    assert spot.x == 1280 + NOTCHLESS_HALF + NOTCH_GAP
    assert spot.y == 12.0
    assert spot.max_height == 20.0


def test_a_screen_that_does_not_start_at_zero():
    screen = Rect(-1920, -200, 0, 880)
    spot = spot_beside_notch(MenuBarInfo(screen, 24.0))
    assert spot.x == -960 + NOTCHLESS_HALF + NOTCH_GAP
    assert spot.y == -200 + 12.0


def test_cocoa_rects_flip_to_qt():
    # A 37 pt bar at the top of a 982 pt screen: Cocoa y = 945
    assert cocoa_to_qt(0, 945, 1512, 37, 982) == Rect(0, 0, 1512, 37)
    # A second screen above the main one (Cocoa y beyond the main screen's height)
    assert cocoa_to_qt(0, 982, 1920, 1080, 982) == Rect(0, -1080, 1920, 0)


def test_the_guess_uses_the_first_screen_and_a_plain_bar():
    screens = [ScreenInfo(Rect(0, 0, 1440, 900), 2.0), ScreenInfo(Rect(1440, 0, 3360, 1080), 1.0)]
    info = guess_menu_bar(screens)
    assert info == MenuBarInfo(Rect(0, 0, 1440, 900), PLAIN_BAR_HEIGHT)
    assert guess_menu_bar([]) is None
