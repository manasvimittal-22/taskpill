"""Playing TaskPill's two sounds (made by packaging/make_sounds.py).

Windows plays them with the built-in ``winsound`` (no extra libraries, nothing
added to the installer). macOS plays them with ``afplay``, which every Mac has.
Other systems are silent. Playing never blocks and never raises: a sound is a nicety.
"""

from __future__ import annotations

import contextlib
import subprocess
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


class AfplayPlayer:
    """macOS: ``afplay <file>`` in the background. Nothing waits for it."""

    def __init__(self, folder: Path = SOUND_DIR, popen=subprocess.Popen) -> None:
        self._folder = folder
        self._popen = popen

    def play(self, name: str) -> None:
        path = self._folder / f"{name}.wav"
        if not path.is_file():
            return
        with contextlib.suppress(OSError):  # no afplay (not a Mac after all): stay quiet
            self._popen(["afplay", str(path)], stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def default_player(platform: str | None = None) -> SoundPlayer:
    platform = platform or sys.platform
    if platform == "win32":
        return WinSoundPlayer()
    if platform == "darwin":
        return AfplayPlayer()
    return SilentPlayer()
