"""Windows: taskbar placement, staying above the taskbar, window focus, full-screen.

Win32 through ctypes (no pywin32). UI Automation (the ``uiautomation``
package) is only used to find the "^" arrow and the app buttons precisely; if
it's missing or fails, the plain-Win32 ``TrayNotifyWnd`` position is used.

Facts found on Windows 11 (build 26300, 2026-11-17):
* ``Shell_TrayWnd`` → child ``TrayNotifyWnd`` starts exactly at the "^" arrow.
* UI Automation: the arrow is a Button with ClassName ``SystemTray.NormalButton``
  (AutomationId ``SystemTrayIcon``, name "Show Hidden Icons", localized).
  The app buttons sit in a Group with AutomationId ``TaskbarFrameRepeater``.
"""

from __future__ import annotations

import contextlib
import ctypes
import threading
import time
from collections.abc import Callable, Sequence
from ctypes import wintypes

from taskpill.platform.base import (
    Edge,
    HighContrastColors,
    Platform,
    Rect,
    ScreenInfo,
    Spot,
    SystemPrefs,
    TaskbarInfo,
    WindowInfo,
    WindowMemory,
    choose_window,
    colorref_to_hex,
    looks_fullscreen,
    spot_from_taskbar,
)
from taskpill.ui.geometry import Anchor

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ---- Win32 constants -------------------------------------------------------------------
ABM_GETSTATE = 0x4
ABM_GETTASKBARPOS = 0x5
ABS_AUTOHIDE = 0x1
ABE_LEFT, ABE_TOP, ABE_RIGHT, ABE_BOTTOM = 0, 1, 2, 3

HWND_TOPMOST = wintypes.HWND(-1)
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_NOOWNERZORDER = 0x1, 0x2, 0x10, 0x200
GWL_EXSTYLE = -20
GWL_STYLE = -16
WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE, WS_EX_TOPMOST = 0x80, 0x08000000, 0x8
WS_VISIBLE, WS_MINIMIZE = 0x10000000, 0x20000000
GW_OWNER = 4
SW_RESTORE = 9
MONITOR_DEFAULTTONEAREST = 2
VK_MENU, KEYEVENTF_KEYUP = 0x12, 0x2

# SHQueryUserNotificationState values that mean "don't disturb"
QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE = 2, 3, 4


class APPBARDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uCallbackMessage", wintypes.UINT),
        ("uEdge", wintypes.UINT),
        ("rc", wintypes.RECT),
        ("lParam", wintypes.LPARAM),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


shell32.SHAppBarMessage.restype = ctypes.c_size_t
shell32.SHAppBarMessage.argtypes = [wintypes.DWORD, ctypes.POINTER(APPBARDATA)]
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowExW.restype = wintypes.HWND
user32.GetForegroundWindow.restype = wintypes.HWND
user32.MonitorFromWindow.restype = wintypes.HANDLE
user32.GetWindow.restype = wintypes.HWND
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.UINT,
]

_EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _rect(r: wintypes.RECT) -> Rect:
    return Rect(r.left, r.top, r.right, r.bottom)


def window_rect(hwnd: int) -> Rect | None:
    r = wintypes.RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r)):
        return None
    return _rect(r)


# ---- taskbar -----------------------------------------------------------------------------
def read_taskbar(uia: _UiaTaskbar | None = None) -> TaskbarInfo | None:
    data = APPBARDATA(cbSize=ctypes.sizeof(APPBARDATA))
    if not shell32.SHAppBarMessage(ABM_GETTASKBARPOS, ctypes.byref(data)):
        return None
    edge = {ABE_LEFT: Edge.LEFT, ABE_TOP: Edge.TOP, ABE_RIGHT: Edge.RIGHT}.get(
        data.uEdge, Edge.BOTTOM
    )
    state = APPBARDATA(cbSize=ctypes.sizeof(APPBARDATA))
    autohide = bool(shell32.SHAppBarMessage(ABM_GETSTATE, ctypes.byref(state)) & ABS_AUTOHIDE)

    tray = None
    taskbar = user32.FindWindowW("Shell_TrayWnd", None)
    if taskbar:
        notify = user32.FindWindowExW(taskbar, None, "TrayNotifyWnd", None)
        if notify:
            tray = window_rect(notify)

    arrow = apps = None
    if uia is not None:
        arrow, apps = uia.read()
    return TaskbarInfo(_rect(data.rc), edge, autohide, arrow=arrow, tray=tray, apps=apps)


class _UiaTaskbar:
    """Finds the "^" arrow and the app buttons through UI Automation.

    The elements are cached; only their positions are read on each call. If
    anything fails, it backs off for a while and returns (None, None).
    """

    RETRY_AFTER = 30.0

    def __init__(self) -> None:
        self._arrow = None
        self._apps = None
        self._failed_at = 0.0
        try:
            import uiautomation  # noqa: F401
            self._available = True
        except Exception:
            self._available = False

    def read(self) -> tuple[Rect | None, Rect | None]:
        if not self._available or time.monotonic() - self._failed_at < self.RETRY_AFTER:
            return None, None
        try:
            if self._arrow is None:
                self._find()
            return self._rect_of(self._arrow), self._rect_of(self._apps)
        except Exception:
            self._arrow = self._apps = None
            self._failed_at = time.monotonic()
            return None, None

    def _find(self) -> None:
        import uiautomation as auto

        taskbar = user32.FindWindowW("Shell_TrayWnd", None)
        if not taskbar:
            raise LookupError("no taskbar")
        root = auto.ControlFromHandle(taskbar)
        self._arrow = root.ButtonControl(searchDepth=4, ClassName="SystemTray.NormalButton")
        self._apps = root.GroupControl(searchDepth=4, AutomationId="TaskbarFrameRepeater")
        if not self._arrow.Exists(0, 0):
            self._arrow = None
            raise LookupError("no arrow button")
        if not self._apps.Exists(0, 0):
            self._apps = None

    @staticmethod
    def _rect_of(control) -> Rect | None:
        if control is None:
            return None
        r = control.BoundingRectangle
        if r.right <= r.left or r.bottom <= r.top:
            return None
        return Rect(r.left, r.top, r.right, r.bottom)


class WindowsPlacement:
    anchor = Anchor.RIGHT

    def __init__(self) -> None:
        self._uia = _UiaTaskbar()

    def spot(self, screens: Sequence[ScreenInfo]) -> Spot | None:
        info = read_taskbar(self._uia)
        return spot_from_taskbar(info, screens) if info is not None else None


# ---- staying above the taskbar --------------------------------------------------------------
class WindowsTopmost:
    def __init__(self) -> None:
        self._styled: set[int] = set()

    def keep_on_top(self, window_id: int) -> None:
        hwnd = wintypes.HWND(window_id)
        if window_id not in self._styled:
            ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE,
                                     ex | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST)
            self._styled.add(window_id)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER)


# ---- window focus -------------------------------------------------------------------------
def list_windows() -> list[WindowInfo]:
    """Visible, un-owned, titled top-level windows, in z-order (top first)."""
    found: list[WindowInfo] = []

    def visit(hwnd, _lparam):
        style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
        if not style & WS_VISIBLE:
            return True
        if user32.GetWindow(hwnd, GW_OWNER):
            return True
        ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        if ex & WS_EX_TOOLWINDOW:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, length + 1)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        found.append(WindowInfo(int(hwnd), int(pid.value), title.value, cls.value,
                                bool(style & WS_MINIMIZE)))
        return True

    user32.EnumWindows(_EnumWindowsProc(visit), 0)
    return found


def bring_to_front(window: WindowInfo) -> bool:
    hwnd = wintypes.HWND(window.handle)
    if window.minimized:
        user32.ShowWindow(hwnd, SW_RESTORE)
    if user32.SetForegroundWindow(hwnd):
        return True
    # Windows only lets the process with the latest input change the foreground.
    # A tap of Alt counts as input from us; then it is allowed.
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    return bool(user32.SetForegroundWindow(hwnd))


def foreground_window() -> WindowInfo | None:
    """The window in front right now (None if there is none)."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    length = user32.GetWindowTextLengthW(hwnd)
    title = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, title, length + 1)
    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return WindowInfo(int(hwnd), int(pid.value), title.value, cls.value)


class WindowsFocuser:
    def __init__(self, memory: WindowMemory | None = None) -> None:
        self._memory = memory or WindowMemory()

    def focus(self, pid_chain: Sequence[int], project: str) -> bool:
        window = choose_window(list_windows(), pid_chain, project, self._memory.recall(pid_chain))
        return bring_to_front(window) if window is not None else False


# ---- full screen --------------------------------------------------------------------------
def _busy_state() -> bool:
    state = ctypes.c_int(0)
    try:
        if shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return False
    except (AttributeError, OSError):
        return False
    return state.value in (QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE)


def _monitor_rect(hwnd: int) -> Rect | None:
    monitor = user32.MonitorFromWindow(wintypes.HWND(hwnd), MONITOR_DEFAULTTONEAREST)
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    return _rect(info.rcMonitor)


class WindowsFullscreen:
    def __init__(self, own_pid: int | None = None) -> None:
        self._own_pid = own_pid if own_pid is not None else kernel32.GetCurrentProcessId()

    def is_fullscreen(self) -> bool:
        hwnd = user32.GetForegroundWindow()
        foreground = None
        rect = monitor = None
        if hwnd:
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value != self._own_pid:
                foreground = WindowInfo(int(hwnd), int(pid.value), "", cls.value)
                rect = window_rect(hwnd)
                monitor = _monitor_rect(hwnd)
        return looks_fullscreen(foreground, rect, monitor, _busy_state())


class WindowsActiveWindow:
    def __init__(self, memory: WindowMemory | None = None) -> None:
        self._memory = memory or WindowMemory()

    def note_prompt(self, pid_chain: Sequence[int]) -> None:
        self._memory.remember(pid_chain, foreground_window())

    def foreground(self) -> int | None:
        hwnd = user32.GetForegroundWindow()
        return int(hwnd) if hwnd else None

    def window_for(self, pid_chain: Sequence[int], project: str) -> int | None:
        window = choose_window(list_windows(), pid_chain, project, self._memory.recall(pid_chain))
        return window.handle if window is not None else None


# ---- the global shortcut (Ctrl+Alt+Space) --------------------------------------------------
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x1, 0x2, 0x4000
VK_SPACE = 0x20
HOTKEY_ID = 0x7461  # ours alone; any number works


class WindowsHotkey:
    """RegisterHotKey on a small thread of its own, which waits for WM_HOTKEY messages.

    Registering never takes the key from another app: if one already owns it,
    Windows refuses and ``register`` returns False.
    """

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._thread_id = 0

    def register(self, on_press: Callable[[], None]) -> bool:
        self.unregister()
        ready = threading.Event()
        result = {"ok": False}

        def run() -> None:
            ok = bool(user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT,
                                            VK_SPACE))
            result["ok"] = ok
            self._thread_id = kernel32.GetCurrentThreadId()
            ready.set()
            if not ok:
                return
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    with contextlib.suppress(Exception):  # a bad callback must not end the listener
                        on_press()
            user32.UnregisterHotKey(None, HOTKEY_ID)

        self._thread = threading.Thread(target=run, name="taskpill-hotkey", daemon=True)
        self._thread.start()
        ready.wait(2.0)
        if not result["ok"]:
            self._thread = None
        return result["ok"]

    def unregister(self) -> None:
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            thread.join(1.0)


# ---- accessibility choices ------------------------------------------------------------------
SPI_GETHIGHCONTRAST, SPI_GETCLIENTAREAANIMATION = 0x0042, 0x1042
HCF_HIGHCONTRASTON = 0x1
COLOR_WINDOW, COLOR_WINDOWTEXT, COLOR_GRAYTEXT, COLOR_HIGHLIGHT, COLOR_HOTLIGHT = 5, 8, 17, 13, 26


class _HighContrast(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwFlags", wintypes.DWORD),
                ("lpszDefaultScheme", wintypes.LPWSTR)]


class WindowsSystemPrefs:
    def read(self) -> SystemPrefs:
        return SystemPrefs(self._reduce_motion(), self._high_contrast())

    @staticmethod
    def _reduce_motion() -> bool:
        animations = wintypes.BOOL(True)
        if not user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0,
                                            ctypes.byref(animations), 0):
            return False  # unknown: assume animations are fine
        return not animations.value

    @staticmethod
    def _high_contrast() -> HighContrastColors | None:
        info = _HighContrast(cbSize=ctypes.sizeof(_HighContrast))
        if not user32.SystemParametersInfoW(SPI_GETHIGHCONTRAST, info.cbSize,
                                            ctypes.byref(info), 0):
            return None
        if not info.dwFlags & HCF_HIGHCONTRASTON:
            return None

        def color(index: int) -> str:
            return colorref_to_hex(user32.GetSysColor(index))

        return HighContrastColors(
            window=color(COLOR_WINDOW), text=color(COLOR_WINDOWTEXT),
            hotlight=color(COLOR_HOTLIGHT), highlight=color(COLOR_HIGHLIGHT),
            gray=color(COLOR_GRAYTEXT),
        )


def create_windows_platform() -> Platform:
    memory = WindowMemory()  # shared: what a prompt taught us is used by click and Done-on-switch
    return Platform(WindowsPlacement(), WindowsFocuser(memory), WindowsFullscreen(),
                    WindowsTopmost(), "windows", WindowsActiveWindow(memory), WindowsHotkey(),
                    WindowsSystemPrefs())
