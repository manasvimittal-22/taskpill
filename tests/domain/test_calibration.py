import math

import pytest

from taskpill.domain.calibration import (
    MAX_SAMPLES,
    MIN_SAMPLES,
    TAU_RANGE,
    calibrated_config,
    is_measurable,
)
from taskpill.domain.progress import Progress, ProgressConfig


def test_too_few_tasks_keeps_the_default_curve():
    assert calibrated_config([40.0] * (MIN_SAMPLES - 1)) == ProgressConfig()


def test_worked_example_from_the_docstring():
    config = calibrated_config([20, 35, 40, 55, 90])
    assert config.tau_seconds == 40
    p = Progress(config)
    p.start(0)
    assert p.value(40) == pytest.approx(90 * (1 - math.exp(-1)))  # 57%, not 13%


def test_only_tau_changes():
    base = ProgressConfig(ceiling=80, cap=90, step_bump=2)
    config = calibrated_config([100] * 5, base)
    assert (config.ceiling, config.cap, config.step_bump) == (80, 90, 2)
    assert config.tau_seconds == 100


def test_tau_is_clamped():
    assert calibrated_config([6] * 5).tau_seconds == TAU_RANGE[0]
    assert calibrated_config([3000] * 5).tau_seconds == TAU_RANGE[1]


def test_one_odd_long_task_does_not_swing_it():
    # the median ignores the outlier; a mean would be ~700 s
    assert calibrated_config([30, 30, 30, 30, 3000]).tau_seconds == 30


def test_unmeasurable_durations_are_ignored():
    # 3 s (a quick answer) and 10 000 s (left running) don't count as samples
    assert calibrated_config([3, 10_000, 60, 60, 60, 60]) == ProgressConfig()
    assert not is_measurable(3) and not is_measurable(10_000) and is_measurable(60)


def test_only_the_most_recent_tasks_count():
    old = [900.0] * MAX_SAMPLES
    recent = [40.0] * MAX_SAMPLES
    assert calibrated_config(old + recent).tau_seconds == 40


def test_calibrated_curve_is_still_valid_and_monotonic():
    config = calibrated_config([45] * 5)
    p = Progress(config)
    p.start(0)
    values = [p.value(t) for t in range(0, 600, 10)]
    assert values == sorted(values)
    assert values[-1] <= config.cap
