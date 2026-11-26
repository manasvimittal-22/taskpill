"""Start TaskPill.

    python -m taskpill.main            # the real app (listens for hook events)
    python -m taskpill.main --demo     # plays a scripted demo, no Claude Code needed

Only one copy runs at a time (a lock file in the config folder). A second
copy, e.g. started by a hook while the app is already up, exits right away.
"""

from __future__ import annotations

import argparse
import os
import secrets
import signal
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from taskpill import __version__, paths
from taskpill.adapters.duration_store import DurationStore
from taskpill.adapters.event_server import EventServer
from taskpill.adapters.hook_command import resolve_hook_command
from taskpill.adapters.hooks_installer import HooksInstaller, SettingsFileError
from taskpill.adapters.runtime_file import (
    RuntimeInfo,
    ask_running_app_to_show_settings,
    remove_runtime_if_owned,
    write_runtime,
)
from taskpill.adapters.settings_store import SettingsStore
from taskpill.adapters.sound import default_player
from taskpill.app import TaskPillApp
from taskpill.platform import create_platform
from taskpill.services.clock import SystemClock
from taskpill.services.task_history import TaskHistory
from taskpill.services.updates import UpdateService


class EventBridge(QObject):
    """Hands events from server threads to the Qt main thread (queued signal)."""

    received = Signal(object)
    clicked = Signal(str)
    settings_requested = Signal()


def is_portable(platform: str | None = None) -> bool:
    """Updates open the download page instead of running an installer: the portable
    .zip (a portable.txt next to TaskPill.exe), and every Mac copy (a .app is
    replaced by dragging the new one into Applications)."""
    if not getattr(sys, "frozen", False):
        return False
    if (platform or sys.platform) == "darwin":
        return True
    return (Path(sys.executable).parent / "portable.txt").exists()


def make_update_service() -> UpdateService | None:
    """Only the installed or portable app checks for updates; from source, git is the
    update. (Phase 10.)"""
    if not getattr(sys, "frozen", False):
        return None
    from taskpill.adapters import github_releases

    return UpdateService(
        __version__,
        fetch=github_releases.fetch_latest,
        download=github_releases.download_installer,
        launch=lambda path: os.startfile(str(path)),  # noqa: S606 (our own installer)
        wall_clock=time.time,
    )


def _exit_watchdog(seconds: float = 3.0) -> None:
    """After Quit, make sure the process really ends. If anything still holds it open
    (a stuck thread or handle), it was left running in Task Manager; this ends it."""
    timer = threading.Timer(seconds, os._exit, args=(0,))
    timer.daemon = True  # a normal exit isn't delayed by it
    timer.start()


def run(demo: bool, background: bool = False) -> int:
    config = paths.config_dir()
    config.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(config / "taskpill.lock"))
    if not demo and not lock.tryLock(0):
        # Already running. A hook start has nothing to say; the user opening the app again
        # wants to see it, so ask the running copy to open Settings.
        if not background:
            ask_running_app_to_show_settings(paths.runtime_file())
        return 0

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("TaskPill")
    app.setQuitOnLastWindowClosed(False)

    taskpill = TaskPillApp(
        app,
        create_platform(),
        SettingsStore(config / "settings.json"),
        HooksInstaller(paths.claude_settings_file(), resolve_hook_command()),
        SystemClock(),
        quit_app=app.quit,
        demo=demo,
        sound_player=default_player(),
        updates=None if demo else make_update_service(),
        portable=is_portable(),
        task_history=None if demo else TaskHistory(DurationStore(config / "history.json")),
    )
    bridge = EventBridge()
    bridge.received.connect(taskpill.handle_event)
    bridge.clicked.connect(taskpill.click)
    bridge.settings_requested.connect(taskpill.open_settings)

    # Let Ctrl+C in a terminal quit the app (Qt otherwise swallows it).
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    wake = QTimer()
    wake.timeout.connect(lambda: None)
    wake.start(250)

    server = None
    runtime = paths.runtime_file()
    if demo:
        from taskpill.ui.demo import play

        play(bridge.received.emit)
    else:
        server = EventServer(sink=bridge.received.emit, token=secrets.token_urlsafe(32),
                             on_click=bridge.clicked.emit,
                             on_settings=bridge.settings_requested.emit)
        port = server.start()
        taskpill.set_publisher(server.publish)
        write_runtime(runtime, RuntimeInfo(port, server.token, os.getpid(), __version__))
        QTimer.singleShot(0, lambda: taskpill.start(background=background))

    try:
        return app.exec()
    finally:
        taskpill.shutdown()  # the icon and pill vanish at once
        _exit_watchdog(1.0)
        if server is not None:
            server.stop()
            remove_runtime_if_owned(runtime, os.getpid())
        lock.unlock()


def disconnect() -> int:
    """Remove TaskPill's hooks from Claude Code (the uninstaller runs this). No window."""
    installer = HooksInstaller(paths.claude_settings_file(), resolve_hook_command())
    try:
        installer.uninstall()
    except (SettingsFileError, OSError):
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    # The installed app has no console: Python then leaves stdout/stderr as None,
    # and any print (argparse's --version or an error) would crash.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")  # noqa: SIM115 (lives as long as the app)
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")  # noqa: SIM115
    parser = argparse.ArgumentParser(prog="taskpill")
    parser.add_argument("--demo", action="store_true", help="play a scripted demo")
    parser.add_argument("--background", action="store_true",
                        help="started by a Claude Code hook: don't open Settings")
    parser.add_argument("--disconnect", action="store_true",
                        help="remove TaskPill's hooks from Claude Code, then exit")
    parser.add_argument("--version", action="version", version=f"TaskPill {__version__}")
    args = parser.parse_args(argv)
    if args.disconnect:
        return disconnect()
    return run(args.demo, args.background)


if __name__ == "__main__":
    sys.exit(main())
