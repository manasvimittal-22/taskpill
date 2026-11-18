"""Where TaskPill keeps its files. Standard library only.

The hook helper (``hook/taskpill_hook.py``) has its own copy of
``config_dir`` because it must run with no imports from this package.
``tests/test_paths.py`` checks that both copies always agree.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "TaskPill"
ENV_OVERRIDE = "TASKPILL_CONFIG_DIR"  # used by tests and for portable setups


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


def runtime_file() -> Path:
    """Port + token of the running app. Written at startup, removed at exit."""
    return config_dir() / "runtime.json"


def claude_settings_file() -> Path:
    """Claude Code's user settings, where our hooks are installed."""
    return Path.home() / ".claude" / "settings.json"
