"""Draws one pill (full or circle, and everything in between) with QPainter.

Everything scales with the pill's height (the user can resize it): 12 px text
and 14 px padding at the default 32 px height.

Text sits on its optical center: the baseline is placed so the *cap height*
is centered in the pill. Centering the whole text box (ascent + descent) puts
letters a pixel or two low, which is what looked misaligned.

The look (docs/design.md → Polish): a small instrument lit from above. The
surface is a touch lighter at the top with a hairline of light on its rim, and
the progress is light running round the edge: its tail fades in from where it
started and its head carries a small bead of light, so you can see which way
it is going and where it is now.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QConicalGradient,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QRadialGradient,
)

from taskpill.ui import geometry as g
from taskpill.ui.theme import Palette, qcolor, rim_light, surface_light, tabular, ui_font
from taskpill.ui.view_model import PillKind, PillModel

EDGE_WIDTH = 2.25
PAD_X = 14.0  # at scale 1
GAP_X = 10.0  # between the name and the step, and before the %
TAIL_ALPHA = 0.32  # how faint the progress line is where it started
SIGN_SCALE = 0.78  # the % sign is smaller than the number, so the number leads


@dataclass(frozen=True)
class PillLook:
    """Animated values for one frame."""

    morph: float = 1.0  # 0 circle … 1 full pill
    opacity: float = 1.0
    edge: float = 0.0  # 0..1 of the way round
    glow: float = 0.0  # needs-you halo 0..1
    show_dot: bool = False
    show_glow: bool = True
    hovered: bool = False
    resizing: float = 0.0  # 0..1: resize mode fading in (brightens the outline)


class Fonts:
    """Fonts for one text scale. Use ``Fonts.for_height`` to share them."""

    def __init__(self, scale: float = 1.0) -> None:
        size = 12 * scale
        self.scale = scale
        self.title = ui_font(size, QFont.Weight.DemiBold)
        self.detail = ui_font(size)
        self.percent = tabular(ui_font(size, QFont.Weight.DemiBold))
        self.sign = ui_font(size * SIGN_SCALE, QFont.Weight.DemiBold)
        self.circle = tabular(ui_font(11 * scale, QFont.Weight.DemiBold))
        self.ask = ui_font(14 * scale, QFont.Weight.Bold)  # the "?" of a needs-you circle

    @staticmethod
    def for_height(height: float) -> Fonts:
        # Round to half a pixel so live resizing doesn't make a new font per frame.
        return _fonts(round(height * 2) / 2)


@lru_cache(maxsize=64)
def _fonts(height: float) -> Fonts:
    return Fonts(height / g.HEIGHT)


def paint_pill(
    p: QPainter, rect: QRectF, model: PillModel, look: PillLook, pal: Palette,
    fonts: Fonts | None = None,
) -> None:
    fonts = Fonts.for_height(rect.height()) if fonts is None or fonts.scale != (
        rect.height() / g.HEIGHT) else fonts
    p.save()
    p.setOpacity(max(0.0, min(1.0, look.opacity)))
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    radius = rect.height() / 2
    edge_color = pal.edge(model.kind)

    if model.kind is PillKind.NEEDS_YOU and look.show_glow and look.glow > 0:
        _paint_glow(p, rect, edge_color, look.glow)

    shape = QPainterPath()
    shape.addRoundedRect(rect, radius, radius)
    _paint_surface(p, rect, shape, pal)
    tint_alpha = {PillKind.DONE: 0.11, PillKind.NEEDS_YOU: 0.07,
                  PillKind.LIMITED: 0.08}.get(model.kind, 0.0)
    if tint_alpha:
        tint = QColor(edge_color)
        tint.setAlphaF(tint_alpha)
        p.fillPath(shape, tint)
    if look.hovered:
        lift = QColor(pal.text)
        lift.setAlphaF(0.05)
        p.fillPath(shape, lift)

    # the track (brighter in resize mode), then the progress line on top of it
    track = qcolor(pal.hairline)
    if look.resizing > 0:
        accent = QColor(pal.working)
        accent.setAlphaF(0.25 + 0.45 * look.resizing)
        track = accent
    p.setPen(QPen(track, 1.0 + 0.5 * look.resizing))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius - 0.5, radius - 0.5)
    _paint_rim(p, rect, radius, pal)

    fraction = 1.0 if model.kind is PillKind.NEEDS_YOU else look.edge
    # Out of usage: the line stops where the estimate froze, with no bead (nothing moves).
    _paint_edge(p, rect, fraction, edge_color, dim=model.kind is PillKind.STALE,
                bead=model.kind is PillKind.WORKING)

    # Cross-fade without overlap: the full text is gone before the number appears.
    full_alpha = _clamp((look.morph - 0.65) / 0.35)
    circle_alpha = _clamp((0.35 - look.morph) / 0.35)
    p.setClipPath(shape)
    base = max(0.0, min(1.0, look.opacity))
    if full_alpha > 0:
        p.setOpacity(base * full_alpha)
        _paint_full_text(p, rect, model, pal, fonts)
    if circle_alpha > 0:
        p.setOpacity(base * circle_alpha)
        _paint_circle_text(p, rect, model, pal, fonts)
    p.setOpacity(base)

    p.setClipping(False)
    if look.show_dot and model.kind is PillKind.NEEDS_YOU:
        _paint_dot(p, rect, edge_color, pal)

    p.restore()


# ---- pieces --------------------------------------------------------------------------
def baseline(fm: QFontMetricsF, center_y: float) -> float:
    """The y to draw text at so its capital letters are centered on ``center_y``."""
    return center_y + fm.capHeight() / 2


def _paint_edge(p: QPainter, rect: QRectF, fraction: float, color: QColor, dim: bool,
                bead: bool = True) -> None:
    if fraction <= 0:
        return
    inset = EDGE_WIDTH / 2
    points = g.capsule_polyline(rect.width(), rect.height(), fraction, inset=inset)
    if len(points) < 2:
        return
    line = QColor(color)
    if dim:
        line.setAlphaF(0.55)
    poly = QPolygonF([QPointF(rect.left() + x, rect.top() + y) for x, y in points])
    if fraction >= 1.0:  # a closed loop (done, needs you) is one even line
        p.setPen(_edge_pen(line))
        p.drawPolygon(poly)
        return
    head = poly[len(poly) - 1]
    p.setPen(_edge_pen(_tail_gradient(rect, head, line)))
    p.drawPolyline(poly)
    if bead and not dim:
        _paint_bead(p, head, line, rect.height() / g.HEIGHT)


def _edge_pen(brush) -> QPen:
    pen = QPen(brush, EDGE_WIDTH, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _tail_gradient(rect: QRectF, head: QPointF, color: QColor) -> QConicalGradient:
    """Faint where the line started (top center), full strength at its head.

    A conical gradient round the pill's center. Qt counts its stops
    counter-clockwise from the start angle, and the line runs clockwise from the
    top, so the start of the line is stop 1.0 and the head is ``1 - turn``.
    """
    center = rect.center()
    turn = (math.degrees(math.atan2(head.x() - center.x(), center.y() - head.y())) % 360) / 360
    faint = QColor(color)
    faint.setAlphaF(color.alphaF() * TAIL_ALPHA)
    gradient = QConicalGradient(center, 90.0)
    gradient.setColorAt(0.0, faint)  # just left of the start: only the start cap lands here
    gradient.setColorAt(min(max(1.0 - turn, 0.001), 0.999), color)
    gradient.setColorAt(1.0, faint)
    return gradient


def _paint_bead(p: QPainter, head: QPointF, color: QColor, s: float) -> None:
    """The bead of light at the head of the progress line."""
    halo = QRadialGradient(head, 6.0 * s)
    glow = QColor(color)
    glow.setAlphaF(0.5)
    halo.setColorAt(0.0, glow)
    glow.setAlphaF(0.0)
    halo.setColorAt(1.0, glow)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(halo)
    p.drawEllipse(head, 6.0 * s, 6.0 * s)
    p.setBrush(color.lighter(140))
    p.drawEllipse(head, 2.0 * s, 2.0 * s)


def _paint_surface(p: QPainter, rect: QRectF, shape: QPainterPath, pal: Palette) -> None:
    """The fill, lit softly from above."""
    top, bottom = surface_light(pal)
    light = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    light.setColorAt(0.0, top)
    light.setColorAt(1.0, bottom)
    p.fillPath(shape, light)


def _paint_rim(p: QPainter, rect: QRectF, radius: float, pal: Palette) -> None:
    """A hairline of light along the top inside edge, fading out by the middle."""
    color = rim_light(pal)
    if color.alpha() == 0:
        return
    fade = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.center().y()))
    fade.setColorAt(0.0, color)
    clear = QColor(color)
    clear.setAlpha(0)
    fade.setColorAt(1.0, clear)
    p.setPen(QPen(fade, 1.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(rect.adjusted(1.5, 1.5, -1.5, -1.5), radius - 1.5, radius - 1.5)


def _paint_glow(p: QPainter, rect: QRectF, color: QColor, strength: float) -> None:
    """A soft halo: a few widening, fading rounded outlines."""
    p.save()
    p.setBrush(Qt.BrushStyle.NoBrush)
    for i, spread in enumerate((2.0, 4.0, 6.5)):
        halo = QColor(color)
        halo.setAlphaF(strength * (0.28, 0.16, 0.07)[i])
        p.setPen(QPen(halo, 2.5))
        r = rect.adjusted(-spread, -spread, spread, spread)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
    p.restore()


def _paint_dot(p: QPainter, rect: QRectF, color: QColor, pal: Palette) -> None:
    x, y = g.notification_dot_center(rect.width(), rect.height())
    center = QPointF(rect.left() + x, rect.top() + y)
    s = rect.height() / g.HEIGHT
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(qcolor(pal.surface))
    p.drawEllipse(center, 5.5 * s, 5.5 * s)  # a ring of surface color separates it from the edge
    p.setBrush(color)
    p.drawEllipse(center, 3.75 * s, 3.75 * s)


def _paint_full_text(
    p: QPainter, rect: QRectF, model: PillModel, pal: Palette, fonts: Fonts
) -> None:
    s = fonts.scale
    left, right = rect.left() + PAD_X * s, rect.right() - PAD_X * s
    cy = rect.center().y()
    show_percent = model.kind in (PillKind.WORKING, PillKind.STALE)

    # % column: as wide as "100%", so the step never jumps when the number changes
    pm, sm = QFontMetricsF(fonts.percent), QFontMetricsF(fonts.sign)
    sign_gap = 0.5 * s
    percent_w = (pm.horizontalAdvance("100") + sign_gap + sm.horizontalAdvance("%")
                 if show_percent else 0.0)

    title_m = QFontMetricsF(fonts.title)
    title = title_m.elidedText(model.title, Qt.TextElideMode.ElideRight, (right - left) * 0.42)
    p.setPen(qcolor(pal.text))
    p.setFont(fonts.title)
    p.drawText(QPointF(left, baseline(title_m, cy)), title)

    detail_left = left + title_m.horizontalAdvance(title) + GAP_X * s
    detail_right = right - (percent_w + GAP_X * s if show_percent else 0.0)
    if model.kind is PillKind.DONE:
        detail_left = _paint_check(p, detail_left, cy, pal.edge(model.kind), s) + 5 * s
    elif model.kind is PillKind.LIMITED:
        detail_left = _paint_pause(p, detail_left, cy, pal.edge(model.kind), s) + 6 * s

    detail_m = QFontMetricsF(fonts.detail)
    detail = detail_m.elidedText(model.detail, Qt.TextElideMode.ElideRight,
                                 max(0.0, detail_right - detail_left))
    loud = model.kind in (PillKind.NEEDS_YOU, PillKind.LIMITED)
    p.setPen(qcolor(pal.text) if loud else qcolor(pal.text_soft))
    p.setFont(fonts.detail)
    p.drawText(QPointF(detail_left, baseline(detail_m, cy)), detail)

    if show_percent:
        # "42" in full, then a smaller, softer "%" on the same baseline
        y = baseline(pm, cy)
        sign_x = right - sm.horizontalAdvance("%")
        p.setPen(qcolor(pal.text_soft))
        p.setFont(fonts.sign)
        p.drawText(QPointF(sign_x, y), "%")
        number = str(model.percent)
        p.setPen(qcolor(pal.text))
        p.setFont(fonts.percent)
        p.drawText(QPointF(sign_x - sign_gap - pm.horizontalAdvance(number), y), number)


def _paint_circle_text(
    p: QPainter, rect: QRectF, model: PillModel, pal: Palette, fonts: Fonts
) -> None:
    # The circle is drawn at the pill's right end while morphing.
    circle = QRectF(rect.right() - rect.height(), rect.top(), rect.height(), rect.height())
    cx, cy = circle.center().x(), circle.center().y()
    s = fonts.scale
    if model.kind is PillKind.DONE:
        _paint_check(p, cx - 5 * s, cy, pal.edge(model.kind), s)
        return
    if model.kind is PillKind.LIMITED:
        _paint_pause(p, cx - PAUSE_WIDTH * s / 2, cy, pal.edge(model.kind), s)
        return
    if model.kind is PillKind.NEEDS_YOU:
        # A circle that needs you asks instead of counting (Manasvi, 2026-11-17:
        # "instead of 0 % show a ?"); the % is paused anyway. Sized like the ✓.
        font, text, color = fonts.ask, "?", pal.edge(model.kind)
    else:
        font, text, color = fonts.circle, str(model.percent), qcolor(pal.text)
    fm = QFontMetricsF(font)
    p.setPen(color)
    p.setFont(font)
    p.drawText(QPointF(cx - fm.horizontalAdvance(text) / 2, baseline(fm, cy)), text)


def _paint_check(p: QPainter, left: float, cy: float, color: QColor, s: float = 1.0) -> float:
    """A small drawn check mark (not a font glyph, so it looks the same everywhere),
    centered on ``cy``. Returns the x where it ends."""
    path = QPainterPath(QPointF(left, cy))
    path.lineTo(left + 3.5 * s, cy + 3.5 * s)
    path.lineTo(left + 10 * s, cy - 3.5 * s)
    pen = QPen(color, 2.0 * max(1.0, s), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    return left + 10 * s


PAUSE_WIDTH = 8.0  # the pause mark at scale 1: two 2.6 px bars, 2.8 px apart


def _paint_pause(p: QPainter, left: float, cy: float, color: QColor, s: float = 1.0) -> float:
    """Out of usage's second cue (besides its color): a drawn pause mark, centered
    on ``cy``. Returns the x where it ends."""
    bar_w, bar_h, gap = 2.6 * s, 9.0 * s, 2.8 * s
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    for x in (left, left + bar_w + gap):
        p.drawRoundedRect(QRectF(x, cy - bar_h / 2, bar_w, bar_h), bar_w / 2, bar_w / 2)
    return left + PAUSE_WIDTH * s


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))
