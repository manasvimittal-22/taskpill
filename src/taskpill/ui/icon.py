"""The tray icon: a small ring that mirrors the pills (docs/design.md → App shell)."""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

from taskpill.ui.theme import Palette

SIZES = (16, 20, 24, 32, 48, 64)


class TrayState(Enum):
    IDLE = "idle"
    WORKING = "working"
    NEEDS_YOU = "needs_you"
    LIMITED = "limited"  # out of usage: a full ring in its color with a pause mark inside


def tray_icon(state: TrayState, pal: Palette, taskbar_dark: bool = True) -> QIcon:
    icon = QIcon()
    for size in SIZES:
        icon.addPixmap(_ring(size, state, pal, taskbar_dark))
    return icon


def _ring(size: int, state: TrayState, pal: Palette, taskbar_dark: bool) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    stroke = max(1.5, size / 8)
    inset = stroke / 2 + size * 0.06
    rect = QRectF(inset, inset, size - 2 * inset, size - 2 * inset)

    track = QColor("#FFFFFF" if taskbar_dark else "#000000")
    track.setAlphaF(0.35)
    p.setPen(QPen(track, stroke))
    p.drawEllipse(rect)

    if state is not TrayState.IDLE:
        color = QColor({TrayState.NEEDS_YOU: pal.needs_you,
                        TrayState.LIMITED: pal.limited}.get(state, pal.working))
        pen = QPen(color, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        span = 270 if state is TrayState.WORKING else 360
        if state is TrayState.LIMITED:
            bar_h, bar_w = size * 0.30, max(1.0, size * 0.09)
            gap = bar_w * 1.4
            top = size / 2 - bar_h / 2
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            for x in (size / 2 - gap / 2 - bar_w, size / 2 + gap / 2):
                p.drawRoundedRect(QRectF(x, top, bar_w, bar_h), bar_w / 2, bar_w / 2)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
        # Qt angles: 1/16 degree, counter-clockwise from 3 o'clock. Start at 12, go clockwise.
        p.drawArc(rect, 90 * 16, -span * 16)
    p.end()
    return pix
