"""Developer console: run the event server + session store with no UI.

    python -m taskpill.dev_console                 # listen and print session changes
    python -m taskpill.dev_console connect         # add dev hooks to ~/.claude/settings.json
    python -m taskpill.dev_console disconnect      # remove them again

Events arrive on server threads and go through a queue to the main thread,
the same hand-off the Qt app will do with a signal.
"""

from __future__ import annotations

import argparse
import os
import queue
import secrets
import sys
from pathlib import Path

from taskpill import __version__, paths
from taskpill.adapters.event_server import EventServer
from taskpill.adapters.hooks_installer import HookCommand, HooksInstaller, SettingsFileError
from taskpill.adapters.runtime_file import RuntimeInfo, remove_runtime_if_owned, write_runtime
from taskpill.domain.events import HookEvent
from taskpill.domain.session import Session
from taskpill.services.clock import SystemClock
from taskpill.services.session_store import SessionStore

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_SCRIPT = REPO_ROOT / "hook" / "taskpill_hook.py"


def dev_hook_command() -> HookCommand:
    """Run the helper with this Python (a real .exe, as exec form needs on Windows)."""
    return HookCommand(command=sys.executable, args=("-I", str(HOOK_SCRIPT)))


def snapshot(store: SessionStore, clock: SystemClock) -> dict:
    now = clock.now()
    return {
        "sessions": [
            {
                "id": s.session_id,
                "project": s.project_name,
                "state": s.state.value,
                "step": s.step,
                "message": s.message,
                "percent": s.progress.percent(now),
            }
            for s in store.visible()
        ]
    }


def describe(session: Session, clock: SystemClock) -> str:
    pct = session.progress.percent(clock.now())
    extra = f" | {session.message}" if session.message else ""
    return f"[{session.project_name}] {session.state.value:<9} {pct:>3}% | {session.step}{extra}"


def listen() -> int:
    clock = SystemClock()
    store = SessionStore(clock)
    inbox: queue.Queue[HookEvent] = queue.Queue()
    server = EventServer(sink=inbox.put, token=secrets.token_urlsafe(32))
    port = server.start()
    runtime = paths.runtime_file()
    write_runtime(runtime, RuntimeInfo(port, server.token, os.getpid(), __version__))

    store.on_changed(lambda s: print(describe(s, clock), flush=True))
    store.on_removed(lambda sid: print(f"[{sid[:8]}] session ended", flush=True))
    print(f"TaskPill dev console on 127.0.0.1:{port}  (runtime file: {runtime})", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    try:
        while True:
            try:
                event = inbox.get(timeout=1.0)
            except queue.Empty:
                store.prune()
                continue
            store.apply(event)
            server.publish(snapshot(store, clock))
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        remove_runtime_if_owned(runtime, os.getpid())
    return 0


def change_hooks(install: bool) -> int:
    installer = HooksInstaller(paths.claude_settings_file(), dev_hook_command())
    try:
        result = installer.install() if install else installer.uninstall()
    except SettingsFileError as e:
        print(f"Nothing changed: {e}", file=sys.stderr)
        return 1
    if not result.changed:
        print("Already up to date." if install else "No TaskPill hooks found.")
    else:
        print(f"{'Added' if install else 'Removed'} hooks: {', '.join(result.events)}")
        if result.backup:
            print(f"Backup: {result.backup}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="taskpill.dev_console")
    parser.add_argument("command", nargs="?", choices=["listen", "connect", "disconnect"])
    args = parser.parse_args(argv)
    if args.command == "connect":
        return change_hooks(install=True)
    if args.command == "disconnect":
        return change_hooks(install=False)
    return listen()


if __name__ == "__main__":
    sys.exit(main())
