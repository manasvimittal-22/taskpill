"""Small hand-drawn controls for the settings window: a toggle, accent swatches, a
segmented control. Drawn with QPainter so they match the pill on both OSes.
All are keyboard-usable (Tab to focus, Space/Enter/arrows to change)."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QKeyEvent, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from taskpill.ui import motion
from taskpill.ui.theme import ACCENT_COLORS, Palette, qcolor, ui_font

FOCUS_RING = 2.0


def _focus_ring(p: QPainter, rect: QRectF, pal: Palette, radius: float) -> None:
    ring = QColor(pal.working)
    ring.setAlphaF(0.6)
    p.setPen(QPen(ring, FOCUS_RING))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(rect, radius, radius)


class Toggle(QAbstractButton):
    """A 34 × 20 capsule switch. The knob slides in 0.12 s."""

    def __init__(self, pal: Palette, checked: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._pal = pal
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._knob = motion.Animated(1.0 if checked else 0.0, motion.FADE)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._step)
        self.toggled.connect(self._animate)

    def set_palette(self, pal: Palette) -> None:
        self._pal = pal
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(38, 24)

    def _animate(self, on: bool) -> None:
        self._knob.set(1.0 if on else 0.0, motion.time_now())
        self._timer.start()

    def _step(self) -> None:
        if not self._knob.running(motion.time_now()):
            self._timer.stop()
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        pal = self._pal
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(2, 2, 34, 20)
        t = self._knob.value(motion.time_now())
        if self.hasFocus():
            _focus_ring(p, track.adjusted(-1.5, -1.5, 1.5, 1.5), pal, 11.5)
        on = QColor(pal.working)
        off = qcolor(pal.hairline)
        if t > 0:
            fill = QColor(on)
            fill.setAlphaF(t)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(track, 10, 10)
        if t < 1:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(off.lighter(160) if pal.dark else off.darker(130), 1.25))
            p.drawRoundedRect(track.adjusted(0.6, 0.6, -0.6, -0.6), 9.4, 9.4)
        knob_x = track.left() + 3 + t * 14
        knob = QColor(pal.surface) if t > 0.5 else qcolor(pal.text_soft)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(knob)
        p.drawEllipse(QRectF(knob_x, track.top() + 3, 14, 14))
        p.end()


class Swatches(QWidget):
    """A color choice: one circle per color; the chosen one wears an edge ring.
    ``colors`` is one of theme's sets (name → (dark, light))."""

    changed = Signal(str)

    def __init__(self, pal: Palette, current: str, parent: QWidget | None = None,
                 colors: dict[str, tuple[str, str]] | None = None):
        super().__init__(parent)
        self._pal = pal
        self._colors = colors or ACCENT_COLORS
        self._names = list(self._colors)
        self._current = current if current in self._colors else self._names[0]
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(len(self._names) * 30, 28)

    @property
    def current(self) -> str:
        return self._current

    def set_palette(self, pal: Palette) -> None:
        self._pal = pal
        self.update()

    def _choose(self, name: str) -> None:
        if name != self._current:
            self._current = name
            self.update()
            self.changed.emit(name)

    def _rect(self, i: int) -> QRectF:
        return QRectF(i * 30 + 3, 3, 22, 22)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        for i, name in enumerate(self._names):
            if self._rect(i).contains(event.position()):
                self._choose(name)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        i = self._names.index(self._current)
        if event.key() in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self._choose(self._names[(i + 1) % len(self._names)])
        elif event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self._choose(self._names[(i - 1) % len(self._names)])
        else:
            super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i, name in enumerate(self._names):
            dark, light = self._colors[name]
            color = QColor(dark if self._pal.dark else light)
            r = self._rect(i)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawEllipse(r.adjusted(4, 4, -4, -4))
            if name == self._current:
                pen = QPen(color, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawArc(r.adjusted(1, 1, -1, -1), 90 * 16, -300 * 16)
                if self.hasFocus():
                    _focus_ring(p, r.adjusted(-1, -1, 1, 1), self._pal, 12)
        p.end()


class Segmented(QWidget):
    """A row of choices, one selected. E.g. "5 min | 10 min | 30 min | 1 h | Never"."""

    changed = Signal(object)

    def __init__(self, pal: Palette, choices: list[tuple[object, str]], current: object,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._pal = pal
        self._choices = choices
        values = [v for v, _ in choices]
        self._index = values.index(current) if current in values else 0
        self._font = ui_font(12)
        self._bold = ui_font(12, QFont.Weight.DemiBold)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(30)
        self.setMinimumWidth(len(choices) * 54)

    @property
    def value(self) -> object:
        return self._choices[self._index][0]

    def set_palette(self, pal: Palette) -> None:
        self._pal = pal
        self.update()

    def _select(self, index: int) -> None:
        index = max(0, min(len(self._choices) - 1, index))
        if index != self._index:
            self._index = index
            self.update()
            self.changed.emit(self.value)

    def _segment(self, i: int) -> QRectF:
        w = (self.width() - 2) / len(self._choices)
        return QRectF(1 + i * w, 1, w, self.height() - 2)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        for i in range(len(self._choices)):
            if self._segment(i).contains(event.position()):
                self._select(i)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Right:
            self._select(self._index + 1)
        elif event.key() == Qt.Key.Key_Left:
            self._select(self._index - 1)
        else:
            super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        pal = self._pal
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        outer = QRectF(1, 1, self.width() - 2, self.height() - 2)
        if self.hasFocus():
            _focus_ring(p, outer.adjusted(-0.5, -0.5, 0.5, 0.5), pal, 9)
        p.setPen(QPen(qcolor(pal.hairline).lighter(150) if pal.dark
                      else qcolor(pal.hairline), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(outer, 8, 8)
        for i, (_value, label) in enumerate(self._choices):
            seg = self._segment(i)
            selected = i == self._index
            if selected:
                fill = QColor(pal.working)
                fill.setAlphaF(0.18 if pal.dark else 0.12)
                p.setPen(QPen(QColor(pal.working), 1.25))
                p.setBrush(fill)
                p.drawRoundedRect(seg.adjusted(2, 2, -2, -2), 6, 6)
            p.setPen(qcolor(pal.text) if selected else qcolor(pal.text_soft))
            p.setFont(self._bold if selected else self._font)
            p.drawText(seg, Qt.AlignmentFlag.AlignCenter, label)
        p.end()


class KeyCaps(QWidget):
    """Keys drawn as small caps in a row: Ctrl Alt Space. Read-only; its accessible
    name spells the combination out ("Ctrl plus Alt plus Space")."""

    HEIGHT = 22
    GAP = 4
    PAD = 7

    def __init__(self, pal: Palette, keys: Sequence[str], parent: QWidget | None = None):
        super().__init__(parent)
        self._pal = pal
        self._keys = list(keys)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(" plus ".join(self._keys))
        self.setFixedSize(self.sizeHint())

    def set_palette(self, pal: Palette) -> None:
        self._pal = pal
        self.update()

    def _font(self) -> QFont:
        return ui_font(11.5, QFont.Weight.DemiBold)

    def _cap_widths(self) -> list[float]:
        metrics = QFontMetricsF(self._font())
        return [max(self.HEIGHT, metrics.horizontalAdvance(k) + 2 * self.PAD) for k in self._keys]

    def sizeHint(self) -> QSize:  # noqa: N802
        widths = self._cap_widths()
        return QSize(round(sum(widths) + self.GAP * (len(widths) - 1)) + 1, self.HEIGHT + 1)

    def paintEvent(self, _event) -> None:  # noqa: N802
        pal = self._pal
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(self._font())
        x = 0.5
        for key, width in zip(self._keys, self._cap_widths(), strict=True):
            cap = QRectF(x, 0.5, width, self.HEIGHT - 1)
            face = qcolor(pal.text)
            face.setAlphaF(0.07 if pal.dark else 0.05)
            edge = qcolor(pal.hairline)
            p.setBrush(face)
            p.setPen(QPen(edge.lighter(150) if pal.dark else edge.darker(120), 1))
            p.drawRoundedRect(cap, 6, 6)
            # the cap's lower lip: a key has a little depth
            lip = QRectF(cap.left() + 5, cap.bottom() + 0.5, cap.width() - 10, 0)
            p.setPen(QPen(edge, 1))
            p.drawLine(lip.topLeft(), lip.topRight())
            p.setPen(qcolor(pal.text))
            p.drawText(cap, Qt.AlignmentFlag.AlignCenter, key)
            x += width + self.GAP
        p.end()
