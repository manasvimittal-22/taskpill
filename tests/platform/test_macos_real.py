"""The real macOS APIs, called for real. Skipped everywhere but a Mac.

macos.py is written on Windows and its other tests use fakes (Manasvi's choice,
2026-11-22), so they can't tell whether a macOS name is spelled right. These can:
the release workflow runs them on GitHub's macOS runner before building the .dmg,
so a wrong name stops the release instead of reaching someone's Mac.
"""

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")

ROOT = Path(__file__).resolve().parents[2]


def test_reads_the_real_menu_bar():
    from taskpill.platform import macos

    info = macos.read_menu_bar()
    assert info is not None
    assert info.screen.width > 0 and info.screen.height > 0
    assert 18 <= info.bar_height <= 60
    assert info.notch_right is None or info.screen.left < info.notch_right < info.screen.right
    for icon in info.icons:
        assert icon.top < info.screen.top + info.bar_height


def test_the_spot_is_in_the_menu_bar_or_just_under_it():
    from taskpill.platform import macos
    from taskpill.platform.base import ScreenInfo

    info = macos.read_menu_bar()
    spot = macos.MacPlacement().spot([ScreenInfo(info.screen, 2.0)])
    assert info.screen.left < spot.x < info.screen.right
    assert info.screen.top <= spot.y < info.screen.top + info.bar_height + 60


def test_lists_windows_and_the_front_one():
    from taskpill.platform import macos

    windows = macos.list_windows()
    assert all(w.handle > 0 and w.pid > 0 for w in windows)
    macos.front_window()  # may be None on a runner; must not raise
    macos.MacActiveWindow(macos.WindowMemory(strict=False)).foreground()


def test_full_screen_and_screens():
    from taskpill.platform import macos

    assert macos.screen_rects()
    assert macos.MacFullscreen().is_fullscreen() in (True, False)


def test_reads_the_accessibility_settings():
    from taskpill.platform import macos
    from taskpill.platform.base import SystemPrefs

    assert isinstance(macos.MacSystemPrefs().read(), SystemPrefs)


def test_brings_finder_forward():
    from AppKit import NSWorkspace

    from taskpill.platform import macos

    finder = [a for a in NSWorkspace.sharedWorkspace().runningApplications()
              if a.bundleIdentifier() == "com.apple.finder"]
    if not finder:
        pytest.skip("Finder isn't running")
    assert macos.activate_app(int(finder[0].processIdentifier())) is True


def test_clears_quarantine_on_its_own_bundle_only(tmp_path):
    from taskpill.platform import macos

    exe = tmp_path / "TaskPill.app" / "Contents" / "MacOS" / "TaskPill"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    other = tmp_path / "other.txt"
    other.write_text("")
    for path in (exe, other):
        subprocess.run(["xattr", "-w", "com.apple.quarantine", "0081;00000000;Safari;", path],
                       check=True)
    assert macos.clear_own_quarantine(str(exe)) is True
    assert subprocess.run(["xattr", "-p", "com.apple.quarantine", exe],
                          capture_output=True).returncode != 0
    assert subprocess.run(["xattr", "-p", "com.apple.quarantine", other],
                          capture_output=True).returncode == 0


def test_afplay_is_there():
    assert shutil.which("afplay")


# The window level, Spaces, no Dock icon and the hotkey need Qt's real Mac display
# ("cocoa"); the rest of the suite uses "offscreen". So they run in a fresh process.
GUI_CHECK = textwrap.dedent("""
    import json, sys
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget
    from taskpill.platform import macos

    app = QApplication(sys.argv[:1])
    macos.become_agent_app()
    w = QWidget(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                | Qt.WindowType.WindowStaysOnTopHint)
    w.resize(200, 40)
    w.show()
    app.processEvents()
    macos.MacTopmost().keep_on_top(int(w.winId()))
    win = macos.ns_window(int(w.winId()))
    from AppKit import NSApplication
    hotkey = macos.MacHotkey()
    registered = hotkey.register(lambda: None)
    hotkey.unregister()
    print(json.dumps({
        "platform": app.platformName(),
        "level": int(win.level()),
        "behavior": int(win.collectionBehavior()),
        "hides": bool(win.hidesOnDeactivate()),
        "policy": int(NSApplication.sharedApplication().activationPolicy()),
        "hotkey": registered,
    }))
""")


def test_the_pill_window_and_the_shortcut_on_the_real_display():
    env = {**os.environ, "QT_QPA_PLATFORM": "cocoa", "PYTHONPATH": str(ROOT / "src")}
    done = subprocess.run([sys.executable, "-c", GUI_CHECK], env=env, capture_output=True,
                          text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout.strip().splitlines()[-1])
    from taskpill.platform import macos

    assert result["platform"] == "cocoa"
    assert result["level"] == macos.PILL_LEVEL
    assert result["behavior"] & macos.CAN_JOIN_ALL_SPACES
    assert result["behavior"] & macos.FULL_SCREEN_AUXILIARY
    assert result["hides"] is False
    assert result["policy"] == macos.ACCESSORY
    assert result["hotkey"] is True  # nothing else owns Control+Option+Space on a runner
