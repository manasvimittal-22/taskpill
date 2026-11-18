"""Shared test helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_hook_helper() -> ModuleType:
    """Import hook/taskpill_hook.py by path (it is a standalone script, not a package)."""
    path = REPO_ROOT / "hook" / "taskpill_hook.py"
    spec = importlib.util.spec_from_file_location("taskpill_hook", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
