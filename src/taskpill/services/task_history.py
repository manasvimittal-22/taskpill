"""Remembers how long recent tasks took, and hands out the matching % curve."""

from __future__ import annotations

import contextlib
from typing import Protocol

from taskpill.domain.calibration import MAX_SAMPLES, calibrated_config, is_measurable
from taskpill.domain.progress import ProgressConfig


class DurationStore(Protocol):
    def load(self) -> list[float]: ...
    def save(self, durations: list[float]) -> None: ...


class TaskHistory:
    def __init__(self, store: DurationStore, base: ProgressConfig | None = None) -> None:
        self._store = store
        self._base = base
        self._durations = [d for d in store.load() if is_measurable(d)][-MAX_SAMPLES:]
        self._config = calibrated_config(self._durations, base)

    def progress_config(self) -> ProgressConfig:
        """The curve for the next task. Changes only between tasks, never mid-task."""
        return self._config

    def record(self, active_seconds: float) -> None:
        """A task finished normally. Ignored if it was too short or too long to mean anything."""
        if not is_measurable(active_seconds):
            return
        self._durations = (self._durations + [float(active_seconds)])[-MAX_SAMPLES:]
        self._config = calibrated_config(self._durations, self._base)
        # a full disk or locked file must never disturb the pill
        with contextlib.suppress(OSError):
            self._store.save(self._durations)
