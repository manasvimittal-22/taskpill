"""What the app needs from the OS, as small interfaces, plus the pure decisions.

Everything here is plain Python so it can be tested on any OS. The Win32
calls live in windows.py; macOS comes in Phase 5.

Coordinates: ``Rect`` is in *physical* screen pixels (what Win32 and UI
Automation report). ``Spot`` is in Qt's *logical* pixels. ``to_logical``
converts using the screen the point is on.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from taskpill.ui.geometry import Anchor

# The shortcut that jumps to the session that needs you (Manasvi, 2026-11-18). Shown in Settings.
JUMP_KEYS = ("Ctrl", "Alt", "Space")
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


@dataclass(frozen=True)
class HighContrastColors:
    """The colors of the user's Windows high-contrast theme, as #RRGGBB."""

    window: str  # background
    text: str  # normal text
    hotlight: str  # links and "active" things
    highlight: str  # selected things
    gray: str  # disabled text


@dataclass(frozen=True)
class SystemPrefs:
    reduce_motion: bool = False  # Windows: Settings → Accessibility → Visual effects → Animation
    high_contrast: HighContrastColors | None = None  # set while a high-contrast theme is on


def colorref_to_hex(colorref: int) -> str:
    """A Win32 COLORREF (0x00BBGGRR) as #RRGGBB."""
    return f"#{colorref & 0xFF:02X}{(colorref >> 8) & 0xFF:02X}{(colorref >> 16) & 0xFF:02X}"


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

    def note_prompt(self, pid_chain: Sequence[int]) -> None:
        """A prompt was just submitted in this session: the window in front is its window."""
        ...


class GlobalHotkey(Protocol):
    """One system-wide key that works from any app (Ctrl+Alt+Space, see JUMP_KEYS)."""

    def register(self, on_press: Callable[[], None]) -> bool:
        """Start listening. ``on_press`` runs on another thread. False if another app
        already owns the key (or this system can't do it)."""
        ...

    def unregister(self) -> None: ...


class SystemPrefsProbe(Protocol):
    def read(self) -> SystemPrefs:
        """The accessibility choices Windows is set to right now (cheap; polled)."""
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
    hotkey: GlobalHotkey = field(default_factory=lambda: _NoHotkey())
    prefs: SystemPrefsProbe = field(default_factory=lambda: _NoPrefs())


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


SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}
# Every process chain ends in explorer.exe, which also owns the desktop and File Explorer
# windows. A session never lives in those, so they must never be picked as a fallback.
NEVER_FOCUS_CLASSES = SHELL_CLASSES | {"CabinetWClass", "ExploreWClass"}

_TOKEN = re.compile(r"[\w.\-]+")


def _title_match(title: str, needle: str) -> int:
    """2 = the project name is a word of the title, 1 = only part of one, 0 = absent.

    "app" is a word of "login.py - app - Visual Studio Code" (2) but only part of
    "app-api - Visual Studio Code" (1), so the right window wins.
    """
    lowered = title.lower()
    if needle in _TOKEN.findall(lowered):
        return 2
    return 1 if needle in lowered else 0


def choose_window(
    windows: Iterable[WindowInfo],
    pid_chain: Sequence[int],
    project: str,
    preferred: int | None = None,
) -> WindowInfo | None:
    """The window to bring forward for a session.

    ``preferred`` is a window we saw in front when this session got its prompt
    (see ``WindowMemory``). If it is still open and still belongs to the session's
    process chain, it wins: that is what tells two terminal windows apart.

    Otherwise walk up the process chain (nearest first: claude, its shell, the
    terminal or VS Code). The first process that owns a window wins. If it owns
    several (VS Code / Windows Terminal with many windows), prefer the best title
    match for the project folder, else the topmost one (``windows`` is in z-order,
    top first). Desktop, taskbar and File Explorer windows never count.
    """
    candidates = [w for w in windows if w.class_name not in NEVER_FOCUS_CLASSES]
    chain = set(pid_chain)
    if preferred is not None:
        for w in candidates:
            if w.handle == preferred and w.pid in chain:
                return w
    needle = project.lower().strip()
    for pid in pid_chain:
        owned = [w for w in candidates if w.pid == pid]
        if not owned:
            continue
        if needle:
            best = max(owned, key=lambda w: _title_match(w.title, needle))  # first max = topmost
            if _title_match(best.title, needle) > 0:
                return best
        return owned[0]
    return None


class WindowMemory:
    """Which window each session lives in, learned when the user submits a prompt.

    Typing a prompt means the window in front *is* the session's window, even when
    Claude Code has retitled its tab so the title no longer names the project.
    Keyed by process chain (one chain = one running ``claude``). Bounded.
    """

    def __init__(self, limit: int = 64) -> None:
        self._limit = limit
        self._by_chain: dict[tuple[int, ...], int] = {}

    def remember(self, pid_chain: Sequence[int], front: WindowInfo | None) -> None:
        """Keep ``front`` for this session, but only if it belongs to the session's chain."""
        if front is None or front.class_name in NEVER_FOCUS_CLASSES:
            return
        if not pid_chain or front.pid not in pid_chain:
            return
        key = tuple(pid_chain)
        self._by_chain.pop(key, None)  # re-insert so the oldest entry is the first
        self._by_chain[key] = front.handle
        while len(self._by_chain) > self._limit:
            del self._by_chain[next(iter(self._by_chain))]

    def recall(self, pid_chain: Sequence[int]) -> int | None:
        return self._by_chain.get(tuple(pid_chain))


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

    def note_prompt(self, pid_chain: Sequence[int]) -> None:
        return None


class _NoPrefs:
    def read(self) -> SystemPrefs:
        return SystemPrefs()


class _NoHotkey:
    def register(self, on_press: Callable[[], None]) -> bool:
        return False

    def unregister(self) -> None:
        return None


class _NoTopmost:
    def keep_on_top(self, window_id: int) -> None:
        return None


def fallback_platform() -> Platform:
    return Platform(_CornerPlacement(), _NoFocus(), _NeverFullscreen(), _NoTopmost(), "fallback")
