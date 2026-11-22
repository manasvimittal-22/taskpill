"""macOS: AppKit and Quartz through PyObjC. Imported only on a Mac (see __init__.py).

This file is written on Windows and never runs there (Manasvi chose fake tests
only, 2026-11-22). So every decision lives in base.py, where it is tested; this
file only reads values from the OS and hands them over. Each OS call sits in a
small function, so a wrong name breaks one feature, never the whole app, and the
borrowed-Mac test rounds can point at the exact call.

Coordinates: Cocoa puts (0, 0) at the bottom left of the main screen with y going
up; Qt and Quartz window lists put it at the top left with y going down. Both use
points, which are Qt's logical pixels on a Mac.
"""

from __future__ import annotations

import contextlib
import ctypes
import dataclasses
import os
import platform as _platform
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence

from taskpill.platform.base import (
    MenuBarInfo,
    Platform,
    Rect,
    ScreenInfo,
    Spot,
    SystemPrefs,
    WindowInfo,
    WindowMemory,
    choose_window,
    cocoa_to_qt,
    fallback_platform,
    guess_menu_bar,
    increase_contrast_colors,
    looks_fullscreen,
    screen_containing,
    spot_beside_notch,
)
from taskpill.ui.geometry import Anchor

STATUS_ITEM_LAYER = 25  # kCGStatusWindowLevel: the menu-bar icons' windows
PILL_LEVEL = 25  # NSStatusWindowLevel: above the menu bar (24), like the icons
# NSWindowCollectionBehavior: on every Space, also next to full-screen apps,
# and not moved by Mission Control or picked by Cmd+`.
CAN_JOIN_ALL_SPACES = 1 << 0
STATIONARY = 1 << 4
IGNORES_CYCLE = 1 << 6
FULL_SCREEN_AUXILIARY = 1 << 8
PILL_BEHAVIOR = CAN_JOIN_ALL_SPACES | STATIONARY | IGNORES_CYCLE | FULL_SCREEN_AUXILIARY
ACCESSORY = 1  # NSApplicationActivationPolicyAccessory: no Dock icon, no app menu
ACTIVATE_IGNORING_OTHER_APPS = 1 << 1  # NSApplicationActivateIgnoringOtherApps
# A real app window: on the normal layer, visible, and not a 1-pixel helper.
NORMAL_LAYER, MIN_WINDOW_SIDE = 0, 40


# ---- reading the menu bar ------------------------------------------------------------------
def read_menu_bar() -> MenuBarInfo | None:
    from AppKit import NSScreen

    screens = NSScreen.screens()
    if not screens:
        return None
    main = screens[0]  # AppKit: the first screen is always the one with the menu bar
    frame = main.frame()
    screen = cocoa_to_qt(frame.origin.x, frame.origin.y, frame.size.width,
                         frame.size.height, frame.size.height)
    bar = _bar_height(main)
    return MenuBarInfo(screen, bar, _notch_right(main), tuple(_menu_bar_icons(screen, bar)))


def _bar_height(screen) -> float:
    """The menu bar's height: the notch's safe area (MacBooks with a notch), the
    space the bar takes from the screen, or the status bar's own thickness."""
    from AppKit import NSStatusBar

    frame, visible = screen.frame(), screen.visibleFrame()
    reserved = (frame.origin.y + frame.size.height) - (visible.origin.y + visible.size.height)
    notch = 0.0
    with contextlib.suppress(AttributeError):  # safeAreaInsets: macOS 12+
        notch = float(screen.safeAreaInsets().top)
    thickness = float(NSStatusBar.systemStatusBar().thickness())
    return max(notch, float(reserved), thickness)


def _notch_right(screen) -> float | None:
    """x where the notch ends, or None (no notch, or macOS before 12)."""
    try:
        area = screen.auxiliaryTopRightArea()
    except AttributeError:
        return None
    if area is None or area.size.width <= 0:
        return None
    frame = screen.frame()
    x = float(area.origin.x)
    if not frame.origin.x <= x <= frame.origin.x + frame.size.width:
        x += float(frame.origin.x)  # given relative to the screen
    return x


def _menu_bar_icons(screen: Rect, bar_height: float) -> list[Rect]:
    """Where the menu-bar icons are (Wi-Fi, battery, clock, other apps' icons).

    Quartz lists every window with its bounds (top-left origin, like Qt). Bounds
    don't need the Screen Recording permission; only window titles do.
    Our own pill window is taller than the bar, so the height check skips it.
    """
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGNullWindowID,
        kCGWindowBounds,
        kCGWindowLayer,
        kCGWindowListOptionOnScreenOnly,
    )

    icons = []
    for info in CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID) or ():
        if info.get(kCGWindowLayer) != STATUS_ITEM_LAYER:
            continue
        b = info.get(kCGWindowBounds) or {}
        x, y = float(b.get("X", 0)), float(b.get("Y", 0))
        w, h = float(b.get("Width", 0)), float(b.get("Height", 0))
        on_this_bar = screen.left <= x < screen.right and screen.top <= y < screen.top + bar_height
        if w > 0 and 0 < h <= bar_height + 1 and on_this_bar:
            icons.append(Rect(round(x), round(y), round(x + w), round(y + h)))
    return icons


class MacPlacement:
    """Where the row goes. With "Automatically hide and show the menu bar", macOS
    reports no icons while the bar is away, so the last icons seen are kept: the
    pill then keeps one size whether the bar is showing or not."""

    anchor = Anchor.LEFT

    def __init__(self, log: Callable[[dict], None] | None = None) -> None:
        self._icons: tuple[Rect, ...] = ()
        self._log = log
        self._last: Spot | None = None

    def spot(self, screens: Sequence[ScreenInfo]) -> Spot | None:
        try:
            info = read_menu_bar()
        except Exception:
            info = None  # a wrong guess about an API must not lose the pill
        info = info or guess_menu_bar(screens)
        if info is None:
            return None
        if info.icons:
            self._icons = info.icons
        elif self._icons:
            info = dataclasses.replace(info, icons=self._icons)
        spot = spot_beside_notch(info)
        if spot != self._last and self._log is not None:
            with contextlib.suppress(Exception):
                self._log(placement_record(info, spot))
        self._last = spot
        return spot


def placement_record(info: MenuBarInfo, spot: Spot) -> dict:
    """One line for menubar-log.jsonl: what the menu bar looked like and where the
    pill went. Only sizes and positions, nothing about what's on screen."""
    def box(r: Rect) -> list[int]:
        return [r.left, r.top, r.right, r.bottom]

    return {"screen": box(info.screen), "bar": info.bar_height, "notch_right": info.notch_right,
            "icons": [box(r) for r in info.icons],
            "spot": {"x": spot.x, "y": spot.y, "room": spot.room, "max_height": spot.max_height}}


class JsonlLog:
    """Keeps the last ``limit`` lines in a small local file (for bug reports from a
    Mac; nothing is sent anywhere)."""

    def __init__(self, path, limit: int = 50, clock=None) -> None:
        import time

        self._path = path
        self._limit = limit
        self._clock = clock or time.time

    def __call__(self, record: dict) -> None:
        import json

        line = json.dumps({"t": round(self._clock()), **record})
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        lines = [*lines, line][-self._limit:]
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---- the pill's window: above the menu bar, on every Space ------------------------------------
def ns_window(window_id: int):
    """The NSWindow behind a Qt window. Qt's winId() on a Mac is its NSView, but only
    on Qt's real Mac display ("cocoa"): anywhere else it's just a number, and treating
    it as a pointer crashes the process. Callers check ``qt_is_cocoa`` first."""
    import objc

    view = objc.objc_object(c_void_p=ctypes.c_void_p(window_id))
    return view.window()


def qt_is_cocoa() -> bool:
    from PySide6.QtGui import QGuiApplication

    return QGuiApplication.platformName() == "cocoa"


class MacTopmost:
    def __init__(self, is_cocoa: Callable[[], bool] = qt_is_cocoa) -> None:
        self._is_cocoa = is_cocoa

    def keep_on_top(self, window_id: int) -> None:
        # Found on GitHub's Mac, 2026-11-22: under Qt's offscreen test display a
        # winId isn't an NSView, and ns_window() crashed Python (segfault).
        if not window_id or not self._is_cocoa():
            return
        window = ns_window(window_id)
        if window is None:
            return
        if window.level() != PILL_LEVEL:
            window.setLevel_(PILL_LEVEL)
        if window.collectionBehavior() != PILL_BEHAVIOR:
            window.setCollectionBehavior_(PILL_BEHAVIOR)
        # Qt makes "tool" windows hide when their app isn't the active one. TaskPill
        # is almost never the active app, so that would hide the pill all the time.
        if window.hidesOnDeactivate():
            window.setHidesOnDeactivate_(False)


def activate_self() -> None:
    """Make TaskPill the active app. On a real Mac (2026-11-22) a click on the
    right-click menu did nothing: TaskPill is never the active app, the click made
    macOS activate it first, and Qt closed the menu during that switch. Menu-bar
    apps activate themselves before opening a menu; so does TaskPill."""
    from AppKit import NSApplication

    app = NSApplication.sharedApplication()
    if hasattr(app, "activate"):  # macOS 14+
        app.activate()
    else:
        app.activateIgnoringOtherApps_(True)


def become_agent_app() -> None:
    """No Dock icon and no app menu: TaskPill lives in the menu bar only.
    (The packaged app also says so in its Info.plist, LSUIElement.)"""
    from AppKit import NSApplication

    NSApplication.sharedApplication().setActivationPolicy_(ACCESSORY)


# ---- windows: which one is a session's, which one is in front ---------------------------------
def windows_from_quartz(infos: Iterable[Mapping], own_pid: int) -> list[WindowInfo]:
    """App windows from a Quartz window list (front to back), as WindowInfo.

    Titles stay empty: reading them needs the Screen Recording permission, which
    TaskPill doesn't ask for. The window number is the handle.
    """
    windows = []
    for info in infos:
        b = info.get("kCGWindowBounds") or {}
        if (info.get("kCGWindowLayer") != NORMAL_LAYER
                or info.get("kCGWindowOwnerPID") in (None, own_pid)
                or float(info.get("kCGWindowAlpha", 1.0)) <= 0
                or min(float(b.get("Width", 0)), float(b.get("Height", 0))) < MIN_WINDOW_SIDE):
            continue
        x, y = float(b.get("X", 0)), float(b.get("Y", 0))
        w, h = float(b.get("Width", 0)), float(b.get("Height", 0))
        windows.append(WindowInfo(int(info["kCGWindowNumber"]), int(info["kCGWindowOwnerPID"]),
                                  "", minimized=not info.get("kCGWindowIsOnscreen", False),
                                  rect=Rect(round(x), round(y), round(x + w), round(y + h))))
    return windows


def list_windows(on_screen_only: bool = False) -> list[WindowInfo]:
    """App windows, front to back. Not only on screen: a session's window can be on
    another Space or minimized, and bringing its app forward still finds it."""
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGNullWindowID,
        kCGWindowListExcludeDesktopElements,
        kCGWindowListOptionAll,
        kCGWindowListOptionOnScreenOnly,
    )

    option = kCGWindowListOptionOnScreenOnly if on_screen_only else kCGWindowListOptionAll
    infos = CGWindowListCopyWindowInfo(option | kCGWindowListExcludeDesktopElements,
                                       kCGNullWindowID) or ()
    return windows_from_quartz(infos, os.getpid())


def front_window() -> WindowInfo | None:
    """The frontmost app's frontmost window."""
    from AppKit import NSWorkspace

    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return None
    pid = int(app.processIdentifier())
    return next((w for w in list_windows(on_screen_only=True) if w.pid == pid), None)


# ---- full screen ---------------------------------------------------------------------------
def screen_rects() -> list[Rect]:
    """Every screen, in Qt's coordinates (the first one has the menu bar)."""
    from AppKit import NSScreen

    screens = NSScreen.screens() or ()
    if not screens:
        return []
    primary_height = screens[0].frame().size.height
    rects = []
    for screen in screens:
        f = screen.frame()
        rects.append(cocoa_to_qt(f.origin.x, f.origin.y, f.size.width, f.size.height,
                                 primary_height))
    return rects


class MacFullscreen:
    """A full-screen app's window covers its whole screen, menu bar included. A
    zoomed ("maximized") window stops under the menu bar, so it doesn't count."""

    def is_fullscreen(self) -> bool:
        front = front_window()
        if front is None or front.rect is None:
            return False
        return looks_fullscreen(front, front.rect, screen_containing(front.rect, screen_rects()),
                                busy_state=False)


def activate_app(pid: int) -> bool:
    """Bring the app that owns ``pid`` to the front (with its frontmost window).

    Raising one exact window needs the Accessibility permission; that's for later
    (plan.md → Later). macOS 14+ may ignore an activation asked by an app that isn't
    active ("cooperative activation"), so ``open -a`` asks LaunchServices too,
    which is always allowed and doesn't open a new window for a running app.
    """
    from AppKit import NSRunningApplication

    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if app is None:
        return False
    activated = bool(app.activateWithOptions_(ACTIVATE_IGNORING_OTHER_APPS))
    url = app.bundleURL()
    if url is not None and (not activated or macos_major() >= 14):
        subprocess.Popen(["open", "-a", str(url.path())], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    return activated


def macos_major() -> int:
    """14 for macOS 14.5; 0 if unknown."""
    try:
        return int(_platform.mac_ver()[0].split(".")[0])
    except ValueError:
        return 0


def session_window(memory: WindowMemory, pid_chain: Sequence[int],
                   project: str) -> WindowInfo | None:
    return choose_window(list_windows(), pid_chain, project, memory.recall(pid_chain),
                         preferred_as_last_resort=True)


class MacFocuser:
    def __init__(self, memory: WindowMemory) -> None:
        self._memory = memory

    def focus(self, pid_chain: Sequence[int], project: str) -> bool:
        window = session_window(self._memory, pid_chain, project)
        return activate_app(window.pid) if window is not None else False


class MacActiveWindow:
    def __init__(self, memory: WindowMemory) -> None:
        self._memory = memory

    def foreground(self) -> int | None:
        window = front_window()
        return window.handle if window is not None else None

    def window_for(self, pid_chain: Sequence[int], project: str) -> int | None:
        window = session_window(self._memory, pid_chain, project)
        return window.handle if window is not None else None

    def note_prompt(self, pid_chain: Sequence[int]) -> None:
        self._memory.remember(pid_chain, front_window())


# ---- the global shortcut (Control+Option+Space) ----------------------------------------------
CARBON = "/System/Library/Frameworks/Carbon.framework/Carbon"
KEY_SPACE = 49  # kVK_Space
CONTROL_KEY, OPTION_KEY = 0x1000, 0x0800  # Carbon's controlKey, optionKey
KEYBOARD_CLASS, HOT_KEY_PRESSED = 0x6B657962, 5  # 'keyb', kEventHotKeyPressed
SIGNATURE = 0x54534B50  # 'TSKP': ours alone
HOT_KEY_EXISTS = -9878  # eventHotKeyExistsErr: another app owns the key


class EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


class EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)


def load_carbon():
    carbon = ctypes.CDLL(CARBON)
    carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
    carbon.GetApplicationEventTarget.argtypes = []
    carbon.InstallEventHandler.restype = ctypes.c_int32
    carbon.InstallEventHandler.argtypes = [ctypes.c_void_p, HANDLER, ctypes.c_ulong,
                                           ctypes.POINTER(EventTypeSpec), ctypes.c_void_p,
                                           ctypes.POINTER(ctypes.c_void_p)]
    carbon.RegisterEventHotKey.restype = ctypes.c_int32
    carbon.RegisterEventHotKey.argtypes = [ctypes.c_uint32, ctypes.c_uint32, EventHotKeyID,
                                           ctypes.c_void_p, ctypes.c_uint32,
                                           ctypes.POINTER(ctypes.c_void_p)]
    carbon.UnregisterEventHotKey.restype = ctypes.c_int32
    carbon.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
    carbon.RemoveEventHandler.restype = ctypes.c_int32
    carbon.RemoveEventHandler.argtypes = [ctypes.c_void_p]
    return carbon


class MacHotkey:
    """Carbon's RegisterEventHotKey: one system-wide key, no permission needed (unlike
    watching all key presses, which needs Accessibility). If another app already owns
    the key, macOS refuses and ``register`` returns False, so we never take it.
    The press arrives on the main thread (Carbon events run in the app's own loop)."""

    def __init__(self, carbon_loader: Callable = load_carbon) -> None:
        self._load = carbon_loader
        self._carbon = None
        self._handler = None  # the C callback; kept alive while registered
        self._handler_ref = ctypes.c_void_p()
        self._hotkey_ref = ctypes.c_void_p()

    def register(self, on_press: Callable[[], None]) -> bool:
        if self._hotkey_ref.value:
            return True
        try:
            carbon = self._carbon = self._carbon or self._load()
            target = carbon.GetApplicationEventTarget()

            def handle(_call_ref, _event, _user_data) -> int:
                with contextlib.suppress(Exception):
                    on_press()
                return 0  # noErr

            self._handler = HANDLER(handle)
            spec = EventTypeSpec(KEYBOARD_CLASS, HOT_KEY_PRESSED)
            if carbon.InstallEventHandler(target, self._handler, 1, ctypes.byref(spec), None,
                                          ctypes.byref(self._handler_ref)) != 0:
                self._handler = None
                return False
            status = carbon.RegisterEventHotKey(KEY_SPACE, CONTROL_KEY | OPTION_KEY,
                                                EventHotKeyID(SIGNATURE, 1), target, 0,
                                                ctypes.byref(self._hotkey_ref))
        except Exception:  # noqa: BLE001 (any Carbon or ctypes surprise: no shortcut, no crash)
            if self._carbon is not None:
                self._remove_handler()
            return False
        if status != 0:  # HOT_KEY_EXISTS: another app owns it
            self._remove_handler()
            self._hotkey_ref = ctypes.c_void_p()
            return False
        return True

    def unregister(self) -> None:
        if self._carbon is None:
            return
        if self._hotkey_ref.value:
            with contextlib.suppress(Exception):
                self._carbon.UnregisterEventHotKey(self._hotkey_ref)
            self._hotkey_ref = ctypes.c_void_p()
        self._remove_handler()

    def _remove_handler(self) -> None:
        if self._handler_ref.value:
            with contextlib.suppress(Exception):
                self._carbon.RemoveEventHandler(self._handler_ref)
            self._handler_ref = ctypes.c_void_p()
        self._handler = None


# ---- System Settings → Accessibility → Display ---------------------------------------------
class MacSystemPrefs:
    """Reduce motion and Increase contrast, read live (cheap; polled every 4 s)."""

    def read(self) -> SystemPrefs:
        from AppKit import NSUserDefaults, NSWorkspace

        workspace = NSWorkspace.sharedWorkspace()
        reduce_motion = bool(workspace.accessibilityDisplayShouldReduceMotion())
        if not workspace.accessibilityDisplayShouldIncreaseContrast():
            return SystemPrefs(reduce_motion=reduce_motion)
        style = NSUserDefaults.standardUserDefaults().stringForKey_("AppleInterfaceStyle")
        dark = str(style or "").lower() == "dark"
        return SystemPrefs(reduce_motion=reduce_motion,
                           high_contrast=increase_contrast_colors(dark))


def own_bundle(executable: str) -> str | None:
    """…/TaskPill.app/Contents/MacOS/TaskPill → …/TaskPill.app (None if not in a bundle)."""
    parts = executable.split("/")
    for i in range(len(parts) - 1, 0, -1):
        if parts[i].endswith(".app"):
            return "/".join(parts[: i + 1])
    return None


def clear_own_quarantine(executable: str, run=subprocess.run) -> bool:
    """A downloaded app is "quarantined". You approve TaskPill once ("Open Anyway"),
    but the hook helper inside it is started by Claude Code, not by you, and macOS
    could block it. So once TaskPill is running (you opened it), it removes the mark
    from its own bundle, and only its own. Quiet; failures don't matter."""
    bundle = own_bundle(executable)
    if bundle is None:
        return False
    try:
        run(["xattr", "-dr", "com.apple.quarantine", bundle], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def create_macos_platform() -> Platform:
    with contextlib.suppress(Exception):
        become_agent_app()
    if getattr(sys, "frozen", False):
        clear_own_quarantine(sys.executable)
    # Not strict: remember the window in front at a prompt even when the session's
    # processes don't reach it (iTerm2, tmux). See choose_window.
    memory = WindowMemory(strict=False)
    from taskpill import paths

    log = JsonlLog(paths.config_dir() / "menubar-log.jsonl")
    return dataclasses.replace(fallback_platform(), placement=MacPlacement(log),
                               topmost=MacTopmost(), name="macos",
                               focuser=MacFocuser(memory), active=MacActiveWindow(memory),
                               fullscreen=MacFullscreen(), hotkey=MacHotkey(),
                               prefs=MacSystemPrefs(), circle_by_default=True,
                               activate_self=activate_self)
