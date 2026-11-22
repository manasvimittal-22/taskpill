"""Color options per state (Manasvi, 2026-11-17): Working, Needs you, Done, Out of usage."""

import json

import pytest
from PySide6.QtGui import QColor

from taskpill.adapters.settings_store import STATE_COLOR_CHOICES, Settings, SettingsStore
from taskpill.ui.icon import TrayState, tray_icon
from taskpill.ui.settings_window import SettingsWindow
from taskpill.ui.theme import DARK, LIGHT, STATE_COLORS, palette_for
from taskpill.ui.view_model import PillKind


def test_settings_and_theme_offer_the_same_names():
    assert {k: tuple(v) for k, v in STATE_COLORS.items()} == STATE_COLOR_CHOICES


def test_no_color_is_in_two_sets():
    values = [hex_ for colors in STATE_COLORS.values() for pair in colors.values()
              for hex_ in pair]
    assert len(values) == len(set(values))
    names = [n for colors in STATE_COLORS.values() for n in colors]
    assert len(names) == len(set(names))


def test_defaults_are_the_original_colors():
    assert palette_for(True) == DARK
    assert palette_for(False) == LIGHT
    s = Settings()
    assert (s.accent, s.needs_you_color, s.done_color, s.limited_color) == (
        "violet", "amber", "mint", "crimson")


@pytest.mark.parametrize("dark", [True, False])
def test_each_choice_changes_only_its_state(dark):
    pal = palette_for(dark, "glacier", "tangerine", "teal", "steel")
    i = 0 if dark else 1
    assert pal.working == STATE_COLORS["accent"]["glacier"][i]
    assert pal.needs_you == STATE_COLORS["needs_you_color"]["tangerine"][i]
    assert pal.done == STATE_COLORS["done_color"]["teal"][i]
    assert pal.limited == STATE_COLORS["limited_color"]["steel"][i]
    assert pal.edge(PillKind.LIMITED) == QColor(pal.limited)
    assert pal.surface == (DARK if dark else LIGHT).surface


def test_unknown_names_fall_back_to_the_defaults():
    assert palette_for(True, "neon", "neon", "neon", "neon") == DARK


def test_colors_are_saved_and_bad_values_fall_back(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    store.save(Settings(needs_you_color="gold", done_color="lime", limited_color="copper"))
    s = store.load()
    assert (s.needs_you_color, s.done_color, s.limited_color) == ("gold", "lime", "copper")
    # a working color isn't a needs-you color, and junk falls back on its own
    path.write_text(json.dumps({"needs_you_color": "violet", "done_color": 3,
                                "limited_color": "steel"}), encoding="utf-8")
    s = store.load()
    assert (s.needs_you_color, s.done_color, s.limited_color) == ("amber", "mint", "steel")


def test_settings_window_has_a_row_per_state_and_saves_choices(qtbot):
    window = SettingsWindow(Settings(), DARK, connected=True)
    qtbot.addWidget(window)
    saved = []
    window.settings_changed.connect(saved.append)
    rows = {"accent": window.swatches, "needs_you_color": window.needs_you_swatches,
            "done_color": window.done_swatches, "limited_color": window.limited_swatches}
    for field, swatches in rows.items():
        names = list(STATE_COLORS[field])
        assert swatches.current == names[0]
        swatches._choose(names[-1])
        assert getattr(saved[-1], field) == names[-1]


def test_tray_shows_out_of_usage_in_its_own_color(qtbot):
    pal = palette_for(True, limited="crimson")
    image = tray_icon(TrayState.LIMITED, pal).pixmap(32, 32).toImage()
    center = image.pixelColor(13, 16)  # on the left bar of the pause mark
    assert center.alpha() > 0
    assert abs(center.red() - QColor(pal.limited).red()) < 40


def test_needs_you_circles_stay_circles_by_default():
    """Manasvi, 2026-11-17: a needs-you circle stays a circle and shows "?"; nothing
    grows past the size that was set. ("Open circles to show the message" is off.)"""
    assert Settings().expand_needs_you is False


def test_settings_has_reset_size(qtbot, tmp_path):
    """Manasvi, 2026-11-17: "reset size should go in the settings menu"."""
    from tests.ui.test_app import build

    env = {"settings": tmp_path / "s.json", "claude": tmp_path / "c.json"}
    app, _, _ = build(qtbot, env)
    from taskpill.ui import geometry as g

    app.row.set_dims(g.Dims(300, 40))
    app._save_size(g.Dims(300, 40))
    window = app.open_settings()
    window.reset_size_button.click()
    assert app.row.dims == g.Dims()
    assert SettingsStore(env["settings"]).load().pill_width == 0  # the system's default
