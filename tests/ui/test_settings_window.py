"""The Settings window's layout pieces (rework 2026-11-26): live preview, connection band,
footer actions."""

from dataclasses import replace

from taskpill import __version__
from taskpill.adapters.settings_store import Settings
from taskpill.ui.settings_preview import SettingsPreview
from taskpill.ui.settings_window import WINDOW_WIDTH, SettingsWindow
from taskpill.ui.theme import DARK, LIGHT, palette_for


def make(qtbot, connected=False, settings=None, pal=DARK):
    window = SettingsWindow(settings or Settings(), pal, connected)
    qtbot.addWidget(window)
    return window


def test_preview_follows_the_glow_and_dot_switches(qtbot):
    window = make(qtbot)
    assert (window.preview._glow, window.preview._dot) == (True, True)
    window.glow.click()
    assert window.preview._glow is False
    window.dot.click()
    assert window.preview._dot is False
    assert window.settings.glow is False and window.settings.dot is False


def test_preview_starts_from_the_saved_look(qtbot):
    window = make(qtbot, settings=replace(Settings(), glow=False, dot=False))
    assert (window.preview._glow, window.preview._dot) == (False, False)


def test_preview_takes_the_new_colors(qtbot):
    window = make(qtbot)
    pal = palette_for(True, accent="rose")
    window.set_palette(pal)
    assert window.preview._pal == pal


def test_preview_pills_fit_side_by_side(qtbot):
    preview = SettingsPreview(LIGHT, True, True)
    qtbot.addWidget(preview)
    preview.resize(WINDOW_WIDTH - 48, preview.height())
    rects = preview.pill_rects()
    assert len(rects) == 4
    for a, b in zip(rects, rects[1:], strict=False):
        assert a.right() < b.left()  # no overlap
    assert rects[-1].right() < preview.width() - 60  # room left for the caption
    assert all(r.top() >= 0 and r.bottom() <= preview.height() for r in rects)


def test_connection_band_asks_to_connect(qtbot):
    window = make(qtbot, connected=False)
    assert window.status_text.text() == "Not connected to Claude Code"
    assert "backs it up first" in window.status_hint.text()
    assert window.connect_button.text() == "Connect"
    assert window.connect_button.property("role") == "primary"
    asked = []
    window.connect_requested.connect(lambda: asked.append(True))
    window.connect_button.click()
    assert asked == [True]


def test_connection_band_goes_quiet_once_connected(qtbot):
    window = make(qtbot, connected=False)
    window.set_connected(True)
    assert window.status_text.text() == "Connected to Claude Code"
    assert window.connect_button.text() == "Disconnect"
    assert window.connect_button.property("role") == ""
    assert window.connect_box.property("needsConnect") is False
    gone = []
    window.disconnect_requested.connect(lambda: gone.append(True))
    window.connect_button.click()
    assert gone == [True]


def test_footer_actions(qtbot):
    window = make(qtbot)
    hits = []
    window.reset_position_requested.connect(lambda: hits.append("position"))
    window.reset_size_requested.connect(lambda: hits.append("size"))
    window.quit_requested.connect(lambda: hits.append("quit"))
    window.reset_size_button.click()
    window.quit_button.click()
    assert hits == ["size", "quit"]
    assert window.reset_size_button.toolTip().startswith("Back to")
    assert window.width() == WINDOW_WIDTH


def test_every_section_sits_in_its_own_box(qtbot):
    from PySide6.QtWidgets import QFrame

    window = make(qtbot)
    boxes = [f for f in window.findChildren(QFrame) if f.objectName() == "section"]
    assert [b.accessibleName() for b in boxes] == [
        "Colors", "When a session needs you", "Sounds", "Motion",
        "Full-screen apps", "Shortcuts", "Quit when idle for", "Updates",
    ]
    assert window.glow.parentWidget() is boxes[1]  # the rows live inside their box


def test_footer_shows_the_version(qtbot):
    window = make(qtbot)
    texts = [label.text() for label in window.findChildren(type(window.status_text))]
    assert f"TaskPill {__version__}" in texts
