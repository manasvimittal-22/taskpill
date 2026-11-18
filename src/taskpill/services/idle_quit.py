"""Decides when the app should quit by itself.

The app is started by Claude Code's hooks, so it doesn't need to stay around:
once nothing has been on screen for ``minutes`` it quits, and the next session
starts it again. 0 minutes = never quit.
"""

from __future__ import annotations

from collections.abc import Callable

from taskpill.services.clock import Clock


class IdleQuit:
    def __init__(self, clock: Clock, is_busy: Callable[[], bool], minutes: int = 10) -> None:
        self._clock = clock
        self._is_busy = is_busy
        self._minutes = minutes
        self._idle_since: float | None = clock.now()

    def set_minutes(self, minutes: int) -> None:
        self._minutes = minutes

    def should_quit(self) -> bool:
        """Call regularly. True once nothing has been busy for long enough."""
        now = self._clock.now()
        if self._is_busy():
            self._idle_since = None
            return False
        if self._idle_since is None:
            self._idle_since = now
        if self._minutes <= 0:
            return False
        return now - self._idle_since >= self._minutes * 60
