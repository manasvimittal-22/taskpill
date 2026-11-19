"""How long recent tasks took, in <config dir>/history.json. Numbers only, no content."""

from __future__ import annotations

import json
from pathlib import Path

from taskpill.adapters.atomic import write_text_atomic


class DurationStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> list[float]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        values = raw.get("durations") if isinstance(raw, dict) else None
        if not isinstance(values, list):
            return []
        return [
            float(v)
            for v in values
            if isinstance(v, int | float) and not isinstance(v, bool) and v == v  # drop NaN
        ]

    def save(self, durations: list[float]) -> None:
        write_text_atomic(self._path, json.dumps({"durations": durations}) + "\n")
