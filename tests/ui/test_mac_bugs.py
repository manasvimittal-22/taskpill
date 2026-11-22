"""Bugs found on a real Mac (2026-11-22) and their fixes, so they can't come back."""

import json

from PySide6.QtCore import QPoint

from taskpill.platform import macos
from taskpill.platform.base import MenuBarInfo, Rect, ScreenInfo
from taskpill.ui import geometry as g
from taskpill.ui.pill_row import PillRow, RowOptions
from taskpill.ui.popups import ResizeChip
from taskpill.ui.theme import DARK
from taskpill.ui.view_model import PillKind, PillModel, Tooltip


class Clock:
    t = 100.0

    def __call__(self):
        return self.t


def model(sid):
    return PillModel(sid, "api", "Editing a.py", PillKind.WORKING, 40,
                     Tooltip("Fix it", "Editing a.py", "Running for 1 min", "/Users/me/api"))


def mac_row(qtbot, poll=True):
    clock = Clock()
    row = PillRow(RowOptions(anchor=g.Anchor.LEFT, poll_hover=poll), DARK, clock=clock)
    qtbot.addWidget(row)
    row.set_anchor(QPoint(200, 60))
    row.show()
    row.set_models([model("a")])
    clock.t += 5
    row._tick()
    return row, clock


# ---- hover: macOS sends no mouse moves to an inactive app, so the pointer is polled ----------
def test_hover_polling_runs_only_on_a_mac_and_only_with_pills(qtbot):
    row, _ = mac_row(qtbot)
    assert row._hover_poll.isActive()
    row.set_models([])
    assert not row._hover_poll.isActive()
    windows_row, _ = mac_row(qtbot, poll=False)
    assert not windows_row._hover_poll.isActive()


def test_the_pointer_over_a_pill_shows_the_card_and_leaving_hides_it(qtbot):
    row, clock = mac_row(qtbot)
    pill = row._global(row._rect(row._items["a"], clock()))
    row._cursor_pos = lambda: pill.center()
    row.poll_hover()
    assert row._hovered == "a"
    assert row._card is not None and row._card.session == "a"
    row._cursor_pos = lambda: QPoint(pill.right() + 200, pill.bottom() + 200)
    row.poll_hover()
    assert row._hovered is None


def test_polling_leaves_resize_mode_alone(qtbot):
    row, clock = mac_row(qtbot)
    assert row.begin_resize("a")
    pill = row._global(row._rect(row._items["a"], clock()))
    row._cursor_pos = lambda: pill.center()
    row.poll_hover()
    assert row._hovered is None


# ---- the resize chip: shown first, then measured, so it never grows over the pill -------------
def test_the_resize_chip_is_measured_after_it_is_shown(qtbot):
    chip = ResizeChip(DARK)
    qtbot.addWidget(chip)
    pill = QRect_at(300, 300, 232, 32)
    chip.show_size(232, 32, pill)
    first = chip.geometry()
    chip.show_size(232, 32, pill)  # the same call again: same place, nothing grew
    assert chip.geometry() == first
    visible_bottom = chip.geometry().bottom() - 6  # minus the shadow margin
    assert visible_bottom < pill.top() or chip.geometry().top() + 6 > pill.bottom()


def QRect_at(x, y, w, h):  # noqa: N802
    from PySide6.QtCore import QRect

    return QRect(x, y, w, h)


# ---- placement: remember the icons while an auto-hiding bar is away ---------------------------
def test_the_icons_seen_last_are_kept_while_the_bar_is_hidden(monkeypatch):
    screen = Rect(0, 0, 1512, 982)
    shown = MenuBarInfo(screen, 37.0, 849.0, (Rect(1340, 0, 1372, 37),))
    hidden = MenuBarInfo(screen, 37.0, 849.0, ())
    infos = iter([shown, hidden])
    monkeypatch.setattr(macos, "read_menu_bar", lambda: next(infos))
    placement = macos.MacPlacement()
    first = placement.spot([ScreenInfo(screen, 2.0)])
    second = placement.spot([ScreenInfo(screen, 2.0)])
    assert first == second


def test_each_new_spot_is_written_to_the_local_log(monkeypatch, tmp_path):
    screen = Rect(0, 0, 1512, 982)
    infos = iter([MenuBarInfo(screen, 37.0, 849.0), MenuBarInfo(screen, 37.0, 849.0),
                  MenuBarInfo(screen, 24.0, None)])
    monkeypatch.setattr(macos, "read_menu_bar", lambda: next(infos))
    log = macos.JsonlLog(tmp_path / "menubar-log.jsonl", limit=50, clock=lambda: 1.0)
    placement = macos.MacPlacement(log)
    for _ in range(3):
        placement.spot([ScreenInfo(screen, 2.0)])
    lines = (tmp_path / "menubar-log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # the unchanged second spot isn't repeated
    first = json.loads(lines[0])
    assert first["notch_right"] == 849.0 and first["spot"]["max_height"] == 31


def test_the_log_keeps_only_the_last_lines(tmp_path):
    log = macos.JsonlLog(tmp_path / "log.jsonl", limit=3, clock=lambda: 1.0)
    for i in range(5):
        log({"i": i})
    lines = (tmp_path / "log.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["i"] for x in lines] == [2, 3, 4]



def test_shutdown_stops_every_timer(qtbot, tmp_path):
    from PySide6.QtWidgets import QApplication

    from taskpill.adapters.hooks_installer import HookCommand, HooksInstaller
    from taskpill.adapters.settings_store import SettingsStore
    from taskpill.app import TaskPillApp
    from taskpill.platform.base import fallback_platform
    from tests.conftest import FakeClock

    app = TaskPillApp(QApplication.instance(), fallback_platform(),
                      SettingsStore(tmp_path / "s.json"),
                      HooksInstaller(tmp_path / "c.json", HookCommand("h", ())),
                      FakeClock(), quit_app=lambda: None, show_tray=False)
    qtbot.addWidget(app.row)
    app.shutdown()
    assert not any(t.isActive() for t in app._timers)
    assert not any(t.isActive() for t in app.driver._timers)


def test_a_deleted_window_ignores_option_changes(qtbot):
    import shiboken6

    row, _ = mac_row(qtbot)
    timer = row._hover_poll
    shiboken6.delete(timer)
    row.set_options(RowOptions(anchor=g.Anchor.LEFT, poll_hover=True))  # no error
