"""Manasvi's round-2 UI requests (2026-11-17): done → circle, hover card above the
pill, text alignment, right-click menu, resize mode."""

import json

import pytest
from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QFontMetricsF

from taskpill.adapters.settings_store import Settings, SettingsStore
from taskpill.ui import geometry as g
from taskpill.ui.pill_painter import Fonts, baseline
from taskpill.ui.pill_row import PillRow, RowOptions
from taskpill.ui.popups import place_above
from taskpill.ui.theme import DARK
from taskpill.ui.view_model import PillKind, PillModel, Tooltip
from tests.conftest import make_event
from tests.ui.test_app import build, env  # noqa: F401 (fixture)


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def model(sid="a", kind=PillKind.WORKING):
    return PillModel(sid, "proj", "Editing a.py", kind, 40,
                     Tooltip("Fix it", "Editing a.py", "Running for 1 min", "C:/p"))


def make_row(qtbot, clock, dims=g.DEFAULT, **opts):
    row = PillRow(RowOptions(**opts), DARK, clock=clock, dims=dims)
    qtbot.addWidget(row)
    # inside the 800×600 offscreen test screen, so popups aren't pushed back on-screen
    row.set_anchor(QPoint(700, 400))
    row.show()
    return row


def settle(row, clock):
    clock.t += 5
    row._tick()


def width_of(row, sid, clock):
    return round(row._items[sid].width.value(clock()))


def hover(row, pos: QPoint) -> None:
    """Send a hover straight to the row. (QTest's simulated moves go to whatever
    window is on top at that spot, which depends on what other tests left open.)"""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(pos), QPointF(row.mapToGlobal(pos)),
                        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(row, event)


# ---- 1. done shrinks to a circle ---------------------------------------------------------
def test_a_lone_done_pill_shrinks_to_a_circle(qtbot):
    clock = Clock()
    row = make_row(qtbot, clock)
    row.set_models([model()])
    settle(row, clock)
    assert width_of(row, "a", clock) == g.FULL_WIDTH
    row.set_models([model(kind=PillKind.DONE)])
    settle(row, clock)
    assert width_of(row, "a", clock) == g.CIRCLE_WIDTH


def test_target_width_done_is_a_circle_unless_it_needs_you():
    assert g.target_width(False, False, done=True) == g.CIRCLE_WIDTH
    assert g.target_width(True, False, done=True) == g.WIDE_WIDTH


# ---- 2. hover card right above the pill ------------------------------------------------------
def test_hover_shows_the_card_centered_above_the_pill(qtbot):
    clock = Clock()
    row = make_row(qtbot, clock)
    row.set_models([model()])
    settle(row, clock)
    pill = row._rect(row._items["a"], clock())
    hover(row, pill.center().toPoint())
    card = row._card
    assert card is not None and card.isVisible()
    pill_global = row._global(pill)
    assert card.geometry().bottom() < pill_global.top()
    assert abs(card.geometry().center().x() - pill_global.center().x()) <= 1


def test_the_card_stays_put_while_moving_over_the_same_pill(qtbot):
    clock = Clock()
    row = make_row(qtbot, clock)
    row.set_models([model()])
    settle(row, clock)
    pill = row._rect(row._items["a"], clock())
    hover(row, QPoint(int(pill.left()) + 20, int(pill.center().y())))
    first = row._card.pos()
    hover(row, QPoint(int(pill.right()) - 20, int(pill.center().y())))
    assert row._card.pos() == first  # no following the cursor


def test_pressing_hides_the_card(qtbot):
    clock = Clock()
    row = make_row(qtbot, clock)
    row.set_models([model()])
    settle(row, clock)
    center = row._rect(row._items["a"], clock()).center().toPoint()
    hover(row, center)
    qtbot.mousePress(row, Qt.MouseButton.LeftButton, pos=center)
    assert not row._card.isVisible()


def test_the_card_goes_away_after_leaving_even_while_events_keep_coming(qtbot):
    """Bug (Manasvi, 2026-11-17): the card stayed after the mouse left, because
    every hook event refreshed it and that cancelled the pending hide."""
    clock = Clock()
    row = make_row(qtbot, clock)
    row.set_models([model()])
    settle(row, clock)
    hover(row, row._rect(row._items["a"], clock()).center().toPoint())
    assert row._card.isVisible()
    row.leaveEvent(None)

    def busy_session_and_hidden() -> bool:
        row.set_models([model()])  # a new hook event arrives
        return not row._card.isVisible()

    qtbot.waitUntil(busy_session_and_hidden, timeout=2000)


def test_the_card_hides_if_the_leave_event_never_comes(qtbot):
    clock = Clock()
    row = make_row(qtbot, clock)
    row.set_models([model()])
    settle(row, clock)
    pill = row._rect(row._items["a"], clock())
    hover(row, pill.center().toPoint())
    row._cursor_pos = lambda: row._global(pill).center()  # still over the pill
    row._check_hover()
    assert row._card.isVisible() and not row._card.hiding
    row._cursor_pos = lambda: QPoint(5, 5)  # left without a leave event
    row._check_hover()
    qtbot.waitUntil(lambda: not row._card.isVisible(), timeout=2000)


def test_the_folder_shows_only_when_two_sessions_share_a_name(qtbot):
    clock = Clock()
    row = make_row(qtbot, clock)
    row.set_models([model()])
    settle(row, clock)
    hover(row, row._rect(row._items["a"], clock()).center().toPoint())
    folder = row._card._lines()[3]
    assert folder.isHidden()
    row.set_models([model("a"), model("b")])  # both are called "proj"
    settle(row, clock)
    hover(row, row._rect(row._items["a"], clock()).center().toPoint())
    assert not folder.isHidden() and folder.text() == "C:/p"


def test_place_above_flips_below_at_the_top_of_the_screen(qtbot):
    from PySide6.QtCore import QSize

    pos = place_above(QSize(100, 40), QRect(500, 0, 200, 32))
    assert pos.y() > 32


# ---- 3. text alignment --------------------------------------------------------------------
def test_text_is_centered_on_its_cap_height():
    fonts = Fonts()
    fm = QFontMetricsF(fonts.title)
    y = baseline(fm, 16.0)
    cap_top = y - fm.capHeight()
    assert abs((cap_top + y) / 2 - 16.0) < 0.01


def test_fonts_scale_with_the_height():
    assert Fonts.for_height(32).title.pixelSize() == 12
    assert Fonts.for_height(42).title.pixelSize() > 12
    assert Fonts.for_height(32) is Fonts.for_height(32.1)  # cached, no new font per frame


# ---- 4. right-click menu ----------------------------------------------------------------------
def test_right_click_asks_for_the_menu_with_the_pills_screen_rect(qtbot):
    clock = Clock()
    row = make_row(qtbot, clock)
    row.set_models([model()])
    settle(row, clock)
    pill = row._rect(row._items["a"], clock())
    with qtbot.waitSignal(row.menu_requested) as blocker:
        qtbot.mousePress(row, Qt.MouseButton.RightButton, pos=pill.center().toPoint())
    sid, rect = blocker.args
    assert sid == "a"
    assert rect == row._global(pill)


def test_right_click_is_not_a_click(qtbot):
    clock = Clock()
    row = make_row(qtbot, clock)
    row.set_models([model()])
    settle(row, clock)
    clicks = []
    row.clicked.connect(clicks.append)
    qtbot.mouseClick(row, Qt.MouseButton.RightButton,
                     pos=row._rect(row._items["a"], clock()).center().toPoint())
    assert clicks == []


def test_app_menu_items(qtbot, env):  # noqa: F811
    app, _, _ = build(qtbot, env)
    app.handle_event(make_event("UserPromptSubmit", "a", cwd="C:/code/taskpill"))
    menu = app.open_pill_menu("a", QRect(800, 900, 232, 32))
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts == ["Go to taskpill", "Resize…", "Settings…", "Quit TaskPill"]

    app.handle_event(make_event("Stop", "a"))
    app.row.set_dims(g.Dims(300, 36))  # a resized pill doesn't add "Reset size" any more
    app.row.moved.emit(QPoint(400, 900))  # dragged away: "Reset position" appears
    menu = app.open_pill_menu("a", QRect(800, 900, 232, 32))
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts == ["Go to taskpill", "Clear", "Resize…", "Reset position", "Settings…",
                     "Quit TaskPill"]
    menu.close()
    next(a for a in menu.actions() if a.text() == "Reset position").trigger()
    assert app.settings.positions == {}
    menu = app.open_pill_menu("a", QRect(800, 900, 232, 32))
    assert "Reset position" not in [a.text() for a in menu.actions()]
    next(a for a in menu.actions() if a.text() == "Clear").trigger()
    assert app.store.visible() == []
    assert app.open_pill_menu("missing", QRect()) is None


# ---- 5. resize mode -----------------------------------------------------------------------------
def start_resizing(qtbot, clock, **opts):
    row = make_row(qtbot, clock, **opts)
    row.set_models([model()])
    settle(row, clock)
    assert row.begin_resize("a")
    settle(row, clock)
    return row


def drag(qtbot, row, grip: str, by: QPoint, clock):
    rect = row._grips(row._target_rect(clock()))[grip]
    start = rect.center().toPoint()
    qtbot.mousePress(row, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(row, start + by)
    qtbot.mouseRelease(row, Qt.MouseButton.LeftButton, pos=start + by)


def test_dragging_the_left_grip_makes_it_wider_with_the_right_end_still(qtbot):
    clock = Clock()
    row = start_resizing(qtbot, clock)
    right_before = row._global(row._target_rect(clock())).right()
    drag(qtbot, row, "width", QPoint(-40, 0), clock)
    assert row.dims.width == g.FULL_WIDTH + 40
    assert row._global(row._target_rect(clock())).right() == right_before


def test_dragging_the_top_grip_makes_it_taller_evenly(qtbot):
    clock = Clock()
    row = start_resizing(qtbot, clock)
    center_before = row._target_rect(clock()).center().y()
    drag(qtbot, row, "height", QPoint(0, -3), clock)
    assert row.dims.height == g.HEIGHT + 6
    assert row._target_rect(clock()).center().y() == pytest.approx(center_before)


def test_resize_is_limited(qtbot):
    clock = Clock()
    row = start_resizing(qtbot, clock)
    drag(qtbot, row, "width", QPoint(-1000, 0), clock)
    drag(qtbot, row, "height", QPoint(0, -1000), clock)
    assert row.dims == g.Dims(g.MAX_WIDTH, g.MAX_HEIGHT)
    drag(qtbot, row, "width", QPoint(1000, 0), clock)
    assert row.dims.is_circle and row.dims.width == g.MAX_HEIGHT  # all the way: a circle


def test_resize_down_to_a_circle_and_back(qtbot):
    """Manasvi, 2026-11-17: resizing can shrink the pill to a complete circle."""
    clock = Clock()
    row = start_resizing(qtbot, clock)
    # a little narrower than the minimum stays a pill at the minimum
    drag(qtbot, row, "width", QPoint(int(g.FULL_WIDTH - g.MIN_WIDTH) + 20, 0), clock)
    assert row.dims.width == g.MIN_WIDTH and not row.dims.is_circle
    # past halfway to a circle: it snaps to one, and eases there
    drag(qtbot, row, "width", QPoint(int(g.FULL_WIDTH - 90), 0), clock)
    assert row.dims == g.Dims(g.HEIGHT, g.HEIGHT) and row.dims.is_circle
    clock.t += 1
    row._tick()
    assert row._target_rect(clock()).width() == pytest.approx(g.HEIGHT)
    # the chip says so, and Done keeps it
    assert row._chip.size_label.text() == "32 × 32"


def test_a_circle_pill_shows_a_circle_for_one_session_and_widens_for_messages(qtbot):
    clock = Clock()
    row = make_row(qtbot, clock)
    row.set_dims(g.Dims(g.HEIGHT, g.HEIGHT), instant=True)
    row.set_models([model()])
    settle(row, clock)
    assert row._rect(row._items["a"], clock()).width() == pytest.approx(g.HEIGHT)
    m = model(kind=PillKind.NEEDS_YOU)
    row.set_models([m])
    settle(row, clock)
    # a circle-sized pill opens to the narrowest readable pill, no more
    assert row._rect(row._items["a"], clock()).width() == pytest.approx(g.MIN_WIDTH)


def test_a_needs_you_pill_stays_at_the_set_size(qtbot):
    """Manasvi, 2026-11-17: "when needs permission happens, leave it in the size it
    was set on". It used to widen by 88 px (and before that, to fit the message)."""
    clock = Clock()
    row = make_row(qtbot, clock, dims=g.Dims(g.MIN_WIDTH, g.HEIGHT))
    long = PillModel("a", "p", "Needs permission to run npm install --workspaces " * 3,
                     PillKind.NEEDS_YOU, 40, Tooltip("", "", "", ""))
    row.set_models([long])
    settle(row, clock)
    assert width_of(row, "a", clock) == g.MIN_WIDTH
    row.set_models([long, PillModel("b", "q", "x", PillKind.WORKING, 1, Tooltip("", "", "", ""))])
    settle(row, clock)
    assert width_of(row, "a", clock) == g.MIN_WIDTH  # opens from a circle to the set size
    assert width_of(row, "b", clock) == g.HEIGHT


def test_the_window_never_resizes_while_dragging(qtbot):
    clock = Clock()
    row = start_resizing(qtbot, clock)
    size = row.size()
    for dx in (-10, -60, -150, 40):
        drag(qtbot, row, "width", QPoint(dx, 0), clock)
        drag(qtbot, row, "height", QPoint(0, -2), clock)
        assert row.size() == size


def test_done_keeps_the_size_and_cancel_restores_it(qtbot):
    clock = Clock()
    row = start_resizing(qtbot, clock)
    drag(qtbot, row, "width", QPoint(-30, 0), clock)
    with qtbot.waitSignal(row.resize_finished) as blocker:
        row._chip.done.emit()
    assert blocker.args[0] == g.Dims(g.FULL_WIDTH + 30, g.HEIGHT)
    assert not row.resizing
    assert not row._chip.isVisible()

    row.begin_resize("a")
    drag(qtbot, row, "width", QPoint(-50, 0), clock)
    row._chip.cancel.emit()
    assert row.dims == g.Dims(g.FULL_WIDTH + 30, g.HEIGHT)


def test_reset_goes_back_to_the_default_and_stays_in_resize_mode(qtbot):
    clock = Clock()
    row = start_resizing(qtbot, clock)
    drag(qtbot, row, "width", QPoint(-30, 0), clock)
    row._chip.reset.emit()
    assert row.dims == g.Dims()
    assert row.resizing


def test_the_chip_shows_the_size_above_the_pill(qtbot):
    clock = Clock()
    row = start_resizing(qtbot, clock)
    drag(qtbot, row, "height", QPoint(0, -2), clock)
    assert row._chip.size_label.text() == "232 × 36"
    assert row._chip.geometry().bottom() < row._global(row._target_rect(clock())).top()


def test_a_done_circle_grows_to_full_size_while_resizing_then_shrinks_back(qtbot):
    clock = Clock()
    row = make_row(qtbot, clock)
    row.set_models([model(kind=PillKind.DONE)])
    settle(row, clock)
    row.begin_resize("a")
    settle(row, clock)
    assert width_of(row, "a", clock) == g.FULL_WIDTH
    row.finish_resize()
    settle(row, clock)
    assert width_of(row, "a", clock) == g.CIRCLE_WIDTH


def test_clicks_and_drags_do_nothing_else_in_resize_mode(qtbot):
    clock = Clock()
    row = start_resizing(qtbot, clock)
    clicks, menus = [], []
    row.clicked.connect(clicks.append)
    row.menu_requested.connect(lambda *a: menus.append(a))
    center = row._target_rect(clock()).center().toPoint()
    qtbot.mouseClick(row, Qt.MouseButton.LeftButton, pos=center)
    qtbot.mouseClick(row, Qt.MouseButton.RightButton, pos=center)
    assert clicks == [] and menus == []


def test_resize_ends_if_the_pill_goes_away(qtbot):
    clock = Clock()
    row = start_resizing(qtbot, clock)
    row.set_models([])
    assert not row.resizing


def test_app_saves_and_restores_the_size(qtbot, env):  # noqa: F811
    app, _, _ = build(qtbot, env)
    app.row.resize_finished.emit(g.Dims(300, 40))
    saved = SettingsStore(env["settings"]).load()
    assert (saved.pill_width, saved.pill_height) == (300, 40)
    again, _, _ = build(qtbot, env)
    assert again.row.dims == g.Dims(300, 40)
    again.reset_size()
    assert SettingsStore(env["settings"]).load().pill_width == 232


def test_size_settings_are_clamped(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"pill_width": 9999, "pill_height": 3}), encoding="utf-8")
    s = SettingsStore(path).load()
    assert (s.pill_width, s.pill_height) == (400, 26)
    path.write_text(json.dumps({"pill_width": 32, "pill_height": 32}), encoding="utf-8")
    assert SettingsStore(path).load().pill_width == 32  # a circle pill is kept
    path.write_text(json.dumps({"pill_width": "wide"}), encoding="utf-8")
    assert SettingsStore(path).load().pill_width == Settings().pill_width


def test_dims_derive_everything():
    d = g.Dims(300, 40)
    assert d.circle == 40 and d.full == 300 and d.wide == 300 + g.WIDE_EXTRA
    assert d.scale == 40 / 32
    assert g.Dims(1, 1) == g.Dims(g.MIN_HEIGHT, g.MIN_HEIGHT)  # too narrow: a circle
    assert g.Dims(1, 1).is_circle and g.Dims(1, 1).wide == g.WIDE_WIDTH
    assert g.Dims(150, 32).width == g.MIN_WIDTH  # closer to a pill than a circle
    assert g.Dims(100, 32).width == 32
    assert g.window_height() == g.MAX_HEIGHT + 2 * g.MARGIN
    assert g.morph_of(g.pill_width(0.5, dims=d), d) == pytest.approx(0.5)
    assert QPointF  # imported for type checks in drag helpers


def test_a_needs_you_circle_shows_a_question_mark(qtbot):
    """Manasvi, 2026-11-17: "when in a cirlce, and needs permission happens, instead
    of 0 % show a ?"."""
    from PySide6.QtGui import QImage, QPainter

    from taskpill.ui import pill_painter
    from taskpill.ui.pill_painter import PillLook, paint_pill

    drawn = []
    original = QPainter.drawText

    def spy(painter, *args):
        drawn.append(args[-1])
        return original(painter, *args)

    image = QImage(64, 64, QImage.Format.Format_ARGB32)
    QPainter.drawText = spy
    try:
        for kind in (PillKind.NEEDS_YOU, PillKind.WORKING):
            p = QPainter(image)
            m = PillModel("a", "p", "Needs permission", kind, 0, Tooltip("", "", "", ""))
            paint_pill(p, pill_painter.QRectF(0, 0, 32, 32), m, PillLook(morph=0), DARK)
            p.end()
    finally:
        QPainter.drawText = original
    assert drawn == ["?", "0"]
