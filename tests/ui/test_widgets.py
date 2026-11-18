from PySide6.QtCore import QPoint, Qt

from taskpill.adapters.settings_store import Settings
from taskpill.ui.connect_dialog import ConnectDialog
from taskpill.ui.icon import TrayState, tray_icon
from taskpill.ui.settings_window import SettingsWindow
from taskpill.ui.theme import DARK, LIGHT, palette_for
from taskpill.ui.widgets import Segmented, Swatches, Toggle


def test_toggle_click_and_keyboard(qtbot):
    t = Toggle(DARK, checked=False)
    qtbot.addWidget(t)
    qtbot.mouseClick(t, Qt.MouseButton.LeftButton)
    assert t.isChecked()
    t.setFocus()
    qtbot.keyClick(t, Qt.Key.Key_Space)
    assert not t.isChecked()


def test_swatches_mouse_and_arrows(qtbot):
    s = Swatches(DARK, "violet")
    qtbot.addWidget(s)
    seen = []
    s.changed.connect(seen.append)
    qtbot.mouseClick(s, Qt.MouseButton.LeftButton, pos=QPoint(4 * 30 + 14, 14))
    assert s.current == "rose"
    qtbot.keyClick(s, Qt.Key.Key_Right)  # wraps round
    assert s.current == "violet"
    assert seen == ["rose", "violet"]


def test_swatches_unknown_current_falls_back():
    s = Swatches(DARK, "neon")
    assert s.current == "violet"


def test_segmented(qtbot):
    seg = Segmented(DARK, [(5, "5 min"), (10, "10 min"), (0, "Never")], 10)
    qtbot.addWidget(seg)
    seg.resize(300, 30)
    seen = []
    seg.changed.connect(seen.append)
    qtbot.mouseClick(seg, Qt.MouseButton.LeftButton, pos=QPoint(280, 15))
    assert seg.value == 0
    qtbot.keyClick(seg, Qt.Key.Key_Left)
    assert seg.value == 10
    qtbot.keyClick(seg, Qt.Key.Key_Left)
    qtbot.keyClick(seg, Qt.Key.Key_Left)  # stays at the first
    assert seg.value == 5
    assert seen == [0, 10, 5]


def test_settings_window_emits_every_change(qtbot):
    w = SettingsWindow(Settings(), DARK, connected=False)
    qtbot.addWidget(w)
    seen = []
    w.settings_changed.connect(seen.append)
    w.dot.click()
    w.fullscreen.click()
    w.auto_quit._select(4)  # Never
    assert seen[-1].dot is False
    assert seen[-1].hide_in_fullscreen is False
    assert seen[-1].auto_quit_minutes == 0


def test_settings_window_buttons(qtbot):
    w = SettingsWindow(Settings(), LIGHT, connected=False)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.connect_requested):
        w.connect_button.click()
    w.set_connected(True)
    with qtbot.waitSignal(w.disconnect_requested):
        w.connect_button.click()


def test_connect_dialog_success_and_failure(qtbot):
    calls = []
    ok = ConnectDialog(DARK, lambda: calls.append(1))
    qtbot.addWidget(ok)
    ok.show()
    ok.connect_button.click()
    assert calls == [1]
    assert not ok.isVisible()

    bad = ConnectDialog(DARK, lambda: "the file is locked.")
    qtbot.addWidget(bad)
    bad.show()
    bad.connect_button.click()
    assert bad.isVisible()
    assert bad.error.text() == "Couldn't connect: the file is locked. Nothing was changed."


def test_tray_icons_for_every_state():
    for state in TrayState:
        for dark in (True, False):
            icon = tray_icon(state, palette_for(dark), dark)
            assert not icon.isNull()
            assert icon.availableSizes()


def test_palette_for_accents():
    assert palette_for(True, "glacier").working == "#4FA3FF"
    assert palette_for(False, "glacier").working == "#1F6FD1"
    assert palette_for(True, "unknown").working == DARK.working
