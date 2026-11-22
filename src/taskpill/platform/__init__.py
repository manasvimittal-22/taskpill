"""OS-specific code behind small interfaces (see base.py). Pick one with ``create_platform``."""

from __future__ import annotations

import sys

from taskpill.platform.base import Platform


def create_platform() -> Platform:
    if sys.platform == "win32":
        from taskpill.platform.windows import create_windows_platform

        return create_windows_platform()
    if sys.platform == "darwin":
        from taskpill.platform.macos import create_macos_platform

        return create_macos_platform()
    from taskpill.platform.base import fallback_platform

    return fallback_platform()
