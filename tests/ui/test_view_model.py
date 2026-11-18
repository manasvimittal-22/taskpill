import pytest

from taskpill.domain.session import STALE_AFTER_SECONDS, Session
from taskpill.ui.view_model import PillKind, build_model, build_models, format_elapsed
from tests.conftest import make_event


def session(*events, at=0.0, cwd="C:/code/taskpill"):
    s = Session("s1", now=at)
    s.apply(make_event("SessionStart", cwd=cwd), at)
    for name, extra, t in events:
        s.apply(make_event(name, **extra), t)
    return s


def test_working_model():
    s = session(
        ("UserPromptSubmit", {"prompt": "Fix the login bug"}, 0),
        ("PreToolUse", {"tool_name": "Edit", "tool_input": {"file_path": "login.py"}}, 10),
    )
    m = build_model(s, now=70)
    assert m.kind is PillKind.WORKING
    assert m.title == "taskpill"
    assert m.detail == "Editing login.py"
    assert 0 < m.percent < 95
    assert m.tooltip.prompt == "Fix the login bug"
    assert m.tooltip.elapsed == "Running for 1 min"
    assert m.tooltip.folder == "C:/code/taskpill"


def test_needs_you_shows_the_message():
    s = session(
        ("UserPromptSubmit", {}, 0),
        ("PermissionRequest", {"tool_name": "Bash", "tool_input": {"command": "npm i"}}, 5),
    )
    m = build_model(s, now=6)
    assert m.kind is PillKind.NEEDS_YOU
    assert m.detail == "Needs permission to run npm i"


def test_done_model():
    s = session(("UserPromptSubmit", {}, 0), ("Stop", {}, 125))
    m = build_model(s, now=200)
    assert m.kind is PillKind.DONE
    assert m.percent == 100
    assert m.fraction == 1.0
    assert m.tooltip.elapsed.startswith("Ran for")


def test_stale_model():
    s = session(("UserPromptSubmit", {}, 0))
    assert build_model(s, now=STALE_AFTER_SECONDS).kind is PillKind.STALE


def test_hidden_sessions_get_no_pill():
    idle = session()
    busy = session(("UserPromptSubmit", {}, 0))
    assert [m.session_id for m in build_models([idle, busy], now=1)] == ["s1"]
    assert build_models([idle], now=1) == []


def test_long_prompts_are_shortened_for_the_tooltip():
    s = session(("UserPromptSubmit", {"prompt": "word " * 100}, 0))
    assert len(build_model(s, now=1).tooltip.prompt) == 80


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(-5, "0 s"), (0, "0 s"), (59, "59 s"), (60, "1 min"), (3599, "59 min"),
     (3600, "1 h"), (3900, "1 h 5 min")],
)
def test_format_elapsed(seconds, text):
    assert format_elapsed(seconds) == text
