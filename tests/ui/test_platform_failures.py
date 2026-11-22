"""A platform call that fails must never break the app (added 2026-11-22, because the
macOS code is written blind and its first run on a Mac may hit a wrong API name)."""

from PySide6.QtCore import QPoint

from taskpill.domain.session import SessionState
from taskpill.platform.base import Platform, Spot
from taskpill.services.session_store import SessionStore
from taskpill.ui import geometry as g
from taskpill.ui.controller import PillController
from taskpill.ui.pill_row import PillRow, RowOptions
from taskpill.ui.platform_driver import PlatformDriver
from taskpill.ui.theme import DARK
from tests.conftest import make_event


class Clock:
    t = 100.0

    def __call__(self):
        return self.t

    def now(self):
        return self.t


class Placement:
    anchor = g.Anchor.RIGHT

    def spot(self, screens):
        return Spot(700.0, 300.0)


class Broken:
    """Every call raises, like a misspelled macOS API."""

    def focus(self, chain, project):
        raise AttributeError("no such selector")

    def is_fullscreen(self):
        raise AttributeError("no such selector")

    def keep_on_top(self, window_id):
        raise AttributeError("no such selector")

    def foreground(self):
        raise AttributeError("no such selector")

    def window_for(self, chain, project):
        raise AttributeError("no such selector")

    def note_prompt(self, chain):
        raise AttributeError("no such selector")


def build(qtbot):
    clock = Clock()
    broken = Broken()
    platform = Platform(Placement(), broken, broken, broken, "broken", active=broken)
    store = SessionStore(clock)
    row = PillRow(RowOptions(), DARK, clock=clock)
    qtbot.addWidget(row)
    controller = PillController(
        store, row, clock, focus=lambda s: platform.focuser.focus(s.pid_chain, s.project_name))
    driver = PlatformDriver(platform, row, controller)  # must not raise on start
    return clock, store, row, controller, driver


def finished_session(store):
    store.apply(make_event("SessionStart", "s1", pid_chain=[300, 500]))
    store.apply(make_event("UserPromptSubmit", "s1", prompt="hi", pid_chain=[300, 500]))
    store.apply(make_event("Stop", "s1", pid_chain=[300, 500]))
    assert store.get("s1").state is SessionState.DONE


def test_the_driver_starts_when_the_foreground_call_fails(qtbot):
    _, _, row, _, driver = build(qtbot)
    assert row.anchor() == QPoint(700, 300)
    driver._check_foreground()  # and keeps going
    driver._keep_on_top()
    driver._check_fullscreen()


def test_a_click_still_clears_done_when_focus_fails(qtbot):
    _, store, _, controller, _ = build(qtbot)
    finished_session(store)
    controller.click("s1")
    assert store.get("s1") is None or store.get("s1").state is not SessionState.DONE
