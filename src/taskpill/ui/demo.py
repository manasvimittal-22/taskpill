"""A scripted demo: two pretend Claude Code sessions, so the pills can be seen
without Claude Code. Used by ``python -m taskpill.main --demo``.

Timeline (seconds):
  0  taskpill: prompt                     → one full pill
  2  taskpill: editing login.py
  5  couchwave: prompt                    → both collapse into circles
  8  taskpill: needs permission           → its circle widens with the message
 13  taskpill: permission granted
 16  couchwave: done                      → ✓ circle
 19  taskpill: done
 25  couchwave: session ends              → back to one pill
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QTimer

from taskpill.domain.events import HookEvent

A, B = "demo-taskpill", "demo-couchwave"
A_DIR, B_DIR = "C:/code/taskpill", "C:/code/couchwave"

SCRIPT: list[tuple[float, dict]] = [
    (0.0, {"session_id": A, "hook_event_name": "UserPromptSubmit", "cwd": A_DIR,
           "prompt": "Fix the login bug where the session cookie expires too early"}),
    (2.0, {"session_id": A, "hook_event_name": "PreToolUse", "tool_name": "Edit",
           "tool_input": {"file_path": "C:/code/taskpill/login.py"}}),
    (3.0, {"session_id": A, "hook_event_name": "PostToolUse", "tool_name": "Edit",
           "tool_input": {"file_path": "C:/code/taskpill/login.py"}}),
    (5.0, {"session_id": B, "hook_event_name": "UserPromptSubmit", "cwd": B_DIR,
           "prompt": "Add tests for the playlist parser"}),
    (6.0, {"session_id": B, "hook_event_name": "PreToolUse", "tool_name": "Bash",
           "tool_input": {"command": "npm test"}}),
    (8.0, {"session_id": A, "hook_event_name": "PermissionRequest", "tool_name": "Bash",
           "tool_input": {"command": "npm install"}}),
    (13.0, {"session_id": A, "hook_event_name": "PostToolUse", "tool_name": "Bash",
            "tool_input": {"command": "npm install"}}),
    (16.0, {"session_id": B, "hook_event_name": "Stop"}),
    (19.0, {"session_id": A, "hook_event_name": "Stop"}),
    (25.0, {"session_id": B, "hook_event_name": "SessionEnd"}),
]


def play(emit: Callable[[HookEvent], None]) -> None:
    for at, payload in SCRIPT:
        event = HookEvent.from_payload(payload)
        QTimer.singleShot(int(at * 1000), lambda e=event: emit(e))
