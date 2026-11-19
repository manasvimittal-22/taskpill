"""Estimated progress.

Claude Code doesn't report real progress, so we estimate it:

    estimate = ceiling · (1 − e^(−t/τ)) + step_bump · steps     (capped at ``cap``)

``t`` is *active* time only: the clock pauses while the session needs you.
The value never goes down, and only ``complete()`` reaches 100%.

Worked example with the defaults (ceiling 90, τ 240 s, +1 per step, cap 95):
after 4 minutes and 12 tool steps → 90·(1−e^−1) + 12 = 56.9 + 12 = 68.9 → shows 68%.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ProgressConfig:
    ceiling: float = 90.0
    tau_seconds: float = 240.0
    step_bump: float = 1.0
    cap: float = 95.0

    def __post_init__(self) -> None:
        if self.tau_seconds <= 0:
            raise ValueError("tau_seconds must be positive")
        if not 0 <= self.ceiling <= self.cap < 100:
            raise ValueError("need 0 <= ceiling <= cap < 100")
        if self.step_bump < 0:
            raise ValueError("step_bump must not be negative")


class Progress:
    """Estimated progress for one prompt. Time is passed in, never read."""

    def __init__(self, config: ProgressConfig | None = None) -> None:
        self._config = config or ProgressConfig()
        self._active_seconds = 0.0
        self._running_since: float | None = None
        self._steps = 0
        self._complete = False

    def start(self, now: float, config: ProgressConfig | None = None) -> None:
        """Begin a new prompt from 0%. A new curve only ever takes effect here."""
        if config is not None:
            self._config = config
        self._active_seconds = 0.0
        self._running_since = now
        self._steps = 0
        self._complete = False

    def pause(self, now: float) -> None:
        if self._running_since is not None:
            self._active_seconds += max(0.0, now - self._running_since)
            self._running_since = None

    def resume(self, now: float) -> None:
        if self._running_since is None and not self._complete:
            self._running_since = now

    def bump(self) -> None:
        if not self._complete:
            self._steps += 1

    def complete(self, now: float) -> None:
        self.pause(now)
        self._complete = True

    @property
    def is_complete(self) -> bool:
        return self._complete

    @property
    def steps(self) -> int:
        return self._steps

    def active_seconds(self, now: float) -> float:
        running = max(0.0, now - self._running_since) if self._running_since is not None else 0.0
        return self._active_seconds + running

    def value(self, now: float) -> float:
        """Estimated percent, 0–100."""
        if self._complete:
            return 100.0
        c = self._config
        t = self.active_seconds(now)
        estimate = c.ceiling * (1 - math.exp(-t / c.tau_seconds)) + c.step_bump * self._steps
        return min(estimate, c.cap)

    def percent(self, now: float) -> int:
        """Whole percent for display. Rounds down, so 99.9 never shows as 100."""
        return math.floor(self.value(now))
