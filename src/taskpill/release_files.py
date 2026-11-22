"""The names of the files attached to each GitHub release. One place for them.

Each name says which system it's for (Manasvi, 2026-11-22: "rename the release
files better, clearly label windows and mac items"). The Windows installer keeps
the ``TaskPill-Setup-`` start and the ``.exe`` end: installed copies up to 0.2.1
find their update by exactly that, so they can still update with one click.

The build scripts (installer.iss, build_windows.ps1, build_macos.sh, release.yml)
can't import this, so tests/test_release_files.py checks they match.
"""

from __future__ import annotations

INSTALLER_PREFIX, INSTALLER_SUFFIX = "TaskPill-Setup-", ".exe"  # what updates look for


def windows_installer(version: str) -> str:
    return f"{INSTALLER_PREFIX}{version}-Windows{INSTALLER_SUFFIX}"


def windows_portable(version: str) -> str:
    return f"TaskPill-{version}-Windows-Portable.zip"


def mac_dmg(version: str) -> str:
    return f"TaskPill-{version}-Mac-AppleSilicon.dmg"


def is_windows_installer(name: str) -> bool:
    """The rule the update check uses (the same rule as every copy since 0.1.0)."""
    return name.startswith(INSTALLER_PREFIX) and name.endswith(INSTALLER_SUFFIX)


# What the release page shows next to each file (GitHub "labels").
LABELS = {
    "installer": "Windows: installer (recommended)",
    "portable": "Windows: portable zip, no install",
    "mac": "Mac: Apple Silicon, M1 or newer (.dmg)",
}
