"""The tray (Windows) / menu-bar (macOS) icon and its menu."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from taskpill.ui.icon import TrayState, tray_icon
from taskpill.ui.theme import Palette


class Tray(QObject):
    settings_requested = Signal()
    connect_toggled = Signal()
    menu_opening = Signal()  # lets the app refresh the menu's text from the real state
    reset_position_requested = Signal()
    quit_requested = Signal()
    update_requested = Signal()

    def __init__(self, pal: Palette, connected: bool, taskbar_dark: bool = True) -> None:
        super().__init__()
        self._pal = pal
        self._state = TrayState.IDLE
        self._taskbar_dark = taskbar_dark

        self._menu = QMenu()
        self._menu.aboutToShow.connect(self.menu_opening)
        self._update_action = QAction(self._menu)
        self._update_action.triggered.connect(lambda: self.update_requested.emit())
        self._update_action.setVisible(False)
        self._menu.addAction(self._update_action)
        self._menu.addAction("Settings…", lambda: self.settings_requested.emit())
        self._connect_action = QAction(self._menu)
        self._connect_action.triggered.connect(lambda: self.connect_toggled.emit())
        self._menu.addAction(self._connect_action)
        self._menu.addAction("Reset position", lambda: self.reset_position_requested.emit())
        self._menu.addSeparator()
        self._menu.addAction("Quit TaskPill", lambda: self.quit_requested.emit())

        self._icon = QSystemTrayIcon()
        self._icon.setContextMenu(self._menu)
        self._icon.activated.connect(self._on_activated)
        self.set_connected(connected)
        self._refresh()

    def show(self) -> None:
        self._icon.show()

    def hide(self) -> None:
        self._icon.hide()

    def set_connected(self, connected: bool) -> None:
        self._connect_action.setText(
            "Disconnect from Claude Code" if connected else "Connect to Claude Code"
        )

    def set_update(self, version: str | None) -> None:
        """Show "Update to TaskPill <version>…" at the top of the menu (None hides it)."""
        self._update_action.setVisible(version is not None)
        if version is not None:
            self._update_action.setText(f"Update to TaskPill {version}…")

    def inform(self, title: str, text: str) -> None:
        """A friendly notification (e.g. an update is available)."""
        if self._icon.isVisible():
            self._icon.showMessage(title, text, QSystemTrayIcon.MessageIcon.Information, 8000)

    def notify(self, title: str, text: str) -> None:
        """A small Windows notification from the tray icon (e.g. a failed disconnect)."""
        if self._icon.isVisible():
            self._icon.showMessage(title, text, QSystemTrayIcon.MessageIcon.Warning, 6000)

    def set_state(self, state: TrayState) -> None:
        if state is not self._state:
            self._state = state
            self._refresh()

    def set_palette(self, pal: Palette, taskbar_dark: bool) -> None:
        self._pal, self._taskbar_dark = pal, taskbar_dark
        self._refresh()

    @property
    def state(self) -> TrayState:
        return self._state

    def _refresh(self) -> None:
        self._icon.setIcon(tray_icon(self._state, self._pal, self._taskbar_dark))
        tip = {
            TrayState.IDLE: "TaskPill: nothing running",
            TrayState.WORKING: "TaskPill: Claude is working",
            TrayState.NEEDS_YOU: "TaskPill: Claude needs you",
        }[self._state]
        self._icon.setToolTip(tip)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.settings_requested.emit()
