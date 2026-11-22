"""macOS shortcut, accessibility settings and sounds (Phase 5 task 5), with fakes."""

import ctypes
import sys
from types import SimpleNamespace as NS

from taskpill.adapters.sound import AfplayPlayer, SilentPlayer, WinSoundPlayer, default_player
from taskpill.platform import macos
from taskpill.platform.base import increase_contrast_colors, jump_keys_for
from taskpill.ui.theme import high_contrast_palette
from tests.platform.test_macos import fake_mac  # noqa: F401 (fixture)


# ---- the shortcut ---------------------------------------------------------------------------
class FakeCarbon:
    def __init__(self, install=0, register=0):
        self.install_status, self.register_status = install, register
        self.handler = None
        self.registered = None
        self.calls = []

    def GetApplicationEventTarget(self):  # noqa: N802 (Carbon naming)
        return 0xA11

    def InstallEventHandler(self, target, handler, count, spec, user, out):  # noqa: N802
        self.handler = handler
        self.calls.append("install")
        if self.install_status == 0:
            out._obj.value = 0xB0B
        return self.install_status

    def RegisterEventHotKey(self, key, modifiers, hotkey_id, target, options, out):  # noqa: N802
        self.registered = (key, modifiers, hotkey_id.signature, target)
        self.calls.append("register")
        if self.register_status == 0:
            out._obj.value = 0xC0C
        return self.register_status

    def UnregisterEventHotKey(self, ref):  # noqa: N802
        self.calls.append("unregister")
        return 0

    def RemoveEventHandler(self, ref):  # noqa: N802
        self.calls.append("remove")
        return 0


def test_registers_control_option_space():
    carbon = FakeCarbon()
    hotkey = macos.MacHotkey(lambda: carbon)
    assert hotkey.register(lambda: None) is True
    key, modifiers, signature, target = carbon.registered
    assert key == macos.KEY_SPACE == 49
    assert modifiers == macos.CONTROL_KEY | macos.OPTION_KEY
    assert signature == macos.SIGNATURE
    assert target == 0xA11


def test_a_press_calls_back_and_a_failing_callback_is_contained():
    carbon = FakeCarbon()
    presses = []
    hotkey = macos.MacHotkey(lambda: carbon)
    hotkey.register(lambda: presses.append(1))
    assert carbon.handler(None, None, None) == 0
    assert presses == [1]

    def boom():
        raise RuntimeError("nope")

    hotkey2 = macos.MacHotkey(lambda: FakeCarbon())
    hotkey2.register(boom)
    assert hotkey2._handler(None, None, None) == 0  # never raises into Carbon


def test_a_key_another_app_owns_is_never_taken():
    carbon = FakeCarbon(register=macos.HOT_KEY_EXISTS)
    hotkey = macos.MacHotkey(lambda: carbon)
    assert hotkey.register(lambda: None) is False
    assert carbon.calls == ["install", "register", "remove"]  # the handler is cleaned up


def test_a_failed_handler_install_gives_no_shortcut():
    carbon = FakeCarbon(install=-50)
    assert macos.MacHotkey(lambda: carbon).register(lambda: None) is False
    assert "register" not in carbon.calls


def test_no_carbon_gives_no_shortcut_and_no_crash():
    def missing():
        raise OSError("no Carbon here")

    hotkey = macos.MacHotkey(missing)
    assert hotkey.register(lambda: None) is False
    hotkey.unregister()  # still safe


def test_unregister_releases_the_key_and_the_handler():
    carbon = FakeCarbon()
    hotkey = macos.MacHotkey(lambda: carbon)
    hotkey.register(lambda: None)
    hotkey.unregister()
    assert carbon.calls[-2:] == ["unregister", "remove"]
    assert hotkey.register(lambda: None) is True  # and can listen again


def test_registering_twice_keeps_one_key():
    carbon = FakeCarbon()
    hotkey = macos.MacHotkey(lambda: carbon)
    hotkey.register(lambda: None)
    hotkey.register(lambda: None)
    assert carbon.calls.count("register") == 1


def test_the_carbon_structures_have_carbons_layout():
    assert ctypes.sizeof(macos.EventTypeSpec) == 8
    assert ctypes.sizeof(macos.EventHotKeyID) == 8


def test_settings_names_the_keys_the_way_each_os_does():
    assert jump_keys_for("darwin") == ("Control", "Option", "Space")
    assert jump_keys_for("win32") == ("Ctrl", "Alt", "Space")


# ---- reduce motion and increase contrast ---------------------------------------------------
def set_prefs(reduce=False, contrast=False, style=None):
    appkit = sys.modules["AppKit"]
    appkit.NSWorkspace = NS(sharedWorkspace=lambda: NS(
        accessibilityDisplayShouldReduceMotion=lambda: reduce,
        accessibilityDisplayShouldIncreaseContrast=lambda: contrast))
    appkit.NSUserDefaults = NS(standardUserDefaults=lambda: NS(stringForKey_=lambda k: style))


def test_nothing_set(fake_mac):  # noqa: F811
    set_prefs()
    prefs = macos.MacSystemPrefs().read()
    assert prefs.reduce_motion is False and prefs.high_contrast is None


def test_reduce_motion(fake_mac):  # noqa: F811
    set_prefs(reduce=True)
    assert macos.MacSystemPrefs().read().reduce_motion is True


def test_increase_contrast_in_dark_mode(fake_mac):  # noqa: F811
    set_prefs(contrast=True, style="Dark")
    assert macos.MacSystemPrefs().read().high_contrast == increase_contrast_colors(dark=True)


def test_increase_contrast_in_light_mode(fake_mac):  # noqa: F811
    set_prefs(contrast=True, style=None)  # light mode has no AppleInterfaceStyle
    assert macos.MacSystemPrefs().read().high_contrast == increase_contrast_colors(dark=False)


def test_increase_contrast_colors_make_a_readable_palette():
    dark = high_contrast_palette(increase_contrast_colors(dark=True))
    light = high_contrast_palette(increase_contrast_colors(dark=False))
    assert dark.dark and not light.dark
    assert (dark.surface, dark.text) == ("#000000", "#FFFFFF")
    assert (light.surface, light.text) == ("#FFFFFF", "#000000")
    assert dark.needs_you != dark.working  # needs-you still stands out from working


def test_the_platform_has_the_shortcut_and_prefs(fake_mac):  # noqa: F811
    platform = macos.create_macos_platform()
    assert isinstance(platform.hotkey, macos.MacHotkey)
    assert isinstance(platform.prefs, macos.MacSystemPrefs)


# ---- sounds ---------------------------------------------------------------------------------
def test_afplay_plays_the_file_in_the_background(tmp_path):
    (tmp_path / "done.wav").write_bytes(b"RIFF")
    calls = []
    AfplayPlayer(tmp_path, popen=lambda args, **kw: calls.append(args)).play("done")
    assert calls == [["afplay", str(tmp_path / "done.wav")]]


def test_afplay_skips_a_missing_file(tmp_path):
    calls = []
    AfplayPlayer(tmp_path, popen=lambda args, **kw: calls.append(args)).play("nope")
    assert calls == []


def test_afplay_missing_stays_quiet(tmp_path):
    (tmp_path / "done.wav").write_bytes(b"RIFF")

    def no_afplay(args, **kw):
        raise FileNotFoundError("afplay")

    AfplayPlayer(tmp_path, popen=no_afplay).play("done")  # no exception


def test_each_os_gets_its_player():
    assert isinstance(default_player("darwin"), AfplayPlayer)
    assert isinstance(default_player("win32"), WinSoundPlayer)
    assert isinstance(default_player("linux"), SilentPlayer)


# ---- words that differ per OS ---------------------------------------------------------------
def test_mac_words_never_mention_windows_things():
    from taskpill.ui.os_words import MACOS, WINDOWS, words_for

    assert words_for("darwin") is MACOS and words_for("win32") is WINDOWS
    assert MACOS.home == "the notch" and MACOS.system == "macOS"
    assert "^" not in MACOS.home and "tray" not in MACOS.menu
    assert WINDOWS.home == "the ^ arrow"  # Windows wording unchanged


# ---- task 6: the packaged Mac app --------------------------------------------------------
def test_a_mac_copy_opens_the_download_page_for_updates(monkeypatch):
    from taskpill import main

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert main.is_portable("darwin") is True  # a .app is replaced by dragging the new one
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert main.is_portable("darwin") is False  # from source: git is the update


def test_finds_its_own_bundle():
    exe = "/Applications/TaskPill.app/Contents/MacOS/TaskPill"
    assert macos.own_bundle(exe) == "/Applications/TaskPill.app"
    assert macos.own_bundle("/Users/me/repo/.venv/bin/python") is None


def test_clears_quarantine_only_on_its_own_bundle():
    calls = []
    exe = "/Applications/TaskPill.app/Contents/MacOS/TaskPill"
    assert macos.clear_own_quarantine(exe, run=lambda args, **kw: calls.append(args)) is True
    assert calls == [["xattr", "-dr", "com.apple.quarantine", "/Applications/TaskPill.app"]]
    assert macos.clear_own_quarantine("/usr/bin/python3", run=lambda *a, **k: 1 / 0) is False


def test_a_failing_xattr_is_quiet():
    def broken(args, **kw):
        raise OSError("no xattr")

    exe = "/Applications/TaskPill.app/Contents/MacOS/TaskPill"
    assert macos.clear_own_quarantine(exe, run=broken) is False


def test_the_frozen_app_clears_its_quarantine_at_start(fake_mac, monkeypatch):  # noqa: F811
    seen = []
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/Applications/TaskPill.app/Contents/MacOS/TaskPill")
    monkeypatch.setattr(macos, "clear_own_quarantine", lambda exe: seen.append(exe))
    macos.create_macos_platform()
    assert seen == ["/Applications/TaskPill.app/Contents/MacOS/TaskPill"]


def test_update_notice_names_the_menu_bar_icon_on_a_mac():
    from taskpill.ui.os_words import MACOS

    assert MACOS.icon == "the TaskPill menu-bar icon"



def test_activate_self_uses_the_new_api_when_there(fake_mac):  # noqa: F811
    calls = []
    sys.modules["AppKit"].NSApplication = NS(sharedApplication=lambda: NS(
        activate=lambda: calls.append("activate")))
    macos.activate_self()
    sys.modules["AppKit"].NSApplication = NS(sharedApplication=lambda: NS(
        activateIgnoringOtherApps_=lambda flag: calls.append(("old", flag))))
    macos.activate_self()
    assert calls == ["activate", ("old", True)]


def test_windows_never_needs_to_activate_itself():
    from taskpill.platform.base import fallback_platform

    assert fallback_platform().activate_self() is None
