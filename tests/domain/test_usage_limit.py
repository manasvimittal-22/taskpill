"""Out of usage (Manasvi, 2026-11-17: "when ran out of usage, show on pill").

Claude Code ends a turn with StopFailure when the API refuses it. A usage limit
(``rate_limit``) or ``billing_error`` becomes a calm LIMITED pill that stays
until Claude Code carries on or you click it. Other errors stay "Stopped with
an error".
"""

import pytest

from taskpill.domain.events import HookEvent
from taskpill.domain.session import USAGE_BACK_MESSAGE, Session, SessionState
from taskpill.ui.view_model import PillKind, build_model
from tests.conftest import make_event

LIMIT_TEXT = "Claude usage limit reached. Your limit will reset at 3pm."


def working(now: float = 0) -> Session:
    s = Session("s1", now=now)
    s.apply(make_event("UserPromptSubmit", prompt="Fix the login bug"), now)
    s.apply(make_event("PostToolUse", tool_name="Edit", tool_input={"file_path": "a.py"}), now + 1)
    return s


def limit(**extra) -> HookEvent:
    return make_event("StopFailure", error="rate_limit", error_details="429 Too Many Requests",
                      last_assistant_message=LIMIT_TEXT, **extra)


def test_the_event_carries_the_error_and_claude_codes_words():
    e = limit()
    assert e.error == "rate_limit"
    assert e.error_text == LIMIT_TEXT
    # without the rendered text, the details are used
    assert make_event("StopFailure", error="rate_limit",
                      error_details="429 Too Many Requests").error_text == "429 Too Many Requests"
    assert make_event("StopFailure", error=42).error == ""  # junk is dropped


@pytest.mark.parametrize("error, label", [("rate_limit", "Out of usage"),
                                          ("billing_error", "Out of credits")])
def test_a_usage_error_shows_out_of_usage(error, label):
    s = working()
    assert s.apply(make_event("StopFailure", error=error, last_assistant_message="API Error"), 60)
    assert s.state is SessionState.LIMITED
    assert s.step == label
    assert s.is_visible


@pytest.mark.parametrize("error", ["server_error", "authentication_failed", "invalid_request",
                                   "max_output_tokens", "unknown", ""])
def test_other_errors_still_stop_with_an_error(error):
    s = working()
    s.apply(make_event("StopFailure", error=error), 60)
    assert s.state is SessionState.DONE
    assert s.step == "Stopped with an error"


def test_the_estimate_freezes_where_it_was():
    s = working()
    s.apply(limit(), 120)
    frozen = s.progress.percent(120)
    assert 0 < frozen < 100
    assert s.progress.percent(120 + 3 * 3600) == frozen  # a long wait doesn't move it


def test_it_is_calm_and_stays_through_idle_notifications():
    s = working()
    s.apply(limit(), 60)
    assert not s.apply(make_event("Notification", notification_type="idle_prompt"), 120)
    assert not s.apply(make_event("Notification", notification_type="quota_auto_resume_disabled",
                                  message="Stopped waiting"), 130)
    assert s.state is SessionState.LIMITED


def test_claude_code_carrying_on_brings_it_back_to_working():
    s = working()
    s.apply(limit(), 60)
    frozen = s.progress.percent(60)
    assert s.apply(make_event("Notification", notification_type="quota_auto_resume_fired"), 4000)
    assert s.state is SessionState.WORKING
    assert s.progress.percent(4000) == frozen  # the clock starts again from where it froze
    assert s.progress.percent(4060) > frozen


def test_a_reset_while_asleep_asks_you_to_press_enter():
    s = working()
    s.apply(limit(), 60)
    assert s.apply(make_event("Notification", notification_type="quota_auto_resume_stale"), 9000)
    assert s.state is SessionState.NEEDS_YOU
    assert s.message == USAGE_BACK_MESSAGE


def test_a_new_prompt_or_tool_event_carries_on():
    s = working()
    s.apply(limit(), 60)
    s.apply(make_event("PreToolUse", tool_name="Bash", tool_input={"command": "npm test"}), 70)
    assert s.state is SessionState.WORKING
    s.apply(limit(), 80)
    s.apply(make_event("UserPromptSubmit", prompt="again"), 90)
    assert s.state is SessionState.WORKING and s.step == "Thinking"


def test_clicking_clears_it():
    s = working()
    s.apply(limit(), 60)
    assert s.acknowledge()
    assert s.state is SessionState.IDLE and not s.is_visible


def test_the_pill_model_shows_it_with_claude_codes_words_in_the_card():
    s = working()
    s.apply(limit(), 60)
    m = build_model(s, 61)
    assert m.kind is PillKind.LIMITED
    assert m.detail == "Out of usage"
    assert m.tooltip.note == LIMIT_TEXT
    assert m.tooltip.elapsed.startswith("Ran for")


def test_a_repeated_failure_with_nothing_new_changes_nothing_visible():
    s = working()
    s.apply(make_event("StopFailure", error="rate_limit"), 60)
    assert not s.apply(make_event("StopFailure", error="rate_limit"), 61)
