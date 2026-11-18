from taskpill.domain.session import STALE_AFTER_SECONDS, Session, SessionState
from tests.conftest import make_event


def new_session() -> Session:
    return Session("s1", now=0)


def test_new_session_is_hidden_idle():
    s = new_session()
    assert s.state is SessionState.IDLE
    assert not s.is_visible


def test_session_start_registers_without_showing():
    s = new_session()
    changed = s.apply(make_event("SessionStart", cwd="C:\\code\\taskpill"), 1)
    assert not changed
    assert s.state is SessionState.IDLE
    assert s.project_name == "taskpill"


def test_full_happy_path():
    s = new_session()
    assert s.apply(make_event("UserPromptSubmit", prompt="Fix the login bug"), 0)
    assert s.state is SessionState.WORKING
    assert s.prompt == "Fix the login bug"
    assert s.step == "Thinking"

    s.apply(make_event("PreToolUse", tool_name="Edit", tool_input={"file_path": "a.py"}), 5)
    assert s.step == "Editing a.py"
    s.apply(make_event("PostToolUse", tool_name="Edit", tool_input={"file_path": "a.py"}), 6)
    assert s.progress.steps == 1

    assert s.apply(make_event("Stop"), 60)
    assert s.state is SessionState.DONE
    assert s.progress.percent(60) == 100


def test_only_post_tool_use_bumps_progress():
    s = new_session()
    s.apply(make_event("UserPromptSubmit"), 0)
    s.apply(make_event("PreToolUse", tool_name="Bash"), 1)
    assert s.progress.steps == 0
    s.apply(make_event("PostToolUse", tool_name="Bash"), 2)
    assert s.progress.steps == 1


def test_notification_while_working_needs_you_and_pauses():
    s = new_session()
    s.apply(make_event("UserPromptSubmit"), 0)
    assert s.apply(make_event("Notification", message="Needs permission to run npm install"), 30)
    assert s.state is SessionState.NEEDS_YOU
    assert s.message == "Needs permission to run npm install"
    assert s.progress.active_seconds(600) == 30  # clock paused while waiting


def test_notification_without_message_gets_a_default():
    s = new_session()
    s.apply(make_event("UserPromptSubmit"), 0)
    s.apply(make_event("Notification"), 1)
    assert s.message == "Needs your input"


def test_tool_event_after_needs_you_resumes_working():
    s = new_session()
    s.apply(make_event("UserPromptSubmit"), 0)
    s.apply(make_event("Notification", message="permission"), 10)
    s.apply(make_event("PostToolUse", tool_name="Bash", tool_input={"command": "ls"}), 50)
    assert s.state is SessionState.WORKING
    assert s.message == ""
    assert s.progress.active_seconds(60) == 20  # 10 before the pause + 10 after


def test_idle_notification_does_not_replace_done():
    # Claude Code sends "Claude is waiting for your input" after a finished turn.
    s = new_session()
    s.apply(make_event("UserPromptSubmit"), 0)
    s.apply(make_event("Stop"), 10)
    assert not s.apply(make_event("Notification", message="waiting for your input"), 70)
    assert s.state is SessionState.DONE


def test_notification_on_idle_session_is_ignored():
    s = new_session()
    assert not s.apply(make_event("Notification", message="hi"), 1)
    assert s.state is SessionState.IDLE


def test_acknowledge_hides_done():
    s = new_session()
    s.apply(make_event("UserPromptSubmit"), 0)
    s.apply(make_event("Stop"), 10)
    assert s.acknowledge()
    assert s.state is SessionState.IDLE
    assert not s.is_visible


def test_acknowledge_only_works_on_done():
    s = new_session()
    s.apply(make_event("UserPromptSubmit"), 0)
    assert not s.acknowledge()
    assert s.state is SessionState.WORKING


def test_second_stop_is_not_a_change():
    s = new_session()
    s.apply(make_event("UserPromptSubmit"), 0)
    assert s.apply(make_event("Stop"), 1)
    assert not s.apply(make_event("Stop"), 2)


def test_tool_event_on_unknown_prompt_starts_working():
    # The app launched mid-task: no UserPromptSubmit was seen.
    s = new_session()
    s.apply(make_event("PreToolUse", tool_name="Read", tool_input={"file_path": "x.md"}), 100)
    assert s.state is SessionState.WORKING
    assert s.progress.percent(100) == 0


def test_tool_event_after_done_starts_a_fresh_estimate():
    s = new_session()
    s.apply(make_event("UserPromptSubmit"), 0)
    s.apply(make_event("Stop"), 10)
    s.apply(make_event("PreToolUse", tool_name="Bash"), 20)
    assert s.state is SessionState.WORKING
    assert s.progress.percent(20) == 0


def test_session_start_mid_task_does_not_reset():
    # SessionStart also fires on resume / after compaction.
    s = new_session()
    s.apply(make_event("UserPromptSubmit", prompt="big job"), 0)
    s.apply(make_event("SessionStart"), 100)
    assert s.state is SessionState.WORKING
    assert s.prompt == "big job"


def test_new_prompt_after_done_restarts():
    s = new_session()
    s.apply(make_event("UserPromptSubmit", prompt="one"), 0)
    s.apply(make_event("Stop"), 10)
    s.apply(make_event("UserPromptSubmit", prompt="two"), 20)
    assert s.state is SessionState.WORKING
    assert s.prompt == "two"
    assert s.progress.percent(20) == 0


def test_stale_only_while_working_and_silent():
    s = new_session()
    s.apply(make_event("UserPromptSubmit"), 0)
    assert not s.is_stale(STALE_AFTER_SECONDS - 1)
    assert s.is_stale(STALE_AFTER_SECONDS)
    s.apply(make_event("Stop"), STALE_AFTER_SECONDS)
    assert not s.is_stale(STALE_AFTER_SECONDS * 10)


def test_cwd_and_pid_chain_are_remembered():
    s = new_session()
    s.apply(make_event("SessionStart", cwd="/Users/m/proj/", pid_chain=[10, 9]), 0)
    s.apply(make_event("UserPromptSubmit"), 1)  # no cwd / pids: keep the old ones
    assert s.project_name == "proj"
    assert s.pid_chain == (10, 9)


def test_project_name_fallback():
    assert new_session().project_name == "Claude Code"


# ---- rules from the Claude Code hooks docs (2026-11) ----------------------


def working_session() -> Session:
    s = new_session()
    s.apply(make_event("UserPromptSubmit"), 0)
    return s


def test_permission_request_needs_you_right_away_with_a_clear_message():
    s = working_session()
    changed = s.apply(
        make_event("PermissionRequest", tool_name="Bash", tool_input={"command": "npm install"}),
        5,
    )
    assert changed
    assert s.state is SessionState.NEEDS_YOU
    assert s.message == "Needs permission to run npm install"


def test_later_permission_prompt_notification_keeps_the_specific_message():
    s = working_session()
    s.apply(make_event("PermissionRequest", tool_name="Edit", tool_input={"file_path": "a.py"}), 5)
    changed = s.apply(
        make_event(
            "Notification",
            notification_type="permission_prompt",
            message="Claude needs your permission to use Edit",
        ),
        11,
    )
    assert not changed
    assert s.message == "Needs permission to edit a.py"


def test_permission_prompt_notification_alone_still_needs_you():
    s = working_session()
    s.apply(make_event("Notification", notification_type="permission_prompt", message="Allow?"), 6)
    assert s.state is SessionState.NEEDS_YOU
    assert s.message == "Allow?"


def test_ask_user_question_needs_you_until_answered():
    s = working_session()
    s.apply(make_event("PreToolUse", tool_name="AskUserQuestion"), 5)
    assert s.state is SessionState.NEEDS_YOU
    assert s.message == "Has a question for you"
    s.apply(make_event("PostToolUse", tool_name="AskUserQuestion"), 40)
    assert s.state is SessionState.WORKING
    assert s.progress.active_seconds(40) == 5  # paused while waiting for the answer


def test_exit_plan_mode_needs_you():
    s = working_session()
    s.apply(make_event("PreToolUse", tool_name="ExitPlanMode"), 5)
    assert s.message == "Plan ready for your review"


def test_idle_prompt_while_working_means_interrupted_and_hides():
    # Esc sends no Stop; idle_prompt arrives later.
    s = working_session()
    assert s.apply(make_event("Notification", notification_type="idle_prompt"), 70)
    assert s.state is SessionState.IDLE
    assert not s.is_visible


def test_idle_prompt_after_done_keeps_done():
    s = working_session()
    s.apply(make_event("Stop"), 10)
    assert not s.apply(make_event("Notification", notification_type="idle_prompt"), 70)
    assert s.state is SessionState.DONE


def test_other_notification_types_are_ignored():
    s = working_session()
    kinds = ["auth_success", "agent_completed", "quota_auto_resume_fired", "plugin_notification"]
    for kind in kinds:
        assert not s.apply(make_event("Notification", notification_type=kind, message="x"), 1)
    assert s.state is SessionState.WORKING


def test_elicitation_needs_you():
    s = working_session()
    event = make_event("Notification", notification_type="elicitation_dialog", message="MCP asks")
    s.apply(event, 3)
    assert s.state is SessionState.NEEDS_YOU


def test_stop_failure_finishes_with_an_error_step():
    s = working_session()
    assert s.apply(make_event("StopFailure"), 9)
    assert s.state is SessionState.DONE
    assert s.step == "Stopped with an error"


def test_permission_request_on_idle_session_starts_working_then_needs_you():
    s = new_session()
    s.apply(make_event("PermissionRequest", tool_name="Write", tool_input={"file_path": "b.md"}), 1)
    assert s.state is SessionState.NEEDS_YOU
    assert s.message == "Needs permission to write b.md"


def test_task_started_at_tracks_the_current_task():
    s = new_session()
    s.apply(make_event("UserPromptSubmit"), 100)
    assert s.task_started_at == 100
    s.apply(make_event("Stop"), 150)
    s.apply(make_event("PreToolUse", tool_name="Bash"), 200)  # carried on after Stop
    assert s.task_started_at == 200
