"""Words in the UI that differ between Windows and macOS. Pure, no Qt.

One place per OS, so a sentence never says "the ^ arrow" on a Mac.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class OsWords:
    system: str  # "Windows is set to reduce motion"
    home: str  # where the pill goes back to: "Back next to <home>."
    menu: str  # where Connect/Disconnect lives: "from <menu>"
    icon: str  # "Right-click <icon> to update."


WINDOWS = OsWords(system="Windows", home="the ^ arrow", menu="the tray menu",
                  icon="the TaskPill tray icon")
MACOS = OsWords(system="macOS", home="the notch", menu="the menu-bar icon",
                icon="the TaskPill menu-bar icon")


def words_for(platform: str | None = None) -> OsWords:
    return MACOS if (platform or sys.platform) == "darwin" else WINDOWS


WORDS = words_for()
