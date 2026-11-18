import math

import pytest

from taskpill.domain.progress import Progress, ProgressConfig


def test_starts_at_zero():
    p = Progress()
    p.start(0)
    assert p.value(0) == 0
    assert p.percent(0) == 0


def test_worked_example_from_the_docstring():
    # 4 minutes and 12 tool steps → 90·(1−e^−1) + 12 ≈ 68.9 → 68%
    p = Progress()
    p.start(0)
    for _ in range(12):
        p.bump()
    assert p.value(240) == pytest.approx(90 * (1 - math.exp(-1)) + 12)
    assert p.percent(240) == 68


def test_never_reaches_100_before_complete():
    p = Progress()
    p.start(0)
    for _ in range(500):
        p.bump()
    assert p.value(10**9) == 95
    assert p.percent(10**9) == 95


def test_complete_is_100():
    p = Progress()
    p.start(0)
    p.complete(30)
    assert p.is_complete
    assert p.value(30) == 100
    assert p.percent(10_000) == 100


def test_value_never_goes_down_over_time():
    p = Progress()
    p.start(0)
    values = []
    for t in range(0, 3600, 7):
        if t % 70 == 0:
            p.bump()
        values.append(p.value(t))
    assert values == sorted(values)


def test_pause_stops_the_clock():
    p = Progress()
    p.start(0)
    p.pause(60)
    before = p.value(60)
    assert p.value(600) == before  # paused for 9 minutes: no change
    p.resume(600)
    assert p.active_seconds(660) == pytest.approx(120)


def test_pause_and_resume_twice_is_safe():
    p = Progress()
    p.start(0)
    p.pause(10)
    p.pause(20)
    p.resume(30)
    p.resume(40)
    assert p.active_seconds(50) == pytest.approx(30)


def test_no_bumps_or_resume_after_complete():
    p = Progress()
    p.start(0)
    p.complete(10)
    p.bump()
    p.resume(20)
    assert p.steps == 0
    assert p.value(1000) == 100


def test_start_resets_everything():
    p = Progress()
    p.start(0)
    p.bump()
    p.complete(100)
    p.start(200)
    assert not p.is_complete
    assert p.steps == 0
    assert p.value(200) == 0


def test_clock_going_backwards_never_gives_negative_time():
    p = Progress()
    p.start(100)
    assert p.active_seconds(50) == 0
    assert p.value(50) == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tau_seconds": 0},
        {"tau_seconds": -5},
        {"ceiling": 96, "cap": 95},
        {"cap": 100},
        {"ceiling": -1},
        {"step_bump": -1},
    ],
)
def test_bad_config_is_rejected(kwargs):
    with pytest.raises(ValueError):
        ProgressConfig(**kwargs)
