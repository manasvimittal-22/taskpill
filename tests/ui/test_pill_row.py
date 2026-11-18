"""Widget tests on Qt's offscreen platform (see tests/ui/conftest.py)."""

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QImage

from taskpill.domain.session import Session
from taskpill.services.session_store import SessionStore
from taskpill.ui import geometry as g
from taskpill.ui.controller import PillController
from taskpill.ui.pill_row import PillRow, RowOptions, tooltip_html
from taskpill.ui.theme import DARK
from taskpill.ui.view_model import PillKind, PillModel, Tooltip
from tests.conftest import make_event


class StepClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def now(self):
        return self.t


def model(sid, kind=PillKind.WORKING, percent=40, detail="Editing a.py"):
    return PillModel(sid, "proj", detail, kind, percent, Tooltip("Fix it", "Editing a.py",
                                                                "Running for 1 min", "C:/p"))


def settle(row, clock):
    clock.t += 5
    row._tick()


def make_row(qtbot, clock, **opts):
    row = PillRow(RowOptions(**opts), DARK, clock=clock)
    qtbot.addWidget(row)
    row.set_anchor(QPoint(1000, 500))
    row.show()
    return row


def widths(row, clock):
    return [round(row._items[s].width.value(clock())) for s in row._order]


def test_one_session_is_a_full_pill(qtbot):
    clock = StepClock()
    row = make_row(qtbot, clock)
    row.set_models([model("a")])
    settle(row, clock)
    assert widths(row, clock) == [g.FULL_WIDTH]
    assert row.width() == g.window_width([g.FULL_WIDTH])


def test_two_sessions_collapse_into_circles(qtbot):
    clock = StepClock()
    row = make_row(qtbot, clock)
    row.set_models([model("a")])
    settle(row, clock)
    row.set_models([model("a"), model("b")])
    settle(row, clock)
    assert widths(row, clock) == [g.CIRCLE_WIDTH, g.CIRCLE_WIDTH]


def test_a_needs_you_circle_widens(qtbot):
    clock = StepClock()
    row = make_row(qtbot, clock)
    row.set_models([model("a"), model("b", PillKind.NEEDS_YOU)])
    settle(row, clock)
    # opens to the pill's set size, never wider (Manasvi, 2026-11-17)
    assert widths(row, clock) == [g.CIRCLE_WIDTH, g.FULL_WIDTH]


def test_expand_setting_off_keeps_the_circle(qtbot):
    clock = StepClock()
    row = make_row(qtbot, clock, expand_needs_you=False)
    row.set_models([model("a"), model("b", PillKind.NEEDS_YOU)])
    settle(row, clock)
    assert widths(row, clock) == [g.CIRCLE_WIDTH, g.CIRCLE_WIDTH]


def test_right_anchor_keeps_the_right_edge_still(qtbot):
    clock = StepClock()
    row = make_row(qtbot, clock)
    row.set_models([model("a")])
    settle(row, clock)
    assert row.geometry().right() + 1 == 1000
    row.set_models([model("a"), model("b")])
    settle(row, clock)
    assert row.geometry().right() + 1 == 1000


def test_window_never_resizes_mid_animation(qtbot):
    clock = StepClock()
    row = make_row(qtbot, clock)
    row.set_models([model("a"), model("b")])
    settle(row, clock)
    row.set_models([model("a")])  # b leaves, a grows back to a full pill
    size_at_start = row.width()
    for _ in range(10):
        clock.t += 0.02
        row._tick()
        if row._frame.isActive():
            assert row.width() == size_at_start
    settle(row, clock)
    assert row.width() == g.window_width([g.FULL_WIDTH])


def test_leaving_pills_fade_out_and_are_removed(qtbot):
    clock = StepClock()
    row = make_row(qtbot, clock)
    row.set_models([model("a"), model("b")])
    settle(row, clock)
    row.set_models([model("a")])
    assert row._items["b"].leaving
    settle(row, clock)
    assert "b" not in row._items
    row.set_models([])
    assert not row.has_pills()


def test_a_pill_that_comes_back_while_fading_is_kept(qtbot):
    clock = StepClock()
    row = make_row(qtbot, clock)
    row.set_models([model("a")])
    settle(row, clock)
    row.set_models([])
    row.set_models([model("a")])
    settle(row, clock)
    assert row.has_pills()
    assert "a" in row._items


def test_click_emits_the_session_id_and_drag_does_not(qtbot):
    clock = StepClock()
    row = make_row(qtbot, clock)
    row.set_models([model("a")])
    settle(row, clock)
    center = row._rect(row._items["a"], clock()).center().toPoint()
    with qtbot.waitSignal(row.clicked) as blocker:
        qtbot.mouseClick(row, Qt.MouseButton.LeftButton, pos=center)
    assert blocker.args == ["a"]

    clicks = []
    row.clicked.connect(clicks.append)
    with qtbot.waitSignal(row.moved):
        qtbot.mousePress(row, Qt.MouseButton.LeftButton, pos=center)
        qtbot.mouseMove(row, center + QPoint(30, 0))
        qtbot.mouseMove(row, center + QPoint(60, 0))
        qtbot.mouseRelease(row, Qt.MouseButton.LeftButton, pos=center + QPoint(60, 0))
    assert clicks == []


def test_clicks_outside_pills_do_nothing(qtbot):
    clock = StepClock()
    row = make_row(qtbot, clock)
    row.set_models([model("a")])
    settle(row, clock)
    assert row._item_at(QPointF(1, 1)) is None


def test_paints_something_for_every_state(qtbot):
    clock = StepClock()
    row = make_row(qtbot, clock)
    for kind in PillKind:
        row.set_models([model("a", kind)])
        settle(row, clock)
        image: QImage = row.grab().toImage()
        center = image.pixelColor(image.width() - int(g.MARGIN) - 20, image.height() // 2)
        assert center.alpha() > 0  # the pill is drawn
        corner = image.pixelColor(0, 0)
        assert corner.alpha() == 0  # outside the pill stays see-through (clicks pass through)


def test_tooltip_is_escaped():
    m = PillModel("a", "p", "d", PillKind.WORKING, 1,
                  Tooltip("<script>x</script>", "Editing a.py", "Running for 1 min", "C:/p"))
    html = tooltip_html(m)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_controller_shows_hides_and_acknowledges(qtbot):
    clock = StepClock()
    store = SessionStore(clock)
    row = PillRow(RowOptions(), DARK, clock=clock)
    qtbot.addWidget(row)
    focused: list[Session] = []
    PillController(store, row, clock, focus=focused.append)

    store.apply(make_event("UserPromptSubmit", "a"))
    assert row.isVisible()
    store.apply(make_event("Stop", "a"))
    row.clicked.emit("a")
    assert [s.session_id for s in focused] == ["a"]
    assert store.visible() == []  # Done was acknowledged
    settle(row, clock)
    qtbot.waitUntil(lambda: not row.isVisible(), timeout=2000)
