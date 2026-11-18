"""When to play a sound (Manasvi, 2026-11-17: "add sound effects when needs
permission happens and done happens. a subtle sound, and a setting ... to disable
sounds for each").

* A session that *becomes* "needs you" or "done" asks for a cue.
* Each cue can be switched off in Settings.
* At most one sound every ``MIN_GAP`` seconds, so a burst of events (two sessions
  finishing together, a run of permission prompts) never stacks into noise.
"""

from __future__ import annotations

from enum import Enum

from taskpill.adapters.sound import SoundPlayer
from taskpill.services.clock import Clock

MIN_GAP = 1.5  # seconds


class Cue(Enum):
    NEEDS_YOU = "needs_you"
    DONE = "done"


class SoundCues:
    def __init__(self, player: SoundPlayer, clock: Clock) -> None:
        self._player = player
        self._clock = clock
        self._enabled = {Cue.NEEDS_YOU: True, Cue.DONE: True}
        self._last: float | None = None

    def set_enabled(self, needs_you: bool, done: bool) -> None:
        self._enabled = {Cue.NEEDS_YOU: needs_you, Cue.DONE: done}

    def cue(self, cue: Cue) -> bool:
        """Play the sound for ``cue`` if it's on and not too soon. True if played."""
        if not self._enabled[cue]:
            return False
        now = self._clock.now()
        if self._last is not None and now - self._last < MIN_GAP:
            return False
        self._last = now
        self._player.play(cue.value)
        return True
