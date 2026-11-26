"""TaskPill hook helper: Claude Code runs this on every hook event.

It reads the event from stdin, keeps only the small fields TaskPill needs,
and sends it to the TaskPill app on 127.0.0.1. If the app isn't running and
a session is starting (SessionStart / UserPromptSubmit), it launches the app.

Hard rules (Claude Code waits on hooks and reads their output):
* Standard library only. This file must run on its own.
* **Never print anything.** Hook stdout becomes context for Claude.
* **Always exit 0**, whatever goes wrong. Problems go to hook.log
  (in the TaskPill config folder, capped in size).

Usage (written into ~/.claude/settings.json by the app):
    taskpill-hook --app <path to TaskPill> [--app-arg ARG ...] --taskpill-hook
"""

from __future__ import annotations

import contextlib
import http.client
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, BinaryIO

APP_NAME = "TaskPill"
ENV_OVERRIDE = "TASKPILL_CONFIG_DIR"
TOKEN_HEADER = "X-TaskPill-Token"

MAX_STDIN = 1024 * 1024
MAX_COMMAND = 500
SEND_TIMEOUT = 0.5
LAUNCH_WAIT = 3.0
LAUNCH_COOLDOWN = 15.0
MAX_LOG = 256 * 1024
MAX_PID_DEPTH = 16

LAUNCH_EVENTS = {"SessionStart", "UserPromptSubmit"}
KEEP_FIELDS = (
    "session_id",
    "hook_event_name",
    "cwd",
    "prompt",
    "message",
    "notification_type",
    "tool_name",
    "source",
    "reason",
)
KEEP_TOOL_INPUT = ("file_path", "notebook_path", "path", "command", "url")
# StopFailure only: why the turn failed ("rate_limit", "429 Too Many Requests",
# "API Error: Rate limit reached"). On Stop, last_assistant_message is Claude's
# reply, which must never leave, so these are kept for StopFailure alone.
FAILURE_FIELDS = ("error", "error_details", "last_assistant_message")
MAX_FAILURE_TEXT = 300


# ---- paths (keep in sync with src/taskpill/paths.py; a test checks it) -----
def config_dir() -> Path:
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME.lower()


# ---- main --------------------------------------------------------------------
def main(argv: list[str] | None = None, stdin: BinaryIO | None = None) -> int:
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
        raw = (stdin or _stdin()).read(MAX_STDIN + 1)
        if len(raw) > MAX_STDIN:
            return 0
        payload = slim(json.loads(raw))
        if payload is None:
            return 0
        event = payload["hook_event_name"]
        # Every event carries the parent chain (a few ms), so the app can always
        # find the session's window, even after it restarted mid-session: it keeps
        # sessions in memory only (Manasvi's bug, 2026-11-17: clicking a pill did
        # nothing because its chain had only come with a prompt before a restart).
        payload["pid_chain"] = pid_chain()

        if send(payload):
            return 0
        if event in LAUNCH_EVENTS and args["app"] and launch(args["app"], args["app_args"]):
            wait_and_send(payload)
    except Exception:
        log_error()
    return 0


def _stdin() -> BinaryIO:
    """The event pipe. In a windowless (no console) build, Python may leave
    sys.stdin as None even though Claude Code passed a pipe, so read fd 0."""
    if sys.stdin is not None:
        return sys.stdin.buffer
    return os.fdopen(0, "rb", closefd=False)


def parse_args(argv: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {"app": None, "app_args": []}
    it = iter(argv)
    for arg in it:
        if arg == "--app":
            result["app"] = next(it, None)
        elif arg == "--app-arg":
            value = next(it, None)
            if value is not None:
                result["app_args"].append(value)
    return result


def slim(data: Any) -> dict[str, Any] | None:
    """Keep only small, needed fields. File contents and tool output never leave."""
    if not isinstance(data, dict):
        return None
    if not isinstance(data.get("session_id"), str) or not isinstance(
        data.get("hook_event_name"), str
    ):
        return None
    out = {k: data[k] for k in KEEP_FIELDS if k in data}
    tool_input = data.get("tool_input")
    if isinstance(tool_input, dict):
        small = {k: tool_input[k] for k in KEEP_TOOL_INPUT if isinstance(tool_input.get(k), str)}
        if "command" in small:
            small["command"] = small["command"][:MAX_COMMAND]
        out["tool_input"] = small
    if data["hook_event_name"] == "StopFailure":
        for k in FAILURE_FIELDS:
            if isinstance(data.get(k), str):
                out[k] = data[k][:MAX_FAILURE_TEXT]
    return out


# ---- talking to the app ----------------------------------------------------------
def read_runtime() -> dict[str, Any] | None:
    try:
        info = json.loads((config_dir() / "runtime.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(info, dict) and isinstance(info.get("port"), int) and info.get("token"):
        return info
    return None


def send(payload: dict[str, Any]) -> bool:
    info = read_runtime()
    if info is None:
        return False
    body = json.dumps(payload).encode()
    conn = http.client.HTTPConnection("127.0.0.1", info["port"], timeout=SEND_TIMEOUT)
    try:
        conn.request(
            "POST",
            "/event",
            body=body,
            headers={"Content-Type": "application/json", TOKEN_HEADER: str(info["token"])},
        )
        status = conn.getresponse().status
    except OSError:
        return False
    finally:
        conn.close()
    return status == 204 or status == 400  # 400: the app is up but didn't want this event


def wait_and_send(payload: dict[str, Any]) -> bool:
    deadline = time.monotonic() + LAUNCH_WAIT
    while time.monotonic() < deadline:
        time.sleep(0.1)
        if send(payload):
            return True
    return False


def launch(app: str, app_args: list[str]) -> bool:
    """Start the app detached. At most once per LAUNCH_COOLDOWN across all hooks."""
    lock = config_dir() / "launch.stamp"
    try:
        if time.time() - lock.stat().st_mtime < LAUNCH_COOLDOWN:
            return True  # another hook just launched it; wait for it instead
    except OSError:
        pass
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(str(os.getpid()), encoding="utf-8")

    # A hook start is silent: only the tray icon. A start by the user opens Settings.
    app_args = [*app_args, "--background"]
    quiet: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED | NEW_GROUP | NO_WINDOW
        subprocess.Popen([app, *app_args], creationflags=flags, **quiet)
    elif sys.platform == "darwin" and app.endswith(".app"):
        subprocess.Popen(["open", "-g", "-a", app, "--args", *app_args], **quiet)
    else:
        subprocess.Popen([app, *app_args], start_new_session=True, **quiet)
    return True


# ---- process tree (lets the app find the terminal / VS Code window) ---------------
def pid_chain() -> list[int]:
    try:
        parents = _parent_map()
    except Exception:
        return []
    chain: list[int] = []
    pid = os.getppid()
    while pid > 0 and pid not in chain and len(chain) < MAX_PID_DEPTH:
        chain.append(pid)
        pid = parents.get(pid, 0)
    return chain


def _parent_map() -> dict[int, int]:
    if sys.platform == "win32":
        return _parent_map_windows()
    out = subprocess.run(
        ["ps", "-A", "-o", "pid=", "-o", "ppid="],
        capture_output=True,
        text=True,
        timeout=1,
        check=True,
    ).stdout
    parents: dict[int, int] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            parents[int(parts[0])] = int(parts[1])
    return parents


def _parent_map_windows() -> dict[int, int]:
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):  # noqa: N801 (Win32 name)
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if snapshot in (None, wintypes.HANDLE(-1).value):
        return {}
    parents: dict[int, int] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            parents[entry.th32ProcessID] = entry.th32ParentProcessID
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return parents


# ---- logging ---------------------------------------------------------------------
def log_error() -> None:
    with contextlib.suppress(Exception):
        path = config_dir() / "hook.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > MAX_LOG:
            path.unlink()
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8") as f:
            f.write(f"{stamp} {traceback.format_exc(limit=3)}\n")


if __name__ == "__main__":
    sys.exit(main())
