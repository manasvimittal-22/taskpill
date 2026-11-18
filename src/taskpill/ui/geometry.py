"""Sizes, row layout and capsule-edge math. Pure: no Qt, so it is easy to test.

Sizes are in logical pixels (Qt scales them for DPI).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

HEIGHT = 32.0
FULL_WIDTH = 232.0
WIDE_WIDTH = 320.0  # a needs-you pill grows so the whole message fits
CIRCLE_WIDTH = HEIGHT
GAP = 6.0
MARGIN = 10.0  # room around the row inside the window for the glow

MIN_WIDTH, MAX_WIDTH = 180.0, 400.0  # resize limits (settings_store has the same)
# ... or a circle: dragging narrower than halfway between the circle and MIN_WIDTH
# snaps the pill to a circle (Manasvi, 2026-11-17).
MIN_HEIGHT, MAX_HEIGHT = 26.0, 44.0
WIDE_EXTRA = WIDE_WIDTH - FULL_WIDTH  # a needs-you pill is this much wider than a full one


@dataclass(frozen=True)
class Dims:
    """The pill's size, which the user can change in resize mode.

    Everything else follows: circles are as wide as the pill is tall, a
    needs-you pill is 88 px wider, and text scales with the height.

    ``width == height`` is a *circle pill*: even a lone working session shows
    as a circle with its %, and only a needs-you message widens it.
    """

    width: float = FULL_WIDTH
    height: float = HEIGHT

    def __post_init__(self) -> None:
        object.__setattr__(self, "height", clamp_height(self.height))
        object.__setattr__(self, "width", clamp_width(self.width, self.height))

    @property
    def full(self) -> float:
        return self.width

    @property
    def circle(self) -> float:
        return self.height

    @property
    def is_circle(self) -> bool:
        return self.width <= self.height

    @property
    def wide(self) -> float:
        return WIDE_WIDTH if self.is_circle else self.width + WIDE_EXTRA

    @property
    def text_width(self) -> float:
        """The width at which a pill shows its full text (for the morph). A circle
        pill that widens for a message reads as a full pill from MIN_WIDTH."""
        return MIN_WIDTH if self.is_circle else self.width

    @property
    def scale(self) -> float:
        """Text and padding scale: 1.0 at the default 32 px height."""
        return self.height / HEIGHT


def clamp_width(width: float, height: float = HEIGHT) -> float:
    """MIN_WIDTH..MAX_WIDTH, or exactly ``height`` (a circle) when it is closer to
    a circle than to the narrowest pill."""
    width = float(width)
    if width < (MIN_WIDTH + height) / 2:
        return float(height)
    return max(MIN_WIDTH, min(MAX_WIDTH, width))


def clamp_height(height: float) -> float:
    return max(MIN_HEIGHT, min(MAX_HEIGHT, float(height)))


DEFAULT = Dims()


def window_height() -> float:
    """The row window is always tall enough for the tallest pill, so changing the
    height never resizes the window."""
    return MAX_HEIGHT + 2 * MARGIN


class Anchor(Enum):
    RIGHT = "right"  # Windows: the row grows to the left from the "^" arrow
    CENTER = "center"  # macOS: centered under the menu bar


def pill_width(morph: float, full: float | None = None, dims: Dims = DEFAULT) -> float:
    """0 = circle, 1 = full pill (``full`` wide)."""
    morph = max(0.0, min(1.0, morph))
    full = dims.full if full is None else full
    return dims.circle + (full - dims.circle) * morph


def morph_of(width: float, dims: Dims = DEFAULT) -> float:
    """How far a pill of this width is from a circle (0) to a full pill (1)."""
    span = dims.full - dims.circle
    return max(0.0, min(1.0, (width - dims.circle) / span)) if span > 0 else 1.0


def target_width(
    needs_you: bool,
    collapsed: bool,
    expand_needs_you: bool = True,
    wide: float | None = None,
    *,
    done: bool = False,
    dims: Dims = DEFAULT,
) -> float:
    """Where a pill should end up.

    One session: a full pill. Two or more: circles. A finished session shrinks
    to a circle too (Manasvi, 2026-11-17). A session that needs you is wide in
    every case (if that setting is on), so the message fits.
    """
    if needs_you and expand_needs_you:
        return dims.wide if wide is None else wide
    if done or collapsed:
        return dims.circle
    return dims.full


def fit_wide(room: float | None, count: int, dims: Dims = DEFAULT) -> float:
    """How wide a needs-you pill may get without covering the taskbar's app icons.

    ``room`` is the free width next to the anchor (None = unknown, no limit).
    The other pills are circles. Never narrower than a normal full pill.
    """
    if room is None:
        return dims.wide
    others = max(0, count - 1) * (dims.circle + GAP)
    available = room - others - 2 * MARGIN
    return max(dims.full, min(dims.wide, available))


def row_width(widths: list[float]) -> float:
    if not widths:
        return 0.0
    return sum(widths) + GAP * (len(widths) - 1)


def window_width(widths: list[float]) -> float:
    return row_width(widths) + 2 * MARGIN


def layout_row(widths: list[float], anchor: Anchor, container_width: float) -> list[float]:
    """Left x of each pill inside a container, keeping the order given (oldest first).

    RIGHT: the newest pill sits next to the anchor on the right, so older pills
    move left when a new one arrives.
    """
    total = row_width(widths)
    if anchor is Anchor.RIGHT:
        x = container_width - MARGIN - total
    else:
        x = (container_width - total) / 2
    xs = []
    for w in widths:
        xs.append(x)
        x += w + GAP
    return xs


def capsule_length(width: float, height: float) -> float:
    r = height / 2
    straight = max(0.0, width - height)
    return 2 * straight + 2 * math.pi * r


def capsule_point(width: float, height: float, fraction: float) -> tuple[float, float]:
    """Point on the capsule's edge, ``fraction`` of the way round.

    Starts at the top center and goes clockwise (screen coordinates, y down),
    like the progress line. Works for circles too (width == height).
    """
    r = height / 2
    straight = max(0.0, width - height)
    half_top = straight / 2
    arc = math.pi * r
    d = (fraction % 1.0) * capsule_length(width, height)
    cx_left, cx_right, cy = r, r + straight, r

    if d <= half_top:  # top edge, center → right
        return (width / 2 + d, 0.0)
    d -= half_top
    if d <= arc:  # right cap, top → bottom
        a = -math.pi / 2 + d / r
        return (cx_right + r * math.cos(a), cy + r * math.sin(a))
    d -= arc
    if d <= straight:  # bottom edge, right → left
        return (cx_right - d, height)
    d -= straight
    if d <= arc:  # left cap, bottom → top
        a = math.pi / 2 + d / r
        return (cx_left + r * math.cos(a), cy + r * math.sin(a))
    d -= arc
    return (cx_left + d, 0.0)  # top edge, left → center


def capsule_polyline(
    width: float, height: float, fraction: float, inset: float = 0.0, step: float = 2.0
) -> list[tuple[float, float]]:
    """Points along the edge from the start to ``fraction``, about ``step`` px apart.

    ``inset`` moves the line inward so a thick stroke stays inside the shape.
    """
    fraction = max(0.0, min(1.0, fraction))
    w, h = width - 2 * inset, height - 2 * inset
    if fraction == 0 or w <= 0 or h <= 0:
        return []
    count = max(2, math.ceil(capsule_length(w, h) * fraction / step) + 1)
    points = []
    for i in range(count):
        x, y = capsule_point(w, h, fraction * i / (count - 1))
        points.append((x + inset, y + inset))
    return points


def notification_dot_center(width: float, height: float) -> tuple[float, float]:
    """The needs-you dot sits on the edge at the top-right "corner" (45° on the right cap)."""
    r = height / 2
    straight = max(0.0, width - height)
    a = -math.pi / 4
    return (r + straight + r * math.cos(a), r + r * math.sin(a))
