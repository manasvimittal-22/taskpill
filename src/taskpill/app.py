"""TaskPillApp: builds every part and keeps them in step (the composition root).

Everything that touches the outside world is passed in (platform, settings
store, hooks installer, clock), so tests can run the whole app with fakes and
never touch the real ~/.claude/settings.json.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import QObject, QPoint, QRect, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QApplication

from taskpill import __version__
from taskpill.adapters.hooks_installer import HooksInstaller, SettingsFileError
from taskpill.adapters.settings_store import Settings, SettingsStore
from taskpill.adapters.sound import SilentPlayer, SoundPlayer
from taskpill.domain.events import EventType, HookEvent
from taskpill.domain.session import SessionState
from taskpill.platform.base import Platform, SystemPrefs
from taskpill.services.clock import Clock
from taskpill.services.idle_quit import IdleQuit
from taskpill.services.session_store import SessionStore
from taskpill.services.sound_cues import Cue, SoundCues
from taskpill.services.task_history import TaskHistory
from taskpill.services.updates import UpdateService, UpdateState, UpdateStatus
from taskpill.ui.connect_dialog import ConnectDialog
from taskpill.ui.controller import PillController
from taskpill.ui.geometry import Dims
from taskpill.ui.icon import TrayState
from taskpill.ui.os_words import WORDS
from taskpill.ui.pill_row import PillRow, RowOptions
from taskpill.ui.platform_driver import PlatformDriver
from taskpill.ui.popups import PillMenu
from taskpill.ui.settings_window import SettingsWindow
from taskpill.ui.shell_style import shell_stylesheet
from taskpill.ui.snapshot import build_snapshot
from taskpill.ui.theme import Palette, high_contrast_palette, palette_for, system_is_dark
from taskpill.ui.tray import Tray
from taskpill.ui.view_model import PillKind, PillModel

IDLE_CHECK_MS = 30_000
UPDATE_FIRST_CHECK_MS = 20_000  # a little after start, so it never slows start-up
UPDATE_TICK_MS = 60 * 60 * 1000  # look every hour whether a day has passed
PRUNE_MS = 60_000
PREFS_MS = 4_000  # how often we look at Windows' reduce-motion and high-contrast choices


class TaskPillApp(QObject):
    jump_requested = Signal()  # the global shortcut was pressed (emitted from its own thread)

    def __init__(
        self,
        app: QApplication,
        platform: Platform,
        settings_store: SettingsStore,
        installer: HooksInstaller,
        clock: Clock,
        quit_app: Callable[[], None],
        *,
        demo: bool = False,
        show_tray: bool = True,
        sound_player: SoundPlayer | None = None,
        updates: UpdateService | None = None,
        portable: bool = False,
        task_history: TaskHistory | None = None,
    ) -> None:
        super().__init__()
        self._app = app
        self._platform = platform
        self._settings_store = settings_store
        self._installer = installer
        self._clock = clock
        self._quit_app = quit_app
        self._demo = demo
        self.settings: Settings = settings_store.load()
        self._settings_window: SettingsWindow | None = None
        self._connect_dialog: ConnectDialog | None = None
        self.hotkey_active = False  # True while the jump shortcut is really listening

        self._prefs: SystemPrefs = self._read_prefs()
        pal = self._palette()
        self.store = SessionStore(clock, task_history=task_history)
        self.row = PillRow(self._row_options(), pal,
                           dims=Dims(self.settings.pill_width, self.settings.pill_height))
        self._menu: PillMenu | None = None
        self.row.menu_requested.connect(self.open_pill_menu)
        self.row.resize_finished.connect(self._save_size)
        self._publish: Callable[[dict], None] | None = None
        self.sounds = SoundCues(sound_player or SilentPlayer(), clock)
        self.sounds.set_enabled(self.settings.sound_needs_you, self.settings.sound_done)
        self.controller = PillController(
            self.store, self.row, clock,
            focus=lambda s: platform.focuser.focus(s.pid_chain, s.project_name),
            on_models=self._publish_models,
            on_cue=self._on_cue,
        )
        self.jump_requested.connect(self.jump_to_waiting)
        self.driver = PlatformDriver(platform, self.row, self.controller)
        self.driver.set_hide_in_fullscreen(self.settings.hide_in_fullscreen)
        self.controller.set_needs_you_in_fullscreen(self.settings.needs_you_in_fullscreen)
        self._restore_position()
        self.row.moved.connect(self._remember_position)

        self.tray = Tray(pal, self.is_connected(), taskbar_dark=system_is_dark())
        self.tray.settings_requested.connect(self.open_settings)
        self.tray.connect_toggled.connect(self._toggle_connection)
        # The file can change behind our back (another tool, a manual edit), so the
        # menu re-reads the real state each time it opens (bug found 2026-11-17).
        self.tray.menu_opening.connect(self._connection_changed)
        self.tray.reset_position_requested.connect(self.reset_position)
        self.tray.quit_requested.connect(quit_app)
        self.tray.update_requested.connect(self.install_update)
        # Updates (Phase 10): only the installed / portable app checks; from source, None.
        self.updates = updates
        self._portable = portable
        if updates is not None:
            updates.changed.connect(self._on_update_status)
        if show_tray:
            self.tray.show()
        self.store.on_changed(lambda _s: self._update_tray())
        self.store.on_removed(lambda _sid: self._update_tray())

        self.idle = IdleQuit(clock, self.store.has_active,
                             0 if demo else self.settings.auto_quit_minutes)
        self._every(IDLE_CHECK_MS, self._check_idle)
        self._every(PRUNE_MS, self.store.prune)
        self._every(PREFS_MS, self._check_system_prefs)

        hints = QGuiApplication.styleHints()
        hints.colorSchemeChanged.connect(lambda _scheme: self._apply_look())
        self._apply_look()

    # ---- events ------------------------------------------------------------------------
    def handle_event(self, event: HookEvent) -> None:
        if event.type is EventType.USER_PROMPT_SUBMIT and event.pid_chain:
            # The window in front is where the prompt was typed: remember it for this session.
            with contextlib.suppress(Exception):
                self._platform.active.note_prompt(event.pid_chain)
        self.store.apply(event)

    def click(self, session_id: str) -> None:
        """A click from outside the taskbar (the VS Code status bar)."""
        self.controller.click(session_id)

    def jump_to_waiting(self) -> None:
        """The shortcut: go to the session that has needed you longest, like clicking its pill."""
        session = self.store.longest_waiting()
        if session is not None:
            self.controller.click(session.session_id)

    def _apply_hotkey(self) -> None:
        """Listen for the jump shortcut while it is switched on (and tell Settings the result)."""
        hotkey = self._platform.hotkey
        if self.settings.jump_hotkey and not self._demo:
            if not self.hotkey_active:
                self.hotkey_active = hotkey.register(self.jump_requested.emit)
        elif self.hotkey_active or not self.settings.jump_hotkey:
            hotkey.unregister()
            self.hotkey_active = False
        if self._settings_window is not None:
            self._settings_window.set_hotkey_status(self.hotkey_active)

    def set_publisher(self, publish: Callable[[dict], None]) -> None:
        """Where snapshots go (the event server's /stream)."""
        self._publish = publish
        self.controller.refresh()

    def _publish_models(self, models: list[PillModel]) -> None:
        if self._publish is not None:
            self._publish(build_snapshot(models))

    # ---- right-click menu & size -------------------------------------------------------
    def open_pill_menu(self, session_id: str, pill: QRect) -> PillMenu | None:
        session = self.store.get(session_id)
        if session is None:
            return None
        menu = PillMenu(self._palette())
        menu.add(f"Go to {session.project_name}",
                 lambda: self._platform.focuser.focus(session.pid_chain, session.project_name))
        if session.state in (SessionState.DONE, SessionState.LIMITED):
            menu.add("Clear", lambda: self.store.acknowledge(session_id))
        menu.addSeparator()
        menu.add("Resize…", lambda: self.row.begin_resize(session_id))
        # Reset position, not Reset size (Manasvi, 2026-11-17); the size resets from
        # Resize… → Reset. Only offered once the row has been dragged away.
        if self._screen_key() in self.settings.positions:
            menu.add("Reset position", self.reset_position)
        menu.addSeparator()
        menu.add("Settings…", self.open_settings)
        menu.add("Quit TaskPill", self._quit_app)
        self._menu = menu  # keep it alive while it's open
        menu.popup_above(pill)
        return menu

    def _save_size(self, dims: Dims) -> None:
        self._save(replace(self.settings, pill_width=round(dims.width),
                           pill_height=round(dims.height)))

    def reset_size(self) -> None:
        self.row.set_dims(Dims())
        self._save_size(Dims())

    # ---- startup -----------------------------------------------------------------------
    def start(self) -> None:
        """Refresh our hooks if connected; ask once if not. Check for updates soon."""
        if self._demo:
            return
        self._apply_hotkey()
        if self.updates is not None:
            QTimer.singleShot(UPDATE_FIRST_CHECK_MS, self._check_updates_if_due)
            self._every(UPDATE_TICK_MS, self._check_updates_if_due)
        if self.is_connected():
            with contextlib.suppress(SettingsFileError, OSError):
                self._installer.install()  # no-op unless TaskPill moved
        else:
            # Not connected: open Settings, which has the Connect button, so a new user
            # sees what to do (Manasvi, 2026-11-17). Shown at every start until connected.
            self.open_settings()

    def ask_to_connect(self) -> ConnectDialog:
        dialog = ConnectDialog(self._palette(), self._connect)
        dialog.finished.connect(self._on_connect_dialog_closed)
        self._connect_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    # ---- Claude Code connection --------------------------------------------------------
    def is_connected(self) -> bool:
        try:
            return self._installer.is_installed()
        except (SettingsFileError, OSError):
            return False

    def _connect(self) -> str | None:
        try:
            self._installer.install()
        except SettingsFileError as e:
            return _problem(e)
        except OSError as e:
            return f"{e.strerror or e}."
        self._connection_changed()
        return None

    def _disconnect(self) -> str | None:
        try:
            self._installer.uninstall()
        except SettingsFileError as e:
            return _problem(e)
        except OSError as e:
            return f"{e.strerror or e}."
        self._connection_changed()
        return None

    def _disconnect_and_report(self) -> str | None:
        """Disconnect, and say so if it failed: errors used to be dropped silently."""
        problem = self._disconnect()
        if problem is not None:
            self.tray.notify("Couldn't disconnect from Claude Code",
                             f"{problem} Nothing was changed. Try again in a moment.")
        self._connection_changed()  # show the real state either way
        return problem

    def _toggle_connection(self) -> None:
        if self.is_connected():
            self._disconnect_and_report()
        else:
            self.ask_to_connect()

    def _connection_changed(self) -> None:
        connected = self.is_connected()
        self.tray.set_connected(connected)
        if self._settings_window is not None:
            self._settings_window.set_connected(connected)

    def _on_connect_dialog_closed(self, _result: int) -> None:
        self._save(replace(self.settings, connect_asked=True))
        self._connect_dialog = None

    # ---- settings ----------------------------------------------------------------------
    def open_settings(self) -> SettingsWindow:
        if self._settings_window is None:
            window = SettingsWindow(self.settings, self._palette(), self.is_connected())
            window.settings_changed.connect(self._save)
            window.connect_requested.connect(self.ask_to_connect)
            window.disconnect_requested.connect(self._disconnect_and_report)
            window.reset_position_requested.connect(self.reset_position)
            window.reset_size_requested.connect(self.reset_size)
            window.update_check_requested.connect(self.check_updates_now)
            window.update_install_requested.connect(self.install_update)
            window.quit_requested.connect(self._quit_app)
            self._settings_window = window
        # A window built earlier may show a stale "Connected" (bug found 2026-11-17).
        self._settings_window.set_connected(self.is_connected())
        self._settings_window.set_hotkey_status(self.hotkey_active)
        self._settings_window.set_system_motion(self._prefs.reduce_motion)
        self._show_update_status()
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()
        return self._settings_window

    def _save(self, settings: Settings) -> None:
        self.settings = settings
        with contextlib.suppress(OSError):  # keep running with the settings in memory
            self._settings_store.save(settings)
        self.row.set_options(self._row_options())
        self.driver.set_hide_in_fullscreen(settings.hide_in_fullscreen)
        self.controller.set_needs_you_in_fullscreen(settings.needs_you_in_fullscreen)
        self.sounds.set_enabled(settings.sound_needs_you, settings.sound_done)
        self._apply_hotkey()
        if not self._demo:
            self.idle.set_minutes(settings.auto_quit_minutes)
        self._apply_look()

    def _on_cue(self, kind: PillKind, shown: bool) -> None:
        """A session just needs you, or just finished. Over a full-screen app only a
        needs-you pill that pops up chimes; a finished one stays quiet."""
        if self._demo or not shown:
            return
        self.sounds.cue(Cue.NEEDS_YOU if kind is PillKind.NEEDS_YOU else Cue.DONE)

    def _row_options(self) -> RowOptions:
        s = self.settings
        # Windows' own choices add to ours: its "animation off" means no motion here either,
        # and a high-contrast theme drops the soft glow (the dot and the edge still show).
        return RowOptions(anchor=self._platform.placement.anchor,
                          glow=s.glow and self._prefs.high_contrast is None,
                          expand_needs_you=s.expand_needs_you, dot=s.dot,
                          reduced_motion=s.reduced_motion or self._prefs.reduce_motion)

    def _read_prefs(self) -> SystemPrefs:
        try:
            return self._platform.prefs.read()
        except Exception:  # noqa: BLE001 (a failed look at Windows must never stop the pill)
            return getattr(self, "_prefs", SystemPrefs())

    def _check_system_prefs(self) -> None:
        """Windows' reduce-motion or high-contrast choice changed: follow it right away."""
        prefs = self._read_prefs()
        if prefs == self._prefs:
            return
        self._prefs = prefs
        self.row.set_options(self._row_options())
        self._apply_look()
        if self._settings_window is not None:
            self._settings_window.set_system_motion(prefs.reduce_motion)

    def _palette(self) -> Palette:
        s = self.settings
        if self._prefs.high_contrast is not None:
            return high_contrast_palette(self._prefs.high_contrast)
        return palette_for(system_is_dark(), s.accent, s.needs_you_color, s.done_color,
                           s.limited_color)

    def _apply_look(self) -> None:
        pal = self._palette()
        self.row.set_palette(pal)
        self.tray.set_palette(pal, system_is_dark())
        self._app.setStyleSheet(shell_stylesheet(pal))
        if self._settings_window is not None:
            self._settings_window.set_palette(pal)

    # ---- position ----------------------------------------------------------------------
    def _screen_key(self) -> str:
        screen = self._app.primaryScreen()
        g = screen.geometry()
        return f"{g.width()}x{g.height()}@{screen.devicePixelRatio():g}"

    def _restore_position(self) -> None:
        saved = self.settings.positions.get(self._screen_key())
        if saved:
            self.driver.use_user_anchor(QPoint(saved[0], saved[1]))

    def _remember_position(self, anchor: QPoint) -> None:
        positions = dict(self.settings.positions)
        positions[self._screen_key()] = [anchor.x(), anchor.y()]
        self._save(replace(self.settings, positions=positions))

    def reset_position(self) -> None:
        positions = dict(self.settings.positions)
        positions.pop(self._screen_key(), None)
        self._save(replace(self.settings, positions=positions))
        self.driver.reset_position()

    # ---- tray state & quitting -------------------------------------------------------------
    def _update_tray(self) -> None:
        states = {s.state for s in self.store.visible()}
        if SessionState.NEEDS_YOU in states:
            self.tray.set_state(TrayState.NEEDS_YOU)
        elif SessionState.LIMITED in states:
            self.tray.set_state(TrayState.LIMITED)
        elif SessionState.WORKING in states:
            self.tray.set_state(TrayState.WORKING)
        else:
            self.tray.set_state(TrayState.IDLE)

    # ---- updates (Phase 10) -------------------------------------------------------------
    def _check_updates_if_due(self) -> None:
        if self.updates is not None and self.settings.check_updates:
            self.updates.check_if_due(self.settings.last_update_check)

    def check_updates_now(self) -> None:
        if self.updates is not None:
            self.updates.check_now()

    def install_update(self) -> None:
        """Installed: download and run the installer. Portable: open the release page."""
        if self.updates is None:
            return
        release = self.updates.status.release
        if self._portable and release is not None:
            QDesktopServices.openUrl(QUrl(release.page_url))
        else:
            self.updates.install()

    def _on_update_status(self, status: UpdateStatus) -> None:
        if status.state in (UpdateState.UP_TO_DATE, UpdateState.AVAILABLE) and not status.message:
            self._save(replace(self.settings, last_update_check=time.time()))
        release = status.release if status.state in (
            UpdateState.AVAILABLE, UpdateState.DOWNLOADING) else None
        self.tray.set_update(release.version if release else None)
        announce = self.updates.take_announcement() if self.updates else None
        if announce is not None:
            self.tray.inform(f"TaskPill {announce.version} is available",
                             f"Right-click {WORDS.icon} to update.")
        self._show_update_status()

    def _show_update_status(self) -> None:
        window = self._settings_window
        if window is None:
            return
        if self.updates is None:
            window.set_update_status("From source, updates come with git.", None)
            return
        s = self.updates.status
        version = __version__
        if s.state is UpdateState.CHECKING:
            window.set_update_status("Checking GitHub…", None)
        elif s.state is UpdateState.DOWNLOADING:
            window.set_update_status("Downloading the update…", None)
        elif s.state is UpdateState.AVAILABLE and s.release is not None:
            label = "Open download page" if self._portable else f"Update to {s.release.version}"
            window.set_update_status(s.message or f"TaskPill {s.release.version} is available.",
                                     "open" if self._portable else "install", label)
        elif s.state is UpdateState.FAILED:
            window.set_update_status(s.message, "check", "Check now")
        elif s.state is UpdateState.UP_TO_DATE:
            window.set_update_status(f"You're up to date ({version}).", "check", "Check now")
        else:
            window.set_update_status(f"Version {version}.", "check", "Check now")

    def _check_idle(self) -> None:
        if self._settings_window is not None and self._settings_window.isVisible():
            return  # never quit while the user has the settings open
        if self.updates is not None and self.updates.status.state is UpdateState.DOWNLOADING:
            return  # an update is on its way
        if self._connect_dialog is not None:
            return
        if self.idle.should_quit():
            self._quit_app()

    def _every(self, ms: int, slot) -> QTimer:
        timer = QTimer(self)
        timer.setInterval(ms)
        timer.timeout.connect(slot)
        timer.start()
        return timer

    def shutdown(self) -> None:
        self.tray.hide()
        self.row.hide()


def _problem(error: SettingsFileError) -> str:
    text = str(error)
    if "not valid JSON" in text:
        return "~/.claude/settings.json isn't valid JSON (fix it, or remove it, and try again)."
    return text.rstrip(".") + "."
