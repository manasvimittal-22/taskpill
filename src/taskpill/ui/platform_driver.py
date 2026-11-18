"""Runs the platform checks on timers and applies them to the row.

* Placement (every 2 s): the default spot next to the taskbar's "^" arrow
  moves when tray icons come and go, or the taskbar or DPI changes. Once the
  user drags the row, their spot wins until "Reset position" (Phase 6).
* Topmost (every 0.3 s while visible): the taskbar is topmost too and jumps
  above us when clicked, so we keep re-asserting our place. The call is cheap.
* Full screen (every 1 s): while a full-screen app is in front, only
  sessions that need you are shown.
"""

from __future__ import annotations

import contextlib

from PySide6.QtCore import QObject, QPoint, QTimer
from PySide6.QtGui import QGuiApplication

from taskpill.platform.base import Platform, Rect, ScreenInfo, Spot, corner_spot
from taskpill.ui.controller import PillController
from taskpill.ui.pill_row import PillRow

PLACEMENT_MS = 2000
TOPMOST_MS = 300
FULLSCREEN_MS = 1000
FOREGROUND_MS = 500  # cheap: one Win32 call; the window list only on a change


def qt_screens() -> list[ScreenInfo]:
    """Qt's screens, primary first, in logical pixels."""
    app = QGuiApplication.instance()
    primary = app.primaryScreen() if app else None
    screens = app.screens() if app else []
    ordered = ([primary] if primary else []) + [s for s in screens if s is not primary]
    result = []
    for s in ordered:
        g = s.geometry()
        result.append(ScreenInfo(Rect(g.x(), g.y(), g.x() + g.width(), g.y() + g.height()),
                                 s.devicePixelRatio()))
    return result


class PlatformDriver(QObject):
    def __init__(self, platform: Platform, row: PillRow, controller: PillController) -> None:
        super().__init__(row)
        self._platform = platform
        self._row = row
        self._controller = controller
        self._user_placed = False
        self._hide_in_fullscreen = True
        self._last_spot: Spot | None = None

        row.moved.connect(self._on_moved)
        self._timers = [
            self._every(PLACEMENT_MS, self.place),
            self._every(TOPMOST_MS, self._keep_on_top),
            self._every(FULLSCREEN_MS, self._check_fullscreen),
            self._every(FOREGROUND_MS, self._check_foreground),
        ]
        self._foreground: int | None = platform.active.foreground()
        self.place()

    def _every(self, ms: int, slot) -> QTimer:
        timer = QTimer(self)
        timer.setInterval(ms)
        timer.timeout.connect(slot)
        timer.start()
        return timer

    @property
    def user_placed(self) -> bool:
        return self._user_placed

    def use_user_anchor(self, point: QPoint) -> None:
        """A position the user chose earlier (restored from settings)."""
        self._user_placed = True
        self._row.set_anchor(point)

    def set_hide_in_fullscreen(self, enabled: bool) -> None:
        self._hide_in_fullscreen = enabled
        self._check_fullscreen()

    def reset_position(self) -> None:
        self._user_placed = False
        self._last_spot = None
        self.place()

    def place(self) -> None:
        if self._user_placed:
            return
        screens = qt_screens()
        try:
            spot = self._platform.placement.spot(screens)
        except Exception:
            spot = None
        spot = spot or corner_spot(screens)
        if spot is None or spot == self._last_spot:
            return
        self._last_spot = spot
        self._row.set_room(spot.room)
        self._row.set_anchor(QPoint(round(spot.x), round(spot.y)))

    def _on_moved(self, _anchor: QPoint) -> None:
        self._user_placed = True

    def _keep_on_top(self) -> None:
        if self._row.isVisible():
            with contextlib.suppress(Exception):
                self._platform.topmost.keep_on_top(int(self._row.winId()))

    def _check_foreground(self) -> None:
        """When the window in front changes, clear Done pills that belong to it."""
        handle = self._platform.active.foreground()
        if handle is None or handle == self._foreground:
            return
        self._foreground = handle
        active = self._platform.active
        self._controller.window_came_forward(
            handle, lambda s: active.window_for(s.pid_chain, s.project_name))

    def _check_fullscreen(self) -> None:
        quiet = False
        if self._hide_in_fullscreen:
            try:
                quiet = self._platform.fullscreen.is_fullscreen()
            except Exception:
                quiet = False
        self._controller.set_quiet(quiet)
