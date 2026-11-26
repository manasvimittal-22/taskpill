"""The live preview at the top of Settings: a small strip like the taskbar (or menu bar)
the pill lives on, with real pills drawn by the app's own painter in each state.

It follows the window's palette (the chosen colors) and the needs-you look (glow, dot),
so every change in Settings shows here at once instead of being picked blind."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QWidget

from taskpill.ui import geometry as g
from taskpill.ui.pill_painter import Fonts, PillLook, paint_pill
from taskpill.ui.theme import Palette, qcolor, ui_font
from taskpill.ui.view_model import PillKind, PillModel, Tooltip

PAD = 14  # inside the strip, around the pills
GAP = 8  # between pills (a little more than the real 6 px, so each state reads alone)
RADIUS = 10
GLOW = 0.6  # a still frame of the needs-you glow, near its brightest

_TIP = Tooltip("", "", "", "")
WORKING = PillModel("w", "taskpill", "Editing login.py", PillKind.WORKING, 42, _TIP)
NEEDS_YOU = PillModel("n", "api", "Has a question for you", PillKind.NEEDS_YOU, 0, _TIP)
CAPTION = "Preview"
DONE = PillModel("d", "docs", "Done", PillKind.DONE, 100, _TIP)
LIMITED = PillModel("l", "web", "Out of usage", PillKind.LIMITED, 61, _TIP)


def stage_color(pal: Palette) -> QColor:
    """A shade below the window, like a taskbar: the pills sit on it as they do for real."""
    base = qcolor(pal.surface)
    return base.darker(128) if pal.dark else base.darker(106)


class SettingsPreview(QWidget):
    def __init__(self, pal: Palette, glow: bool, dot: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self._pal, self._glow, self._dot = pal, glow, dot
        self._fonts = Fonts()
        self.setFixedHeight(int(g.HEIGHT + 2 * PAD))
        self.setAccessibleName("Preview of your pills: working, needs you, done, "
                               "and out of usage")

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(int(2 * g.FULL_WIDTH + 2 * g.HEIGHT + 3 * GAP + 2 * PAD),
                     int(g.HEIGHT + 2 * PAD))

    def set_palette(self, pal: Palette) -> None:
        self._pal = pal
        self.update()

    def set_needs_you_look(self, glow: bool, dot: bool) -> None:
        self._glow, self._dot = glow, dot
        self.update()

    def pill_rects(self) -> list[QRectF]:
        """Where each sample is drawn: two full pills, then two circles."""
        h, w = g.HEIGHT, g.FULL_WIDTH
        top = (self.height() - h) / 2
        x = PAD + 4
        rects = []
        for width in (w, w, h, h):
            rects.append(QRectF(x, top, width, h))
            x += width + GAP
        return rects

    def paintEvent(self, _event) -> None:  # noqa: N802
        pal = self._pal
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        strip = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(qcolor(pal.hairline), 1))
        p.setBrush(stage_color(pal))
        p.drawRoundedRect(strip, RADIUS, RADIUS)

        working, needs, done, limited = self.pill_rects()
        full, circle = PillLook(edge=0.42), PillLook(morph=0.0, edge=1.0)
        paint_pill(p, working, WORKING, full, pal, self._fonts)
        paint_pill(p, needs, NEEDS_YOU,
                   PillLook(edge=1.0, glow=GLOW if self._glow else 0.0,
                            show_glow=self._glow, show_dot=self._dot), pal, self._fonts)
        paint_pill(p, done, DONE, circle, pal, self._fonts)
        paint_pill(p, limited, LIMITED, PillLook(morph=0.0, edge=0.61), pal, self._fonts)

        # Says these are samples, not your sessions; it sits where the tray would be.
        font = ui_font(12)
        p.setFont(font)
        p.setPen(qcolor(pal.text_soft))
        width = QFontMetricsF(font).horizontalAdvance(CAPTION)
        caption = QRectF(strip.right() - PAD - width - 4, strip.top(), width + 4, strip.height())
        p.drawText(caption, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, CAPTION)
        p.end()
