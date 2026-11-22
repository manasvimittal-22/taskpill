"""Windows' reduce-motion and high-contrast choices, and the high-contrast palette."""

from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication

from taskpill.adapters.hooks_installer import HookCommand, HooksInstaller
from taskpill.adapters.settings_store import Settings, SettingsStore
from taskpill.app import TaskPillApp
from taskpill.platform.base import HighContrastColors, SystemPrefs, fallback_platform
from taskpill.ui.os_words import WORDS
from taskpill.ui.theme import high_contrast_palette
from tests.conftest import FakeClock

BLACK_AND_YELLOW = HighContrastColors(window="#000000", text="#FFFFFF", hotlight="#FFFF00",
                                      highlight="#1AEBFF", gray="#3FF23F")
WHITE = HighContrastColors(window="#FFFFFF", text="#000000", hotlight="#202020",
                           highlight="#37006E", gray="#600000")


class FakePrefs:
    def __init__(self, prefs=None):
        self.prefs = prefs or SystemPrefs()
        self.fail = False

    def read(self):
        if self.fail:
            raise OSError("no")
        return self.prefs


@pytest.fixture
def env(tmp_path):
    return {"settings": tmp_path / "config" / "settings.json",
            "claude": tmp_path / ".claude" / "settings.json"}


def build(qtbot, env, probe):
    platform = fallback_platform()
    platform.prefs = probe
    app = TaskPillApp(
        QApplication.instance(), platform, SettingsStore(env["settings"]),
        HooksInstaller(env["claude"], HookCommand("hook.exe", ("--app", "TaskPill.exe"))),
        FakeClock(), quit_app=lambda: None, show_tray=False,
    )
    qtbot.addWidget(app.row)
    return app


# ---- the palette -----------------------------------------------------------------------------
def test_high_contrast_palette_uses_the_themes_own_colors():
    pal = high_contrast_palette(BLACK_AND_YELLOW)
    assert (pal.surface, pal.text, pal.working) == ("#000000", "#FFFFFF", "#FFFF00")
    assert pal.needs_you == "#1AEBFF" and pal.limited == "#3FF23F"
    assert pal.dark is True
    assert high_contrast_palette(WHITE).dark is False


def test_text_is_never_the_disabled_gray():
    pal = high_contrast_palette(BLACK_AND_YELLOW)
    assert pal.text_soft == pal.text == pal.hairline


def test_needs_you_never_vanishes_into_the_background():
    same = replace(BLACK_AND_YELLOW, highlight="#000000")
    pal = high_contrast_palette(same)
    assert pal.needs_you != pal.surface


# ---- the app follows Windows -------------------------------------------------------------------
def test_windows_asking_for_less_motion_turns_motion_off(qtbot, env):
    probe = FakePrefs(SystemPrefs(reduce_motion=True))
    app = build(qtbot, env, probe)
    assert app._row_options().reduced_motion is True
    assert app.settings.reduced_motion is False  # the user's own switch is untouched


def test_a_change_in_windows_applies_live(qtbot, env):
    probe = FakePrefs()
    app = build(qtbot, env, probe)
    window = app.open_settings()
    assert app._row_options().reduced_motion is False
    assert f"{WORDS.system} is set" not in window.motion_hint.text()
    probe.prefs = SystemPrefs(reduce_motion=True)
    app._check_system_prefs()
    assert app._row_options().reduced_motion is True
    assert f"{WORDS.system} is set to reduce motion" in window.motion_hint.text()
    probe.prefs = SystemPrefs()
    app._check_system_prefs()
    assert app._row_options().reduced_motion is False
    window.close()


def test_high_contrast_changes_the_colors_and_drops_the_glow(qtbot, env):
    SettingsStore(env["settings"]).save(Settings(glow=True))
    probe = FakePrefs()
    app = build(qtbot, env, probe)
    assert app._row_options().glow is True
    probe.prefs = SystemPrefs(high_contrast=BLACK_AND_YELLOW)
    app._check_system_prefs()
    assert app._row_options().glow is False
    assert app._palette().working == "#FFFF00"
    assert app.row._palette.working == "#FFFF00"  # the row was repainted in the new colors
    probe.prefs = SystemPrefs()
    app._check_system_prefs()
    assert app._row_options().glow is True
    assert app._palette().working != "#FFFF00"


def test_high_contrast_at_start(qtbot, env):
    app = build(qtbot, env, FakePrefs(SystemPrefs(high_contrast=WHITE)))
    assert app._palette().surface == "#FFFFFF"


def test_a_failing_probe_never_breaks_the_app(qtbot, env):
    probe = FakePrefs(SystemPrefs(reduce_motion=True))
    app = build(qtbot, env, probe)
    probe.fail = True
    app._check_system_prefs()  # must not raise, and must keep what it knew
    assert app._row_options().reduced_motion is True


def test_unchanged_prefs_do_no_work(qtbot, env):
    app = build(qtbot, env, FakePrefs())
    calls = []
    app._apply_look = lambda: calls.append(1)
    app._check_system_prefs()
    assert calls == []
