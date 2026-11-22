"""The macOS row: grows right from the notch, and fits the menu bar (Manasvi, 2026-11-22:
"the location should be on the right side of the notch, but the size should fit in
that area")."""

import pytest
from PySide6.QtCore import QPoint, Qt

from taskpill.platform.base import Platform, Spot
from taskpill.services.session_store import SessionStore
from taskpill.ui import geometry as g
from taskpill.ui.controller import PillController
from taskpill.ui.pill_painter import TEXT_SCALE_FLOOR, Fonts
from taskpill.ui.pill_row import PillRow, RowOptions
from taskpill.ui.platform_driver import PlatformDriver
from taskpill.ui.theme import DARK
from taskpill.ui.view_model import PillKind, PillModel, Tooltip

TIP = Tooltip("Fix it", "Editing a.py", "Running for 1 min", "/Users/me/p")


class Clock:
    t = 100.0

    def __call__(self):
        return self.t

    def now(self):
        return self.t


def model(sid, kind=PillKind.WORKING):
    return PillModel(sid, "proj", "Editing a.py", kind, 40, TIP)


def settle(row, clock):
    clock.t += 5
    row._tick()


def mac_row(qtbot, clock, dims=g.DEFAULT):
    row = PillRow(RowOptions(anchor=g.Anchor.LEFT), DARK, clock=clock, dims=dims)
    qtbot.addWidget(row)
    row.set_anchor(QPoint(300, 40))
    row.show()
    return row


def shown_widths(row, clock):
    return [round(row._items[s].width.value(clock())) for s in row._order]


# ---- geometry ----------------------------------------------------------------------------
def test_fit_dims_leaves_windows_alone():
    assert g.fit_dims(g.DEFAULT) is g.DEFAULT


def test_fit_dims_caps_the_height_at_the_bar():
    assert g.fit_dims(g.Dims(232, 32), max_height=20).height == 20
    assert g.fit_dims(g.Dims(232, 32), max_height=33).height == 32  # the user's size fits
    assert g.fit_dims(g.Dims(232, 44), max_height=33).height == 33


def test_fit_dims_never_goes_thinner_than_the_floor():
    assert g.fit_dims(g.DEFAULT, max_height=4).height == g.BAR_MIN_HEIGHT


def test_fit_dims_caps_the_width_at_the_room():
    assert g.fit_dims(g.Dims(300, 32), room=250).width == 250
    assert g.fit_dims(g.Dims(232, 32), room=400).width == 232


def test_too_little_room_for_the_narrowest_pill_makes_a_circle():
    dims = g.fit_dims(g.Dims(232, 32), max_height=20, room=120)
    assert dims.is_circle and dims.width == 20


def test_a_circle_stays_a_circle_at_the_new_height():
    dims = g.fit_dims(g.Dims(32, 32), max_height=20)
    assert (dims.width, dims.height) == (20, 20)


def test_left_layout_keeps_the_oldest_by_the_anchor():
    xs = g.layout_row([32, 32, 32], g.Anchor.LEFT, 500)
    assert xs == [g.MARGIN, g.MARGIN + 32 + g.GAP, g.MARGIN + 2 * (32 + g.GAP)]


def test_text_never_shrinks_below_the_smallest_settable_size():
    small, smallest = Fonts(20 / g.HEIGHT), Fonts(g.MIN_HEIGHT / g.HEIGHT)
    assert small.title.pixelSize() == smallest.title.pixelSize()
    assert small.scale == pytest.approx(20 / g.HEIGHT)  # padding still follows the height
    assert Fonts(1.0).title.pixelSize() == 12  # Windows' default size is unchanged
    assert TEXT_SCALE_FLOOR == g.MIN_HEIGHT / g.HEIGHT


# ---- the row -------------------------------------------------------------------------------
def test_left_anchor_keeps_the_left_edge_still(qtbot):
    clock = Clock()
    row = mac_row(qtbot, clock)
    row.set_models([model("a")])
    settle(row, clock)
    assert row.geometry().left() + g.MARGIN == 300
    first_x = row._items["a"].x.value(clock())
    row.set_models([model("a"), model("b")])
    settle(row, clock)
    assert row.geometry().left() + g.MARGIN == 300
    assert row._items["a"].x.value(clock()) == first_x  # the first one doesn't move


def test_the_pill_fits_the_bar_height(qtbot):
    clock = Clock()
    row = mac_row(qtbot, clock)
    row.set_models([model("a")])
    row.set_bar_height(20.0)
    settle(row, clock)
    assert row._rect(row._items["a"], clock()).height() == 20
    assert row.dims == g.DEFAULT  # what the user set is kept (and saved)
    row.set_bar_height(None)
    settle(row, clock)
    assert row._rect(row._items["a"], clock()).height() == g.HEIGHT


def test_the_pill_is_never_wider_than_the_room(qtbot):
    clock = Clock()
    row = mac_row(qtbot, clock)
    row.set_models([model("a")])
    row.set_room(200.0)
    settle(row, clock)
    assert shown_widths(row, clock) == [200]
    row.set_room(100.0)
    settle(row, clock)
    assert shown_widths(row, clock) == [g.HEIGHT]  # a circle


def test_room_does_not_shrink_the_windows_pill(qtbot):
    clock = Clock()
    row = PillRow(RowOptions(), DARK, clock=clock)
    qtbot.addWidget(row)
    row.set_anchor(QPoint(700, 300))
    row.show()
    row.set_models([model("a")])
    row.set_room(100.0)
    settle(row, clock)
    assert shown_widths(row, clock) == [g.FULL_WIDTH]


def test_a_needs_you_pill_also_fits(qtbot):
    clock = Clock()
    row = mac_row(qtbot, clock)
    row.set_models([model("a", PillKind.NEEDS_YOU)])
    row.set_room(200.0)
    row.set_bar_height(20.0)
    settle(row, clock)
    rect = row._rect(row._items["a"], clock())
    assert (rect.width(), rect.height()) == (200, 20)


def test_resizing_on_a_mac_drags_the_right_edge(qtbot):
    clock = Clock()
    row = mac_row(qtbot, clock)
    row.set_models([model("a")])
    settle(row, clock)
    assert row.begin_resize("a")
    settle(row, clock)
    target = row._target_rect(clock())
    grip = row._grips(target)["width"]
    assert grip.center().x() == pytest.approx(target.right())
    start = grip.center().toPoint()
    qtbot.mousePress(row, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(row, start + QPoint(30, 0))
    qtbot.mouseRelease(row, Qt.MouseButton.LeftButton, pos=start + QPoint(30, 0))
    assert row.dims.width == g.FULL_WIDTH + 30
    assert row._global(row._target_rect(clock())).left() == row._global(target).left()


# ---- the driver ----------------------------------------------------------------------------
class MacLikePlacement:
    anchor = g.Anchor.LEFT

    def __init__(self):
        self.next = Spot(300.0, 18.5, room=250.0, max_height=33.0)

    def spot(self, screens):
        return self.next


class Nothing:
    def focus(self, chain, project):
        return False

    def is_fullscreen(self):
        return False

    def keep_on_top(self, window_id):
        return None


def mac_driver(qtbot):
    clock = Clock()
    nothing = Nothing()
    platform = Platform(MacLikePlacement(), nothing, nothing, nothing, "fake-mac")
    row = PillRow(RowOptions(anchor=g.Anchor.LEFT), DARK, clock=clock)
    qtbot.addWidget(row)
    controller = PillController(SessionStore(clock), row, clock, focus=lambda s: None)
    return clock, platform, row, PlatformDriver(platform, row, controller)


def test_the_driver_hands_the_bar_height_and_room_to_the_row(qtbot):
    _, _, row, _ = mac_driver(qtbot)
    assert row._bar_height == 33.0
    assert row._room == 250.0
    assert row.shown_dims().height == g.HEIGHT  # 32 fits in 33
    assert row.anchor() == QPoint(300, 18)


def test_dragging_the_row_away_gives_it_back_the_users_size(qtbot):
    _, platform, row, driver = mac_driver(qtbot)
    platform.placement.next = Spot(300.0, 18.5, room=150.0, max_height=20.0)
    driver.place()
    assert row.shown_dims().height == 20
    row.moved.emit(QPoint(400, 400))
    assert row._bar_height is None and row._room is None
    assert row.shown_dims() == g.DEFAULT
    driver.reset_position()  # back to the menu bar: fitted again
    assert row.shown_dims().height == 20


def test_a_restored_user_position_is_not_fitted(qtbot):
    _, _, row, driver = mac_driver(qtbot)
    driver.use_user_anchor(QPoint(500, 500))
    assert row.shown_dims() == g.DEFAULT
