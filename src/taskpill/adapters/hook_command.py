"""Which command Claude Code should run for our hooks, for this copy of TaskPill.

Installed app (PyInstaller):
    command: <install dir>/taskpill-hook(.exe)
    args:    --app <install dir>/TaskPill(.exe)          (macOS: the .app bundle)

From source (a developer's venv):
    command: <venv>/pythonw(.exe)   (python on macOS/Linux)
    args:    -I <repo>/hook/taskpill_hook.py --app <venv>/pythonw(.exe) --app-arg -m
             --app-arg taskpill.main
"""

from __future__ import annotations

import sys
from pathlib import Path

from taskpill.adapters.hooks_installer import HookCommand

REPO_ROOT = Path(__file__).resolve().parents[3]


def resolve_hook_command(
    frozen: bool | None = None,
    executable: str | None = None,
    platform: str | None = None,
    repo_root: Path = REPO_ROOT,
) -> HookCommand:
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    exe = Path(executable or sys.executable)
    platform = platform or sys.platform
    windows = platform == "win32"

    if frozen:
        hook = exe.with_name("taskpill-hook.exe" if windows else "taskpill-hook")
        app = _mac_bundle(exe) if platform == "darwin" else exe
        return HookCommand(str(hook), ("--app", str(app)))

    # From source: the hook and the app both run windowless on Windows, so no
    # console can flash on each hook event. (The helper reads fd 0 itself, since
    # pythonw leaves sys.stdin as None.) python.org's Python is signed, which also
    # gets it past Smart App Control when an unsigned build is blocked.
    gui_python = exe.with_name("pythonw.exe") if windows else exe
    return HookCommand(
        str(gui_python),
        ("-I", str(repo_root / "hook" / "taskpill_hook.py"),
         "--app", str(gui_python), "--app-arg", "-m", "--app-arg", "taskpill.main"),
    )


def _mac_bundle(exe: Path) -> Path:
    """…/TaskPill.app/Contents/MacOS/TaskPill → …/TaskPill.app"""
    for parent in exe.parents:
        if parent.suffix == ".app":
            return parent
    return exe
