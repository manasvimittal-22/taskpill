import pytest

from taskpill.domain.events import (
    MAX_PID_CHAIN,
    MAX_PROMPT,
    EventType,
    HookEvent,
    InvalidEventError,
)


def test_parses_a_full_payload():
    event = HookEvent.from_payload(
        {
            "session_id": "abc",
            "hook_event_name": "PreToolUse",
            "cwd": "C:\\code\\taskpill",
            "tool_name": "Edit",
            "tool_input": {"file_path": "app.py"},
            "pid_chain": [120, 88, 4],
            "transcript_path": "ignored",
        }
    )
    assert event.session_id == "abc"
    assert event.type is EventType.PRE_TOOL_USE
    assert event.cwd == "C:\\code\\taskpill"
    assert event.tool_name == "Edit"
    assert event.tool_input == {"file_path": "app.py"}
    assert event.pid_chain == (120, 88, 4)


@pytest.mark.parametrize("payload", [None, [], "text", 42])
def test_rejects_non_objects(payload):
    with pytest.raises(InvalidEventError):
        HookEvent.from_payload(payload)


@pytest.mark.parametrize("session_id", [None, "", "   ", 5, "x" * 201])
def test_rejects_bad_session_ids(session_id):
    with pytest.raises(InvalidEventError):
        HookEvent.from_payload({"session_id": session_id, "hook_event_name": "Stop"})


@pytest.mark.parametrize("name", [None, "", "SubagentStop", "stop", "PreCompact"])
def test_rejects_unsupported_events(name):
    with pytest.raises(InvalidEventError):
        HookEvent.from_payload({"session_id": "a", "hook_event_name": name})


def test_cuts_long_text_and_marks_it():
    event = HookEvent.from_payload(
        {"session_id": "a", "hook_event_name": "UserPromptSubmit", "prompt": "y" * 5000}
    )
    assert len(event.prompt) == MAX_PROMPT
    assert event.prompt.endswith("…")


def test_wrong_types_become_empty_values():
    event = HookEvent.from_payload(
        {
            "session_id": "a",
            "hook_event_name": "Notification",
            "message": 123,
            "cwd": ["x"],
            "tool_input": "not a dict",
            "pid_chain": "1,2,3",
        }
    )
    assert event.message == ""
    assert event.cwd == ""
    assert event.tool_input == {}
    assert event.pid_chain == ()


def test_pid_chain_keeps_only_positive_ints_and_is_capped():
    event = HookEvent.from_payload(
        {
            "session_id": "a",
            "hook_event_name": "Stop",
            "pid_chain": [5, -1, 0, "7", True, 3.5, *range(100, 200)],
        }
    )
    assert event.pid_chain[:2] == (5, 100)  # -1, 0, "7", True and 3.5 are dropped
    assert len(event.pid_chain) == MAX_PID_CHAIN
