"""What a screen reader says about the pills. Pure: no Qt.

The pill is painted by hand, so Windows can't read it by itself. We give the
row an accessible description in plain words instead:

    "taskpill: needs you. Needs permission to run npm install."
    "2 sessions. taskpill: working, 42 percent. Editing login.py. couchwave: done."

Color is never the only signal for sighted users, and words are the signal here.
"""

from __future__ import annotations

from collections.abc import Sequence

from taskpill.ui.view_model import PillKind, PillModel

NAME = "TaskPill"


def _sentence(text: str) -> str:
    return text.strip().rstrip(".") + "."


def describe_one(model: PillModel) -> str:
    title = model.title
    match model.kind:
        case PillKind.WORKING:
            return f"{title}: working, {model.percent} percent. {_sentence(model.detail)}"
        case PillKind.STALE:
            return f"{title}: no news from Claude Code for 30 minutes."
        case PillKind.NEEDS_YOU:
            return f"{title}: needs you. {_sentence(model.detail)}"
        case PillKind.DONE:
            return f"{title}: done."
        case PillKind.LIMITED:
            return f"{title}: {_sentence(model.detail)}"
    return f"{title}."  # unreachable while PillKind is covered; never raise for speech


def describe(models: Sequence[PillModel]) -> str:
    """All pills in one description (empty when nothing is shown)."""
    if not models:
        return ""
    parts = [describe_one(m) for m in models]
    if len(models) > 1:
        parts.insert(0, f"{len(models)} sessions.")
    return " ".join(parts)


def announcement_key(models: Sequence[PillModel]) -> frozenset[tuple[str, str, str]]:
    """What is worth interrupting a screen reader for: which session is in which
    state. The % and the working step change all the time and are left out, so the
    reader isn't talking constantly. A needs-you message is included, because a new
    question is news."""
    return frozenset(
        (m.session_id, m.kind.value, m.detail if m.kind is PillKind.NEEDS_YOU else "")
        for m in models
    )


def needs_you_ids(models: Sequence[PillModel]) -> set[str]:
    return {m.session_id for m in models if m.kind is PillKind.NEEDS_YOU}
