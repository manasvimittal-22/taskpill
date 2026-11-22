"""Update rules (Phase 10). Pure: no network, no clock.

* Versions look like ``0.1.0`` or ``v0.2.0`` (a GitHub release tag). Anything else
  never counts as newer, so a strange tag can't trigger an update.
* The installed app checks at most once a day.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CHECK_EVERY_SECONDS = 24 * 60 * 60
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse_version(text: str) -> tuple[int, int, int] | None:
    m = _VERSION.match(text.strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def is_newer(candidate: str, current: str) -> bool:
    new, now = parse_version(candidate), parse_version(current)
    return new is not None and now is not None and new > now


def due(last_check: float, now: float) -> bool:
    """Time for another check? (``last_check`` 0 = never checked.) A clock that went
    backwards counts as due, so a wrong clock can't stop checks forever."""
    return last_check <= 0 or now - last_check >= CHECK_EVERY_SECONDS or now < last_check


@dataclass(frozen=True)
class Release:
    version: str  # "0.2.0" (no "v")
    page_url: str  # the release page on GitHub
    installer_url: str | None  # TaskPill-Setup-<version>-Windows.exe, if attached
    installer_size: int = 0
