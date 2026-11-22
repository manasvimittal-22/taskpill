"""The user's settings, in <config dir>/settings.json.

A missing or broken file never stops the app: every value falls back to its
default on its own, so one bad value doesn't reset the rest.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from taskpill.adapters.atomic import write_text_atomic

ACCENTS = ("violet", "glacier", "orchid", "slate", "rose")
# Color choices per state; the names match ui/theme.py STATE_COLORS (a test checks).
STATE_COLOR_CHOICES = {
    "accent": ACCENTS,
    "needs_you_color": ("amber", "tangerine", "gold"),
    "done_color": ("mint", "teal", "lime"),
    "limited_color": ("crimson", "copper", "steel"),
}
AUTO_QUIT_CHOICES = (5, 10, 30, 60, 0)  # minutes; 0 = never
WIDTH_RANGE = (180, 400)  # the pill's size, set in resize mode; or a circle (<= 44)
HEIGHT_RANGE = (26, 44)  # 44 still fits inside the 48 px Windows 11 taskbar


@dataclass
class Settings:
    # alerts when a session needs you
    glow: bool = True
    # off (Manasvi, 2026-11-17): a needs-you circle stays a circle with "?";
    # on: it opens to the set size (never wider)
    expand_needs_you: bool = False
    dot: bool = True
    # look
    accent: str = "violet"  # the color while working
    needs_you_color: str = "amber"
    done_color: str = "mint"
    limited_color: str = "crimson"  # out of usage
    reduced_motion: bool = False
    # 0 = this system's default (Manasvi, 2026-11-22: "for mac, default it to the circle
    # size"): a circle on a Mac, 232 on Windows. Files from before keep their number.
    pill_width: int = 0
    pill_height: int = 32
    # behavior
    hide_in_fullscreen: bool = True
    needs_you_in_fullscreen: bool = True  # ...but still show sessions that need you
    # sounds (Manasvi, 2026-11-17): a subtle chime for each, each can be turned off
    sound_needs_you: bool = True
    sound_done: bool = True
    # Ctrl+Alt+Space jumps to the session that needs you, from any app (Manasvi, 2026-11-18)
    jump_hotkey: bool = True
    # updates (Phase 10): the installed app asks GitHub once a day
    check_updates: bool = True
    last_update_check: float = 0.0  # wall-clock seconds of the last check
    auto_quit_minutes: int = 10
    # first launch
    connect_asked: bool = False
    # where the user dragged the row, per screen setup ("1536x960@1.25" → [x, y])
    positions: dict[str, list[int]] = field(default_factory=dict)


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> Settings:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return Settings()
        return _from_dict(raw if isinstance(raw, dict) else {})

    def save(self, settings: Settings) -> None:
        write_text_atomic(self._path, json.dumps(asdict(settings), indent=2) + "\n")


def _from_dict(raw: dict[str, Any]) -> Settings:
    defaults = Settings()
    values: dict[str, Any] = {}
    for f in fields(Settings):
        default = getattr(defaults, f.name)
        value = raw.get(f.name, default)
        values[f.name] = _valid(f.name, value, default)
    return Settings(**values)


def _valid(name: str, value: Any, default: Any) -> Any:
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if name in STATE_COLOR_CHOICES:
        return value if value in STATE_COLOR_CHOICES[name] else default
    if name in ("pill_width", "pill_height"):
        low, high = WIDTH_RANGE if name == "pill_width" else HEIGHT_RANGE
        ok = isinstance(value, int) and not isinstance(value, bool)
        if ok and name == "pill_width" and value == 0:
            return 0  # the system's default size
        if ok and name == "pill_width" and value <= HEIGHT_RANGE[1]:
            return max(HEIGHT_RANGE[0], value)  # a circle pill (width == height)
        return max(low, min(high, value)) if ok else default
    if name == "auto_quit_minutes":
        ok = isinstance(value, int) and not isinstance(value, bool)
        return value if ok and value in AUTO_QUIT_CHOICES else default
    if name == "last_update_check":
        ok = isinstance(value, int | float) and not isinstance(value, bool)
        return float(value) if ok and value >= 0 else default
    if name == "positions":
        if not isinstance(value, dict):
            return {}
        return {
            str(k): [int(v[0]), int(v[1])]
            for k, v in value.items()
            if isinstance(v, list) and len(v) == 2
            and all(isinstance(n, int) and not isinstance(n, bool) for n in v)
        }
    return default
