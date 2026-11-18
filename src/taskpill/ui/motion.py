"""Animation curves and values. Pure: time is passed in.

Timings follow docs/design.md: fades 0.12 s, morph 0.2 s, the Done loop 0.3 s,
and a needs-you glow every ~3.2 s.
"""

from __future__ import annotations

import math
import time

FADE = 0.12
MORPH = 0.2
EDGE = 0.3

GLOW_RISE = 0.8
GLOW_FALL = 1.2
GLOW_CYCLE = 3.2


def time_now() -> float:
    return time.monotonic()


def ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def ease_in_out_sine(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return -(math.cos(math.pi * t) - 1) / 2


class Animated:
    """A number that eases toward a target over a fixed duration."""

    def __init__(self, value: float, duration: float) -> None:
        self._from = value
        self._to = value
        self._start = 0.0
        self._duration = duration

    def set(self, target: float, now: float, *, instant: bool = False) -> None:
        if target == self._to and not instant:
            return
        self._from = target if instant else self.value(now)
        self._to = target
        self._start = now

    def value(self, now: float) -> float:
        if self._duration <= 0:
            return self._to
        t = (now - self._start) / self._duration
        if t >= 1:
            return self._to
        return self._from + (self._to - self._from) * ease_out_cubic(t)

    def shift(self, delta: float) -> None:
        """Move start and target by ``delta`` (e.g. the window's origin moved)."""
        self._from += delta
        self._to += delta

    @property
    def target(self) -> float:
        return self._to

    def running(self, now: float) -> bool:
        return self.value(now) != self._to


def glow(now: float, since: float) -> float:
    """Needs-you halo strength 0..1: a soft rise, a slow fall, then a rest."""
    t = (now - since) % GLOW_CYCLE
    if t < GLOW_RISE:
        return ease_in_out_sine(t / GLOW_RISE)
    t -= GLOW_RISE
    if t < GLOW_FALL:
        return 1 - ease_in_out_sine(t / GLOW_FALL)
    return 0.0
