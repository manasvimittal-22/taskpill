"""What one pill shows, built from a Session. Pure: no Qt."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from taskpill.domain.session import Session, SessionState

TOOLTIP_PROMPT = 80


class PillKind(Enum):
    WORKING = "working"
    NEEDS_YOU = "needs_you"
    DONE = "done"
    STALE = "stale"  # working, but nothing heard for 30 min
    LIMITED = "limited"  # out of usage (Claude Code stopped at a usage limit)


@dataclass(frozen=True)
class Tooltip:
    prompt: str
    step: str
    elapsed: str
    folder: str
    note: str = ""  # out of usage: Claude Code's own words, e.g. "… resets at 3pm"


@dataclass(frozen=True)
class PillModel:
    session_id: str
    title: str  # project folder name
    detail: str  # step text, or the needs-you message
    kind: PillKind
    percent: int
    tooltip: Tooltip

    @property
    def fraction(self) -> float:
        return max(0.0, min(1.0, self.percent / 100))


def build_models(sessions: Iterable[Session], now: float) -> list[PillModel]:
    return [build_model(s, now) for s in sessions if s.is_visible]


def build_model(session: Session, now: float) -> PillModel:
    kind = _kind(session, now)
    detail = session.message if kind is PillKind.NEEDS_YOU and session.message else session.step
    elapsed = format_elapsed(now - session.task_started_at)
    return PillModel(
        session_id=session.session_id,
        title=session.project_name,
        detail=detail or "Working",
        kind=kind,
        percent=session.progress.percent(now),
        tooltip=Tooltip(
            prompt=_shorten(session.prompt, TOOLTIP_PROMPT),
            step=session.step,
            elapsed=(
                f"Ran for {elapsed}" if kind in (PillKind.DONE, PillKind.LIMITED)
                else f"Running for {elapsed}"
            ),
            folder=session.cwd,
            note=session.message if kind is PillKind.LIMITED else "",
        ),
    )


def format_elapsed(seconds: float) -> str:
    """Plain words: "40 s", "3 min", "1 h 5 min"."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min" if minutes else f"{hours} h"


def _kind(session: Session, now: float) -> PillKind:
    if session.state is SessionState.NEEDS_YOU:
        return PillKind.NEEDS_YOU
    if session.state is SessionState.DONE:
        return PillKind.DONE
    if session.state is SessionState.LIMITED:
        return PillKind.LIMITED
    if session.is_stale(now):
        return PillKind.STALE
    return PillKind.WORKING


def _shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
