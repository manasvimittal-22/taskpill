import pytest

from taskpill.domain.session import SessionState
from taskpill.services.session_store import FORGET_IDLE_AFTER_SECONDS, SessionStore
from tests.conftest import make_event


@pytest.fixture
def store(clock):
    return SessionStore(clock)


def collect(store):
    changed, removed = [], []
    store.on_changed(lambda s: changed.append((s.session_id, s.state)))
    store.on_removed(removed.append)
    return changed, removed


def test_creates_sessions_on_first_event(store):
    store.apply(make_event("SessionStart", "a"))
    assert store.get("a") is not None
    assert store.visible() == []


def test_longest_waiting_is_the_session_that_needed_you_first(store, clock):
    store.apply(make_event("UserPromptSubmit", "a"))
    store.apply(make_event("UserPromptSubmit", "b"))
    store.apply(make_event("PermissionRequest", "b", tool_name="Bash", tool_input={}))
    clock.advance(30)
    store.apply(make_event("PermissionRequest", "a", tool_name="Bash", tool_input={}))
    assert store.longest_waiting().session_id == "b"
    # a repeated prompt for the same session doesn't restart its wait
    clock.advance(30)
    store.apply(make_event("Notification", "b", notification_type="agent_needs_input"))
    assert store.longest_waiting().session_id == "b"


def test_longest_waiting_ignores_sessions_that_do_not_need_you(store):
    assert store.longest_waiting() is None
    store.apply(make_event("UserPromptSubmit", "a"))
    store.apply(make_event("UserPromptSubmit", "b"))
    store.apply(make_event("Stop", "b"))
    assert store.longest_waiting() is None


def test_the_wait_starts_again_after_answering(store, clock):
    store.apply(make_event("UserPromptSubmit", "a"))
    store.apply(make_event("PermissionRequest", "a", tool_name="Bash", tool_input={}))
    store.apply(make_event("UserPromptSubmit", "b"))
    clock.advance(10)
    store.apply(make_event("PermissionRequest", "b", tool_name="Bash", tool_input={}))
    clock.advance(10)
    store.apply(make_event("PostToolUse", "a", tool_name="Bash"))  # a answered, works again
    clock.advance(10)
    store.apply(make_event("PermissionRequest", "a", tool_name="Bash", tool_input={}))
    assert store.longest_waiting().session_id == "b"


def test_notifies_only_on_visible_changes(store):
    changed, _ = collect(store)
    store.apply(make_event("SessionStart", "a"))
    store.apply(make_event("UserPromptSubmit", "a"))
    store.apply(make_event("Stop", "a"))
    store.apply(make_event("Stop", "a"))
    assert changed == [("a", SessionState.WORKING), ("a", SessionState.DONE)]


def test_session_end_removes_and_notifies(store):
    _, removed = collect(store)
    store.apply(make_event("UserPromptSubmit", "a"))
    assert store.apply(make_event("SessionEnd", "a")) is None
    assert store.get("a") is None
    assert removed == ["a"]


def test_session_end_for_unknown_session_is_quiet(store):
    _, removed = collect(store)
    store.apply(make_event("SessionEnd", "ghost"))
    assert removed == []
    assert store.all() == []


def test_visible_keeps_creation_order(store, clock):
    for sid in ["first", "second", "third"]:
        store.apply(make_event("UserPromptSubmit", sid))
        clock.advance(1)
    store.apply(make_event("Notification", "first", message="permission"))
    assert [s.session_id for s in store.visible()] == ["first", "second", "third"]


def test_multiple_sessions_are_independent(store):
    store.apply(make_event("UserPromptSubmit", "a"))
    store.apply(make_event("UserPromptSubmit", "b"))
    store.apply(make_event("Stop", "a"))
    assert store.get("a").state is SessionState.DONE
    assert store.get("b").state is SessionState.WORKING


def test_acknowledge(store):
    changed, _ = collect(store)
    store.apply(make_event("UserPromptSubmit", "a"))
    store.apply(make_event("Stop", "a"))
    assert store.acknowledge("a")
    assert changed[-1] == ("a", SessionState.IDLE)
    assert not store.acknowledge("a")
    assert not store.acknowledge("missing")


def test_has_active(store):
    assert not store.has_active()
    store.apply(make_event("UserPromptSubmit", "a"))
    assert store.has_active()
    store.apply(make_event("Stop", "a"))
    assert store.has_active()  # Done stays on screen until clicked
    store.acknowledge("a")
    assert not store.has_active()


def test_prune_forgets_only_old_hidden_sessions(store, clock):
    _, removed = collect(store)
    store.apply(make_event("SessionStart", "old_idle"))
    store.apply(make_event("UserPromptSubmit", "old_working"))
    clock.advance(FORGET_IDLE_AFTER_SECONDS)
    store.apply(make_event("SessionStart", "fresh"))
    assert store.prune() == ["old_idle"]
    assert removed == ["old_idle"]
    assert store.get("old_working") is not None
    assert store.get("fresh") is not None


def test_cap_evicts_hidden_before_visible(clock):
    store = SessionStore(clock, max_sessions=3)
    _, removed = collect(store)
    store.apply(make_event("UserPromptSubmit", "busy1"))
    clock.advance(1)
    store.apply(make_event("SessionStart", "hidden"))
    clock.advance(1)
    store.apply(make_event("UserPromptSubmit", "busy2"))
    clock.advance(1)
    store.apply(make_event("UserPromptSubmit", "new"))
    assert removed == ["hidden"]
    assert len(store.all()) == 3


def test_cap_evicts_oldest_when_all_visible(clock):
    store = SessionStore(clock, max_sessions=2)
    store.apply(make_event("UserPromptSubmit", "a"))
    clock.advance(1)
    store.apply(make_event("UserPromptSubmit", "b"))
    clock.advance(1)
    store.apply(make_event("UserPromptSubmit", "a"))  # a heard from again
    clock.advance(1)
    store.apply(make_event("UserPromptSubmit", "c"))
    assert {s.session_id for s in store.all()} == {"a", "c"}


def test_max_sessions_must_be_positive(clock):
    with pytest.raises(ValueError):
        SessionStore(clock, max_sessions=0)


def test_every_listener_is_called(store):
    first, second = [], []
    store.on_changed(lambda s: first.append(s.session_id))
    store.on_changed(lambda s: second.append(s.session_id))
    store.apply(make_event("UserPromptSubmit", "a"))
    assert first == second == ["a"]
