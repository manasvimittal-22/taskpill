"""Playing TaskPill's two sounds (made by packaging/make_sounds.py).

Windows plays them with the built-in ``winsound`` (no extra libraries, nothing
added to the installer). Other systems are silent for now (macOS comes with
Phase 5). Playing never blocks and never raises: a sound is a nicety.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Protocol

SOUND_DIR = Path(__file__).resolve().parents[1] / "sounds"  # also right inside PyInstaller


class SoundPlayer(Protocol):
    def play(self, name: str) -> None:
        """Play ``<name>.wav`` without waiting for it to finish."""
        ...


class SilentPlayer:
    def play(self, name: str) -> None:
        return None


class WinSoundPlayer:
    def __init__(self, folder: Path = SOUND_DIR) -> None:
        self._folder = folder

    def play(self, name: str) -> None:
        path = self._folder / f"{name}.wav"
        if not path.is_file():
            return
        try:
            import winsound  # Windows only; elsewhere this player stays silent
        except ImportError:
            return
        try:
            flags = winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
            winsound.PlaySound(str(path), flags)
        except RuntimeError:
            pass  # no sound device, or the system refused: stay quiet


def default_player() -> SoundPlayer:
    return WinSoundPlayer() if sys.platform == "win32" else SilentPlayer()
