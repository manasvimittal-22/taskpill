from PySide6.QtCore import QPoint

from taskpill.platform.base import Platform, Spot
from taskpill.services.session_store import SessionStore
from taskpill.ui import geometry as g
from taskpill.ui.controller import PillController
from taskpill.ui.pill_row import PillRow, RowOptions
from taskpill.ui.platform_driver import PlatformDriver
from taskpill.ui.theme import DARK
from tests.conftest import make_event


class FakePlacement:
    anchor = g.Anchor.RIGHT

    def __init__(self):
        self.next = Spot(800.0, 500.0, room=400.0)
        self.calls = 0

    def spot(self, screens):
        self.calls += 1
        return self.next


class FakeFocus:
    def __init__(self):
        self.calls = []

    def focus(self, chain, project):
        self.calls.append((tuple(chain), project))
        return True


class FakeFullscreen:
    value = False

    def is_fullscreen(self):
        return self.value


class FakeTopmost:
    def __init__(self):
        self.ids = []

    def keep_on_top(self, window_id):
        self.ids.append(window_id)


class Clock:
    t = 100.0

    def __call__(self):
        return self.t

    def now(self):
        return self.t


def setup(qtbot):
    clock = Clock()
    platform = Platform(FakePlacement(), FakeFocus(), FakeFullscreen(), FakeTopmost(), "fake")
    store = SessionStore(clock)
    row = PillRow(RowOptions(), DARK, clock=clock)
    qtbot.addWidget(row)
    focus = platform.focuser
    controller = PillController(store, row, clock,
                                focus=lambda s: focus.focus(s.pid_chain, s.project_name))
    driver = PlatformDriver(platform, row, controller)
    return clock, platform, store, row, controller, driver


def test_places_the_row_at_the_platform_spot(qtbot):
    _, _, _, row, _, _ = setup(qtbot)
    assert row.anchor() == QPoint(800, 500)
    assert row._room == 400.0


def test_follows_the_spot_when_it_moves(qtbot):
    _, platform, _, row, _, driver = setup(qtbot)
    platform.placement.next = Spot(760.0, 500.0, 360.0)
    driver.place()
    assert row.anchor() == QPoint(760, 500)


def test_a_drag_stops_automatic_placement_until_reset(qtbot):
    _, platform, _, row, _, driver = setup(qtbot)
    row.moved.emit(QPoint(300, 300))
    assert driver.user_placed
    platform.placement.next = Spot(10.0, 10.0)
    driver.place()
    assert row.anchor() == QPoint(800, 500)  # unchanged
    driver.reset_position()
    assert row.anchor() == QPoint(10, 10)


def test_no_spot_falls_back_to_a_corner(qtbot):
    _, platform, _, row, _, driver = setup(qtbot)
    platform.placement.next = None
    driver._last_spot = None
    driver.place()
    assert row.anchor() != QPoint(800, 500)


def test_a_failing_platform_never_crashes_the_app(qtbot):
    _, platform, _, row, _, driver = setup(qtbot)

    def boom(_screens):
        raise OSError("taskbar went away")

    platform.placement.spot = boom
    platform.fullscreen.is_fullscreen = lambda: (_ for _ in ()).throw(OSError("x"))
    driver.place()
    driver._check_fullscreen()


def test_fullscreen_keeps_only_needs_you_pills(qtbot):
    clock, platform, store, row, _, driver = setup(qtbot)
    store.apply(make_event("UserPromptSubmit", "a"))
    store.apply(make_event("UserPromptSubmit", "b"))
    store.apply(make_event("PermissionRequest", "b", tool_name="Bash"))
    platform.fullscreen.value = True
    driver._check_fullscreen()
    clock.t += 5
    row._tick()
    assert [sid for sid in row._order] == ["b"]
    # Bug (Manasvi, 2026-11-17): alone over the full-screen app it expanded to a
    # full pill; two sessions are running, so it stays the circle it was ...
    row.set_options(RowOptions(expand_needs_you=False))
    assert row._items["b"].width.target == g.CIRCLE_WIDTH
    # ... or, with "Open circles to show the message" on, opens to the set size.
    row.set_options(RowOptions(expand_needs_you=True))
    assert row._items["b"].width.target == g.FULL_WIDTH
    platform.fullscreen.value = False
    driver._check_fullscreen()
    assert set(row._order) == {"a", "b"}


def test_click_focuses_the_sessions_window(qtbot):
    _, platform, store, row, _, _ = setup(qtbot)
    store.apply(make_event("UserPromptSubmit", "a", cwd="C:/code/taskpill", pid_chain=[5, 4]))
    row.clicked.emit("a")
    assert platform.focuser.calls == [((5, 4), "taskpill")]


def test_topmost_only_while_visible(qtbot):
    _, platform, store, row, _, driver = setup(qtbot)
    driver._keep_on_top()
    assert platform.topmost.ids == []
    store.apply(make_event("UserPromptSubmit", "a"))
    driver._keep_on_top()
    assert platform.topmost.ids == [int(row.winId())]


def test_a_needs_you_pill_stays_at_its_size_even_with_room_to_spare(qtbot):
    clock, platform, store, row, _, driver = setup(qtbot)
    platform.placement.next = Spot(800.0, 500.0, room=280.0)
    driver.place()
    store.apply(make_event("UserPromptSubmit", "a"))
    store.apply(make_event("PermissionRequest", "a", tool_name="Bash"))
    clock.t += 5
    row._tick()
    # It used to widen into the free room; since 2026-11-17 it keeps the set size.
    assert row._items["a"].width.target == g.FULL_WIDTH


def test_needs_you_pills_can_stay_hidden_in_fullscreen_too(qtbot):
    """Manasvi, 2026-11-17: showing needs-you pills over a full-screen app is a
    setting ("Still show sessions that need you"), on by default."""
    clock, platform, store, row, controller, driver = setup(qtbot)
    store.apply(make_event("UserPromptSubmit", "b"))
    store.apply(make_event("PermissionRequest", "b", tool_name="Bash"))
    platform.fullscreen.value = True
    driver._check_fullscreen()
    assert [sid for sid in row._order] == ["b"]
    controller.set_needs_you_in_fullscreen(False)
    clock.t += 5
    row._tick()
    assert not [i for i in row._items.values() if not i.leaving]
    controller.set_needs_you_in_fullscreen(True)
    assert [sid for sid, i in row._items.items() if not i.leaving] == ["b"]


class FakeActive:
    def __init__(self):
        self.front = 1
        self.windows = {}  # project -> handle

    def foreground(self):
        return self.front

    def window_for(self, pid_chain, project):
        return self.windows.get(project)


def test_switching_to_a_done_sessions_window_clears_it(qtbot):
    """Manasvi, 2026-11-17: a Done pill clears when you switch to its window yourself."""
    clock, platform, store, row, controller, driver = setup(qtbot)
    active = FakeActive()
    active.windows = {"proj-a": 77, "proj-b": 88}
    platform.active = active
    driver._foreground = active.front
    for sid in ("a", "b"):
        store.apply(make_event("UserPromptSubmit", sid, cwd=f"C:/code/proj-{sid}",
                               pid_chain=[10, 9]))
        store.apply(make_event("Stop", sid))
    active.front = 77  # you switch to a's window
    driver._check_foreground()
    states = {s.session_id: s.state.value for s in store.visible()}
    assert states == {"b": "done"}  # a cleared, b (another window) stays


def test_done_while_you_are_already_in_its_window_still_shows(qtbot):
    clock, platform, store, row, controller, driver = setup(qtbot)
    active = FakeActive()
    active.windows = {"proj-a": 77}
    active.front = 77  # you're already in a's window
    platform.active = active
    driver._foreground = 77
    store.apply(make_event("UserPromptSubmit", "a", cwd="C:/code/proj-a", pid_chain=[10]))
    store.apply(make_event("Stop", "a"))
    driver._check_foreground()  # no switch happened
    assert [s.state.value for s in store.visible()] == ["done"]
    active.front = 5  # away...
    driver._check_foreground()
    active.front = 77  # ...and back: now it clears
    driver._check_foreground()
    assert store.visible() == []
