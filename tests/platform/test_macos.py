"""platform/macos.py against fake AppKit, Quartz and objc modules.

These run on any OS (Manasvi chose fake tests only, 2026-11-22). They check our
logic around the macOS calls; whether the real calls are spelled right is only
known on a Mac (the borrowed-Mac test rounds).
"""

import sys
import types
from types import SimpleNamespace as NS

import pytest

from taskpill.platform import macos
from taskpill.platform.base import NOTCH_GAP, Rect, ScreenInfo
from taskpill.ui.geometry import Anchor


def rect(x, y, w, h):
    return NS(origin=NS(x=x, y=y), size=NS(width=w, height=h))


class FakeScreen:
    """A 14" MacBook Pro: 1512 × 982 pt, a 37 pt menu bar, notch from 663 to 849."""

    def __init__(self, notch=True, frame=None, visible=None, aux=None):
        self._frame = frame or rect(0, 0, 1512, 982)
        self._visible = visible or rect(0, 0, 1512, 945)
        self._notch = notch
        self._aux = aux

    def frame(self):
        return self._frame

    def visibleFrame(self):  # noqa: N802 (AppKit naming)
        return self._visible

    def safeAreaInsets(self):  # noqa: N802
        return NS(top=37.0 if self._notch else 0.0)

    def auxiliaryTopRightArea(self):  # noqa: N802
        if self._aux is not None:
            return self._aux
        return rect(849, 945, 663, 37) if self._notch else rect(0, 0, 0, 0)


class OldScreen(FakeScreen):
    """macOS 11: no safe area, no auxiliary areas."""

    def __getattribute__(self, name):
        if name in ("safeAreaInsets", "auxiliaryTopRightArea"):
            raise AttributeError(name)
        return super().__getattribute__(name)


@pytest.fixture
def fake_mac(monkeypatch):
    state = NS(screens=[FakeScreen()], windows=[], thickness=24.0, policy=None)

    appkit = types.ModuleType("AppKit")
    appkit.NSScreen = NS(screens=lambda: state.screens)
    appkit.NSStatusBar = NS(systemStatusBar=lambda: NS(thickness=lambda: state.thickness))

    def set_policy(value):
        state.policy = value
        return True

    appkit.NSApplication = NS(sharedApplication=lambda: NS(setActivationPolicy_=set_policy))

    quartz = types.ModuleType("Quartz")
    quartz.kCGWindowListOptionOnScreenOnly = 1
    quartz.kCGWindowListOptionAll = 0
    quartz.kCGWindowListExcludeDesktopElements = 16
    quartz.kCGNullWindowID = 0
    quartz.kCGWindowLayer = "kCGWindowLayer"
    quartz.kCGWindowBounds = "kCGWindowBounds"
    quartz.CGWindowListCopyWindowInfo = lambda option, wid: state.windows

    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    monkeypatch.setitem(sys.modules, "Quartz", quartz)
    return state


def window(x, y, w, h, layer=macos.STATUS_ITEM_LAYER):
    return {"kCGWindowLayer": layer, "kCGWindowBounds": {"X": x, "Y": y, "Width": w, "Height": h}}


def test_reads_the_notch_and_the_bar(fake_mac):
    info = macos.read_menu_bar()
    assert info.screen == Rect(0, 0, 1512, 982)
    assert info.bar_height == 37.0
    assert info.notch_right == 849.0
    assert info.icons == ()


def test_no_notch_uses_what_the_bar_takes_from_the_screen(fake_mac):
    fake_mac.screens = [FakeScreen(notch=False, frame=rect(0, 0, 2560, 1440),
                                   visible=rect(0, 0, 2560, 1416))]
    info = macos.read_menu_bar()
    assert info.notch_right is None
    assert info.bar_height == 24.0


def test_an_auto_hiding_menu_bar_still_has_its_thickness(fake_mac):
    fake_mac.screens = [FakeScreen(notch=False, visible=rect(0, 0, 1512, 982))]
    fake_mac.thickness = 24.0
    assert macos.read_menu_bar().bar_height == 24.0


def test_macos_11_has_no_notch_api(fake_mac):
    fake_mac.screens = [OldScreen(notch=False, visible=rect(0, 0, 1440, 878),
                                  frame=rect(0, 0, 1440, 900))]
    info = macos.read_menu_bar()
    assert info.notch_right is None
    assert info.bar_height == 24.0


def test_an_auxiliary_area_given_relative_to_its_screen_is_moved(fake_mac):
    fake_mac.screens = [FakeScreen(frame=rect(100, 0, 1512, 982),
                                   visible=rect(100, 0, 1512, 945),
                                   aux=rect(949, 945, 663, 37))]
    assert macos.read_menu_bar().notch_right == 949.0  # inside the screen: already global
    fake_mac.screens = [FakeScreen(frame=rect(2000, 0, 1512, 982),
                                   visible=rect(2000, 0, 1512, 945),
                                   aux=rect(849, 945, 663, 37))]
    assert macos.read_menu_bar().notch_right == 2849.0


def test_only_menu_bar_icons_count(fake_mac):
    fake_mac.windows = [
        window(1340, 0, 32, 37),  # Wi-Fi
        window(1380, 0, 125, 37),  # the clock
        window(800, -10, 300, 64),  # our own pill window: taller than the bar
        window(200, 300, 800, 500, layer=0),  # an app window
        window(1400, 500, 30, 24),  # a status-level window further down the screen
        window(1300, 0, 0, 37),  # zero width
    ]
    icons = macos.read_menu_bar().icons
    assert icons == (Rect(1340, 0, 1372, 37), Rect(1380, 0, 1505, 37))


def test_no_screens_means_no_menu_bar(fake_mac):
    fake_mac.screens = []
    assert macos.read_menu_bar() is None


def test_placement_sits_right_of_the_notch(fake_mac):
    fake_mac.windows = [window(1340, 0, 32, 37)]
    placement = macos.MacPlacement()
    assert placement.anchor is Anchor.LEFT
    spot = placement.spot([ScreenInfo(Rect(0, 0, 1512, 982), 2.0)])
    assert spot.x == 849 + NOTCH_GAP
    assert spot.max_height == 31
    assert spot.room == 1340 - NOTCH_GAP - (849 + NOTCH_GAP)


def test_a_broken_api_falls_back_to_a_guess_instead_of_losing_the_pill(fake_mac, monkeypatch):
    def boom():
        raise AttributeError("no such selector")

    monkeypatch.setattr(macos, "read_menu_bar", boom)
    spot = macos.MacPlacement().spot([ScreenInfo(Rect(0, 0, 1440, 900), 2.0)])
    assert spot.x == 720 + 92 + NOTCH_GAP
    assert spot.max_height == 20.0


class FakeWindow:
    def __init__(self):
        self._level, self._behavior, self._hides = 3, 0, True
        self.calls = 0

    def level(self):
        return self._level

    def setLevel_(self, value):  # noqa: N802
        self.calls += 1
        self._level = value

    def collectionBehavior(self):  # noqa: N802
        return self._behavior

    def setCollectionBehavior_(self, value):  # noqa: N802
        self.calls += 1
        self._behavior = value

    def hidesOnDeactivate(self):  # noqa: N802
        return self._hides

    def setHidesOnDeactivate_(self, value):  # noqa: N802
        self.calls += 1
        self._hides = value


def test_the_pill_window_goes_above_the_menu_bar_on_every_space(monkeypatch):
    win = FakeWindow()
    monkeypatch.setattr(macos, "ns_window", lambda _id: win)
    macos.MacTopmost(is_cocoa=lambda: True).keep_on_top(1234)
    assert win.level() == macos.PILL_LEVEL
    assert win.collectionBehavior() & macos.CAN_JOIN_ALL_SPACES
    assert win.collectionBehavior() & macos.FULL_SCREEN_AUXILIARY
    assert win.hidesOnDeactivate() is False


def test_keeping_on_top_is_cheap_once_set(monkeypatch):
    win = FakeWindow()
    monkeypatch.setattr(macos, "ns_window", lambda _id: win)
    keeper = macos.MacTopmost(is_cocoa=lambda: True)
    keeper.keep_on_top(1)
    before = win.calls
    keeper.keep_on_top(1)
    assert win.calls == before


def test_ns_window_comes_from_the_qt_view(monkeypatch):
    seen = {}

    def objc_object(c_void_p):
        seen["ptr"] = c_void_p.value
        return NS(window=lambda: "the window")

    monkeypatch.setitem(sys.modules, "objc", NS(objc_object=objc_object))
    assert macos.ns_window(0xBEEF) == "the window"
    assert seen["ptr"] == 0xBEEF


def test_create_makes_an_agent_app_with_mac_placement(fake_mac):
    platform = macos.create_macos_platform()
    assert fake_mac.policy == macos.ACCESSORY
    assert platform.name == "macos"
    assert isinstance(platform.placement, macos.MacPlacement)
    assert isinstance(platform.topmost, macos.MacTopmost)
    assert isinstance(platform.focuser, macos.MacFocuser)
    assert isinstance(platform.active, macos.MacActiveWindow)


def test_create_survives_a_missing_appkit(monkeypatch):
    monkeypatch.setitem(sys.modules, "AppKit", None)  # import fails
    assert macos.create_macos_platform().name == "macos"


def test_never_touches_a_native_window_off_the_real_mac_display(monkeypatch):
    # Found on GitHub's Mac (2026-11-22): under Qt's offscreen display a winId isn't
    # an NSView, and treating it as one crashed Python. Now it isn't even looked at.
    def crash(_id):
        raise AssertionError("ns_window must not be called")

    monkeypatch.setattr(macos, "ns_window", crash)
    macos.MacTopmost(is_cocoa=lambda: False).keep_on_top(1234)
    macos.MacTopmost(is_cocoa=lambda: True).keep_on_top(0)  # no window yet


def test_the_default_check_asks_qt(qapp):
    assert macos.qt_is_cocoa() is False  # the test suite runs on Qt's offscreen display
