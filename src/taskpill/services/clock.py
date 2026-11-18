"""Time source, injected so tests can control it."""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float:
        """Seconds, monotonic (only differences matter)."""
        ...


class SystemClock:
    def now(self) -> float:
        return time.monotonic()
