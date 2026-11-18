"""What the app needs from the OS, as small interfaces, plus the pure decisions.

Everything here is plain Python so it can be tested on any OS. The Win32
calls live in windows.py; macOS comes in Phase 5.

Coordinates: ``Rect`` is in *physical* screen pixels (what Win32 and UI
Automation report). ``Spot`` is in Qt's *logical* pixels. ``to_logical``
converts using the screen the point is on.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from taskpill.ui.geometry import Anchor

GAP_TO_ARROW = 6  # physical px between the row and the "^" arrow
FALLBACK_TRAY_WIDTH = 340  # if no tray is found: this far in from the taskbar's right end


# ---- data -------------------------------------------------------------------------------
@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2

    def contains(self, x: float, y: float) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom


class Edge(Enum):
    BOTTOM = "bottom"
    TOP = "top"
    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True)
class TaskbarInfo:
    rect: Rect
    edge: Edge
    autohide: bool
    arrow: Rect | None = None  # the "^" show-hidden-icons button
    tray: Rect | None = None  # the notification area (TrayNotifyWnd)
    apps: Rect | None = None  # the pinned/running app buttons


@dataclass(frozen=True)
class Spot:
    """Where the row goes, in logical pixels."""

    x: float  # the row's right edge (RIGHT anchor) or center (CENTER anchor)
    y: float  # vertical center of the row
    room: float | None = None  # free width before something else (app icons), if known


@dataclass(frozen=True)
class ScreenInfo:
    """A screen as Qt sees it: logical geometry + device pixel ratio."""

    logical: Rect
    ratio: float


@dataclass(frozen=True)
class WindowInfo:
    handle: int
    pid: int
    title: str
    class_name: str = ""
    minimized: bool = False


# ---- interfaces ---------------------------------------------------------------------------
class Placement(Protocol):
    anchor: Anchor

    def spot(self, screens: Sequence[ScreenInfo]) -> Spot | None:
        """Default place for the row, or None if it can't be worked out right now."""
        ...


class Focuser(Protocol):
    def focus(self, pid_chain: Sequence[int], project: str) -> bool:
        """Bring the window that runs this session to the front."""
        ...


class FullscreenProbe(Protocol):
    def is_fullscreen(self) -> bool: ...


class ActiveWindow(Protocol):
    """Which window is in front, and which window belongs to a session. Used to
    clear a Done pill when you switch to its window yourself (Manasvi, 2026-11-17)."""

    def foreground(self) -> int | None:
        """Handle of the window in front (None if unknown)."""
        ...

    def window_for(self, pid_chain: Sequence[int], project: str) -> int | None:
        """Handle of the session's window: the one a click on its pill would focus."""
        ...


class TopmostKeeper(Protocol):
    def keep_on_top(self, window_id: int) -> None:
        """Make sure our window is above the taskbar (called often; must be cheap)."""
        ...


@dataclass
class Platform:
    placement: Placement
    focuser: Focuser
    fullscreen: FullscreenProbe
    topmost: TopmostKeeper
    name: str
    active: ActiveWindow = field(default_factory=lambda: _NoActiveWindow())


# ---- pure decisions -----------------------------------------------------------------------
def spot_from_taskbar(info: TaskbarInfo, screens: Sequence[ScreenInfo]) -> Spot | None:
    """Right next to the "^" arrow, vertically centered on the taskbar.

    Falls back to the start of the tray, then to a fixed distance from the
    taskbar's end. Vertical or auto-hiding taskbars get None (the caller then
    uses a corner of the screen).
    """
    if info.edge not in (Edge.BOTTOM, Edge.TOP) or info.autohide:
        return None
    if info.arrow is not None:
        right = info.arrow.left - GAP_TO_ARROW
    elif info.tray is not None:
        right = info.tray.left - GAP_TO_ARROW
    else:
        right = info.rect.right - FALLBACK_TRAY_WIDTH
    y = info.rect.center_y

    room_physical = None
    if info.apps is not None and info.apps.right < right:
        room_physical = right - info.apps.right - GAP_TO_ARROW

    lx, ly, ratio = to_logical(right, y, screens)
    room = room_physical / ratio if room_physical is not None else None
    return Spot(lx, ly, room)


def corner_spot(screens: Sequence[ScreenInfo], margin: float = 12.0) -> Spot | None:
    """Fallback: bottom-right corner of the primary (first) screen, in logical px."""
    if not screens:
        return None
    s = screens[0].logical
    return Spot(s.right - margin, s.bottom - margin - 26, None)


def to_logical(x: float, y: float, screens: Sequence[ScreenInfo]) -> tuple[float, float, float]:
    """Physical → logical pixels, Qt style: each screen keeps its top-left where it is,
    and everything inside it is divided by that screen's ratio.

    Returns (x, y, ratio used).
    """
    for s in screens:
        phys_w = s.logical.width * s.ratio
        phys_h = s.logical.height * s.ratio
        left, top = s.logical.left, s.logical.top
        if left <= x < left + phys_w and top <= y < top + phys_h:
            return (left + (x - left) / s.ratio, top + (y - top) / s.ratio, s.ratio)
    ratio = screens[0].ratio if screens else 1.0
    return (x / ratio, y / ratio, ratio)


def choose_window(
    windows: Iterable[WindowInfo], pid_chain: Sequence[int], project: str
) -> WindowInfo | None:
    """The window to bring forward for a session.

    Walk up the session's process chain (nearest first: claude, its shell, the
    terminal or VS Code). The first process that owns a window wins. If it owns
    several (VS Code / Windows Terminal with many windows), prefer the one whose
    title mentions the project folder, else the topmost one (``windows`` is in
    z-order, top first).
    """
    windows = list(windows)
    needle = project.lower().strip()
    for pid in pid_chain:
        owned = [w for w in windows if w.pid == pid]
        if not owned:
            continue
        if needle:
            for w in owned:
                if needle in w.title.lower():
                    return w
        return owned[0]
    return None


SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}


def looks_fullscreen(foreground: WindowInfo | None, window_rect: Rect | None,
                     monitor_rect: Rect | None, busy_state: bool) -> bool:
    """True while a game, video or presentation fills the screen.

    ``busy_state`` is Windows' own answer (SHQueryUserNotificationState says
    "busy", "D3D full screen" or "presentation"). We also check whether the
    foreground window covers its whole monitor, because borderless full-screen
    apps (most video players, browsers in F11) don't always set that state.
    The desktop and the taskbar never count.
    """
    if busy_state:
        return True
    if foreground is None or window_rect is None or monitor_rect is None:
        return False
    if foreground.class_name in SHELL_CLASSES:
        return False
    return (
        window_rect.left <= monitor_rect.left
        and window_rect.top <= monitor_rect.top
        and window_rect.right >= monitor_rect.right
        and window_rect.bottom >= monitor_rect.bottom
    )


# ---- fallback (no OS integration) -----------------------------------------------------------
class _CornerPlacement:
    anchor = Anchor.RIGHT

    def spot(self, screens: Sequence[ScreenInfo]) -> Spot | None:
        return corner_spot(screens)


class _NoFocus:
    def focus(self, pid_chain: Sequence[int], project: str) -> bool:
        return False


class _NeverFullscreen:
    def is_fullscreen(self) -> bool:
        return False


class _NoActiveWindow:
    def foreground(self) -> int | None:
        return None

    def window_for(self, pid_chain: Sequence[int], project: str) -> int | None:
        return None


class _NoTopmost:
    def keep_on_top(self, window_id: int) -> None:
        return None


def fallback_platform() -> Platform:
    return Platform(_CornerPlacement(), _NoFocus(), _NeverFullscreen(), _NoTopmost(), "fallback")
