import pytest

from taskpill.ui import motion


def test_animated_eases_to_its_target():
    a = motion.Animated(0.0, duration=0.2)
    a.set(1.0, now=10.0)
    assert a.value(10.0) == 0.0
    assert 0.0 < a.value(10.1) < 1.0
    assert a.value(10.2) == 1.0
    assert a.running(10.1)
    assert not a.running(10.3)


def test_retarget_mid_way_starts_from_the_current_value():
    a = motion.Animated(0.0, duration=1.0)
    a.set(1.0, now=0.0)
    mid = a.value(0.5)
    a.set(0.0, now=0.5)
    assert a.value(0.5) == pytest.approx(mid)  # no jump


def test_same_target_does_not_restart():
    a = motion.Animated(0.0, duration=1.0)
    a.set(1.0, now=0.0)
    a.set(1.0, now=0.9)
    assert a.value(1.0) == 1.0


def test_instant():
    a = motion.Animated(0.0, duration=1.0)
    a.set(5.0, now=0.0, instant=True)
    assert a.value(0.0) == 5.0
    assert not a.running(0.0)


def test_shift_moves_start_and_target():
    a = motion.Animated(10.0, duration=1.0)
    a.set(20.0, now=0.0)
    before = a.value(0.5)
    a.shift(5)
    assert a.value(0.5) == pytest.approx(before + 5)
    assert a.target == 25


def test_glow_cycle():
    assert motion.glow(0.0, 0.0) == 0.0
    assert motion.glow(motion.GLOW_RISE, 0.0) == pytest.approx(1.0)
    assert motion.glow(motion.GLOW_RISE + motion.GLOW_FALL + 0.1, 0.0) == 0.0  # resting
    assert motion.glow(motion.GLOW_CYCLE + motion.GLOW_RISE, 0.0) == pytest.approx(1.0)
    for i in range(100):
        assert 0.0 <= motion.glow(i * 0.05, 0.0) <= 1.0


def test_easings_stay_in_range():
    for f in (motion.ease_out_cubic, motion.ease_in_out_sine):
        assert f(-1) == 0.0
        assert f(2) == pytest.approx(1.0)
