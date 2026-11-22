"""What the app needs from the OS, as small interfaces, plus the pure decisions.

Everything here is plain Python so it can be tested on any OS. The Win32
calls live in windows.py, the macOS ones in macos.py.

Coordinates: ``Rect`` is in *physical* screen pixels (what Win32 and UI
Automation report). ``Spot`` is in Qt's *logical* pixels. ``to_logical``
converts using the screen the point is on.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from taskpill.ui.geometry import Anchor


# The shortcut that jumps to the session that needs you (Manasvi, 2026-11-18). Shown in Settings.
def jump_keys_for(platform: str) -> tuple[str, ...]:
    """The same three keys, named the way each OS names them."""
    return ("Control", "Option", "Space") if platform == "darwin" else ("Ctrl", "Alt", "Space")


JUMP_KEYS = jump_keys_for(sys.platform)
GAP_TO_ARROW = 6  # physical px between the row and the "^" arrow
FALLBACK_TRAY_WIDTH = 340  # if no tray is found: this far in from the taskbar's right end
# macOS (Manasvi, 2026-11-22): in the menu bar, just right of the notch, sized to fit there.
NOTCH_GAP = 8.0  # pt between the notch and the row, and between the row and the first icon
NOTCHLESS_HALF = 92.0  # no notch: pretend one this far right of centre (half a 14" notch)
# Menu bar left above and below the pill: 8% of the bar, at least 2 pt (a 37 pt bar
# holds a 31 pt pill, a 24 pt bar a 20 pt one). Less looked cramped next to the notch.
BAR_INSET_SHARE, BAR_INSET_MIN = 0.08, 2.0
PLAIN_BAR_HEIGHT = 24.0  # a menu bar on a screen with no notch


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
    max_height: float | None = None  # macOS: the pill must fit in the menu bar


@dataclass(frozen=True)
class MenuBarInfo:
    """The macOS menu bar of the main screen, in Qt's coordinates (points, y down)."""

    screen: Rect  # the whole screen
    bar_height: float  # the menu bar's height (37 pt on a notched MacBook, 24 pt otherwise)
    notch_right: float | None = None  # x where the notch ends; None = no notch
    icons: tuple[Rect, ...] = ()  # the menu-bar icons (Wi-Fi, battery, clock, other apps)


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
    rect: Rect | None = None  # macOS fills it in (Quartz gives bounds with the list)


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


def increase_contrast_colors(dark: bool) -> HighContrastColors:
    """macOS has no high-contrast *theme*, only "Increase contrast". Use Apple's
    accessible (high-contrast) system blue and orange on pure black or white."""
    if dark:
        return HighContrastColors(window="#000000", text="#FFFFFF", hotlight="#409CFF",
                                  highlight="#FFB340", gray="#AEAEB2")
    return HighContrastColors(window="#FFFFFF", text="#000000", hotlight="#0040DD",
                              highlight="#C93400", gray="#6C6C70")


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
    circle_by_default: bool = False  # macOS: a fresh pill starts as a circle (2026-11-22)
    # Make TaskPill the active app before it shows something to click (its menu,
    # resize mode, Settings). macOS needs it (see macos.activate_self); Windows doesn't.
    activate_self: Callable[[], None] = field(default_factory=lambda: _do_nothing)


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


def spot_beside_notch(info: MenuBarInfo) -> Spot:
    """macOS: in the menu bar, just right of the notch, fitted to the bar.

    Left edge of the row (LEFT anchor) 8 pt right of the notch; with no notch,
    where a notch's right edge would be. Vertically centred on the bar. ``room``
    reaches to the first menu-bar icon on the right.

    It never leaves the menu bar (Manasvi, 2026-11-22: the pill coming down when
    the menu bar shows "shouldnt happen. this is a big problem"). With no room it
    is a circle. Only real icons count: ones that start right of the notch and
    aren't wider than a third of the screen. (When the bar slid in on a real Mac,
    something wide at the icons' level made the old rule drop the pill below it.)
    """
    s = info.screen
    edge = info.notch_right if info.notch_right is not None else (
        (s.left + s.right) / 2 + NOTCHLESS_HALF)
    left = edge + NOTCH_GAP
    max_height = round(info.bar_height - 2 * bar_inset(info.bar_height))
    room = min((r.left for r in real_icons(info, edge)), default=s.right) - NOTCH_GAP - left
    return Spot(left, s.top + info.bar_height / 2, max(room, max_height), max_height)


def real_icons(info: MenuBarInfo, edge: float) -> list[Rect]:
    """Menu-bar icons right of ``edge`` (the notch), leaving out anything far too
    wide to be an icon (the bar's own background, a whole-width strip)."""
    widest = info.screen.width / 3
    return [r for r in info.icons if r.left >= edge and 0 < r.width <= widest]


def bar_inset(bar_height: float) -> float:
    return max(BAR_INSET_MIN, bar_height * BAR_INSET_SHARE)


def screen_containing(rect: Rect, screens: Sequence[Rect]) -> Rect | None:
    """The screen holding the middle of ``rect`` (None if it's off every screen)."""
    cx, cy = (rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2
    return next((s for s in screens if s.contains(cx, cy)), None)


def guess_menu_bar(screens: Sequence[ScreenInfo]) -> MenuBarInfo | None:
    """If macOS can't be asked: the first screen, a plain 24 pt menu bar, no notch."""
    if not screens:
        return None
    return MenuBarInfo(screens[0].logical, PLAIN_BAR_HEIGHT)


def cocoa_to_qt(x: float, y: float, w: float, h: float, primary_height: float) -> Rect:
    """A Cocoa rect (origin at the bottom left of the main screen, y up) as a Qt one
    (origin at its top left, y down). Both are in points."""
    top = primary_height - (y + h)
    return Rect(round(x), round(top), round(x + w), round(top + h))


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
    *,
    preferred_as_last_resort: bool = False,
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

    ``preferred_as_last_resort`` (macOS): when no process in the chain owns a
    window, use ``preferred`` even though it isn't in the chain. iTerm2 and tmux
    run the shell under a server process that isn't a child of the app, so the
    chain never reaches a window; the window in front at the prompt is the answer.
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
    if preferred_as_last_resort and preferred is not None:
        return next((w for w in candidates if w.handle == preferred), None)
    return None


class WindowMemory:
    """Which window each session lives in, learned when the user submits a prompt.

    Typing a prompt means the window in front *is* the session's window, even when
    Claude Code has retitled its tab so the title no longer names the project.
    Keyed by process chain (one chain = one running ``claude``). Bounded.
    """

    def __init__(self, limit: int = 64, *, strict: bool = True) -> None:
        self._limit = limit
        # strict (Windows): only a window of the session's own processes. macOS keeps
        # any window, for chains that never reach the app (see choose_window).
        self._strict = strict
        self._by_chain: dict[tuple[int, ...], int] = {}

    def remember(self, pid_chain: Sequence[int], front: WindowInfo | None) -> None:
        """Keep ``front`` for this session (when strict, only if it belongs to the chain)."""
        if front is None or front.class_name in NEVER_FOCUS_CLASSES or not pid_chain:
            return
        if self._strict and front.pid not in pid_chain:
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


def _do_nothing() -> None:
    return None


def fallback_platform() -> Platform:
    return Platform(_CornerPlacement(), _NoFocus(), _NeverFullscreen(), _NoTopmost(), "fallback")
