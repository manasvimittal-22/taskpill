"""The JSON the app streams on /stream (for the VS Code extension).

Version 1 (keep vscode-extension/src/snapshot.ts in step):
    {"version": 1,
     "sessions": [{"id": "…", "project": "taskpill", "cwd": "C:/code/taskpill",
                   "kind": "working" | "needs_you" | "done" | "stale" | "limited",
                   "detail": "Editing login.py", "percent": 42, "prompt": "Fix the …"}]}

Sessions are oldest first, exactly the ones that have a pill (before the
full-screen filter, which only applies to the taskbar).
"""

from __future__ import annotations

from typing import Any

from taskpill.ui.view_model import PillModel

SNAPSHOT_VERSION = 1


def build_snapshot(models: list[PillModel]) -> dict[str, Any]:
    return {
        "version": SNAPSHOT_VERSION,
        "sessions": [
            {
                "id": m.session_id,
                "project": m.title,
                "cwd": m.tooltip.folder,
                "kind": m.kind.value,
                "detail": m.detail,
                "percent": m.percent,
                "prompt": m.tooltip.prompt,
            }
            for m in models
        ],
    }
