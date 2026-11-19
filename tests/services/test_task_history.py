import pytest

from taskpill.domain.calibration import MAX_SAMPLES, MIN_SAMPLES
from taskpill.domain.progress import ProgressConfig
from taskpill.services.session_store import SessionStore
from taskpill.services.task_history import TaskHistory
from tests.conftest import make_event


class MemoryStore:
    def __init__(self, durations=None, fail=False):
        self.durations = list(durations or [])
        self.fail = fail

    def load(self):
        return list(self.durations)

    def save(self, durations):
        if self.fail:
            raise OSError("disk full")
        self.durations = list(durations)


def run_task(store, clock, seconds, sid="a", end="Stop"):
    store.apply(make_event("UserPromptSubmit", sid))
    clock.advance(seconds)
    store.apply(make_event(end, sid, **({"error": "server_error"} if end == "StopFailure" else {})))


def test_history_starts_from_the_saved_durations():
    history = TaskHistory(MemoryStore([40.0] * MIN_SAMPLES))
    assert history.progress_config().tau_seconds == 40


def test_record_saves_and_recalibrates():
    mem = MemoryStore()
    history = TaskHistory(mem)
    for _ in range(MIN_SAMPLES):
        history.record(60)
    assert mem.durations == [60.0] * MIN_SAMPLES
    assert history.progress_config().tau_seconds == 60


def test_record_ignores_unmeasurable_and_keeps_only_recent():
    mem = MemoryStore()
    history = TaskHistory(mem)
    history.record(1)
    history.record(99_999)
    assert mem.durations == []
    for i in range(MAX_SAMPLES + 5):
        history.record(10 + i)
    assert len(mem.durations) == MAX_SAMPLES


def test_a_failing_save_never_raises():
    history = TaskHistory(MemoryStore(fail=True))
    history.record(60)  # must not raise


def test_normal_stop_teaches_the_curve(clock):
    history = TaskHistory(MemoryStore())
    store = SessionStore(clock, task_history=history)
    for _ in range(MIN_SAMPLES):
        run_task(store, clock, 50)
    assert history.progress_config().tau_seconds == 50


def test_failures_interrupts_and_mid_task_joins_do_not_teach(clock):
    mem = MemoryStore()
    store = SessionStore(clock, task_history=TaskHistory(mem))
    run_task(store, clock, 50, "a", end="StopFailure")
    # interrupted with Esc: idle_prompt, no Stop
    store.apply(make_event("UserPromptSubmit", "b"))
    clock.advance(50)
    store.apply(make_event("Notification", "b", notification_type="idle_prompt"))
    # we joined mid-task: no prompt seen, only a tool event
    store.apply(make_event("PostToolUse", "c", tool_name="Read"))
    clock.advance(50)
    store.apply(make_event("Stop", "c"))
    assert mem.durations == []


def test_time_waiting_for_you_is_not_counted(clock):
    mem = MemoryStore()
    store = SessionStore(clock, task_history=TaskHistory(mem))
    store.apply(make_event("UserPromptSubmit", "a"))
    clock.advance(20)
    ask = make_event("PermissionRequest", "a", tool_name="Bash", tool_input={"command": "ls"})
    store.apply(ask)
    clock.advance(600)  # away from the desk
    store.apply(make_event("PostToolUse", "a", tool_name="Bash"))
    clock.advance(10)
    store.apply(make_event("Stop", "a"))
    assert mem.durations == [pytest.approx(30)]


def test_a_second_stop_is_not_counted_twice(clock):
    mem = MemoryStore()
    store = SessionStore(clock, task_history=TaskHistory(mem))
    run_task(store, clock, 30)
    store.apply(make_event("Stop", "a"))
    assert len(mem.durations) == 1


def test_curve_changes_only_at_the_next_prompt(clock):
    history = TaskHistory(MemoryStore([40.0] * MIN_SAMPLES))
    store = SessionStore(clock, task_history=history)
    store.apply(make_event("UserPromptSubmit", "a"))
    session = store.get("a")
    clock.advance(40)
    before = session.progress.value(clock.now())
    history.record(900)  # another session finishes a long task mid-way
    assert session.progress.value(clock.now()) == before
    store.apply(make_event("Stop", "a"))
    store.apply(make_event("UserPromptSubmit", "a"))
    assert session.progress.value(clock.now()) == 0


def test_without_history_the_default_curve_is_used(clock):
    store = SessionStore(clock)
    store.apply(make_event("UserPromptSubmit", "a"))
    assert store.get("a").progress._config == ProgressConfig()
