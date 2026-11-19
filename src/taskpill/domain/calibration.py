"""Tune the % curve to how long this user's tasks really take.

The default curve assumes a task takes about 4 minutes (τ = 240 s). If your
tasks usually take 40 seconds, the pill would crawl; if they take 15 minutes,
it would sit near the top too early. So we remember how long the last finished
tasks took (active seconds only, never any content) and set τ to their median.

Worked example: your last 5 tasks took 20, 35, 40, 55 and 90 seconds.
The median is 40 s, so τ = 40 s and a task that has run 40 s shows
90·(1 − e^−1) = 57%, instead of 13% with the default curve.

Pure rules, no I/O. Needs MIN_SAMPLES tasks before it changes anything.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import replace

from taskpill.domain.progress import ProgressConfig

MIN_SAMPLES = 5
MAX_SAMPLES = 30  # only the most recent tasks count, so it follows how you work now
MIN_TASK_SECONDS = 5.0  # shorter than this is a quick answer, not a task
MAX_TASK_SECONDS = 3600.0  # longer than this is probably left running, not worked on
TAU_RANGE = (30.0, 900.0)


def is_measurable(seconds: float) -> bool:
    """Is this duration worth remembering?"""
    return MIN_TASK_SECONDS <= seconds <= MAX_TASK_SECONDS


def calibrated_config(
    durations: Sequence[float], base: ProgressConfig | None = None
) -> ProgressConfig:
    """The % curve for these recent task durations (the base curve if too few)."""
    base = base or ProgressConfig()
    recent = [d for d in durations if is_measurable(d)][-MAX_SAMPLES:]
    if len(recent) < MIN_SAMPLES:
        return base
    low, high = TAU_RANGE
    tau = min(high, max(low, statistics.median(recent)))
    return replace(base, tau_seconds=tau)
