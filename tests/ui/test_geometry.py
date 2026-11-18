import math

import pytest

from taskpill.ui import geometry as g


def test_pill_width_and_morph_are_inverse():
    for m in (0.0, 0.25, 0.5, 1.0):
        assert g.morph_of(g.pill_width(m)) == pytest.approx(m)
    assert g.pill_width(-1) == g.CIRCLE_WIDTH
    assert g.pill_width(2) == g.FULL_WIDTH


@pytest.mark.parametrize(
    ("needs_you", "collapsed", "expand", "expected"),
    [
        (False, False, True, g.FULL_WIDTH),
        (False, True, True, g.CIRCLE_WIDTH),
        (True, False, True, g.WIDE_WIDTH),
        (True, True, True, g.WIDE_WIDTH),  # a needs-you circle widens
        (True, True, False, g.CIRCLE_WIDTH),  # unless that setting is off
        (True, False, False, g.FULL_WIDTH),
    ],
)
def test_target_width(needs_you, collapsed, expand, expected):
    assert g.target_width(needs_you, collapsed, expand) == expected


def test_row_layout_right_anchor_packs_against_the_right_margin():
    widths = [32.0, 32.0, 32.0]
    container = g.window_width(widths)
    xs = g.layout_row(widths, g.Anchor.RIGHT, container)
    assert xs[0] == pytest.approx(g.MARGIN)
    assert xs[-1] + widths[-1] == pytest.approx(container - g.MARGIN)
    assert xs[1] - xs[0] == pytest.approx(32 + g.GAP)


def test_row_layout_right_anchor_in_a_wider_container_stays_right():
    xs = g.layout_row([100.0], g.Anchor.RIGHT, 500)
    assert xs[0] + 100 == pytest.approx(500 - g.MARGIN)


def test_row_layout_center():
    xs = g.layout_row([100.0, 50.0], g.Anchor.CENTER, 400)
    total = 150 + g.GAP
    assert xs[0] == pytest.approx((400 - total) / 2)


def test_empty_row():
    assert g.row_width([]) == 0
    assert g.layout_row([], g.Anchor.RIGHT, 100) == []


def test_capsule_length_of_a_circle_is_its_circumference():
    assert g.capsule_length(32, 32) == pytest.approx(math.pi * 32)


@pytest.mark.parametrize(
    ("fraction", "expected"),
    [
        (0.0, (116.0, 0.0)),  # top center
        (1.0, (116.0, 0.0)),  # all the way round
    ],
)
def test_capsule_point_start_and_end(fraction, expected):
    assert g.capsule_point(232, 32, fraction) == pytest.approx(expected)


def test_capsule_point_goes_clockwise_through_the_right_cap_then_the_bottom():
    w, h = 232, 32
    length = g.capsule_length(w, h)
    half_top = (w - h) / 2
    # just past the top-right straight part: on the right cap, moving down
    x, y = g.capsule_point(w, h, (half_top + 1) / length)
    assert x > w - h / 2 and y < h / 2
    # halfway round: bottom center
    assert g.capsule_point(w, h, 0.5) == pytest.approx((w / 2, h))


def test_capsule_points_stay_on_the_shape():
    w, h = 232, 32
    r = h / 2
    for i in range(200):
        x, y = g.capsule_point(w, h, i / 200)
        if r <= x <= w - r:
            assert y == pytest.approx(0) or y == pytest.approx(h)
        else:
            cx = r if x < r else w - r
            assert math.hypot(x - cx, y - r) == pytest.approx(r)


def test_polyline_is_empty_at_zero_and_closes_at_one():
    assert g.capsule_polyline(232, 32, 0) == []
    points = g.capsule_polyline(232, 32, 1.0)
    assert points[0] == pytest.approx(points[-1])


def test_polyline_respects_inset():
    points = g.capsule_polyline(232, 32, 0.5, inset=2)
    assert points[0] == pytest.approx((116, 2))
    assert all(2 - 1e-6 <= y <= 30 + 1e-6 for _, y in points)


def test_notification_dot_sits_on_the_right_cap():
    x, y = g.notification_dot_center(232, 32)
    assert math.hypot(x - (232 - 16), y - 16) == pytest.approx(16)
    assert x > 232 - 16 and y < 16  # upper right


@pytest.mark.parametrize(
    ("room", "count", "expected"),
    [
        (None, 1, g.WIDE_WIDTH),
        (1000, 1, g.WIDE_WIDTH),
        (280, 1, 280 - 2 * g.MARGIN),
        (100, 1, g.FULL_WIDTH),  # never narrower than a normal pill
        (320, 3, g.FULL_WIDTH),  # two circles take room too
    ],
)
def test_fit_wide(room, count, expected):
    assert g.fit_wide(room, count) == pytest.approx(expected)
