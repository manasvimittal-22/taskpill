"""Small floating surfaces that belong to the pills (docs/design.md → Round 2, Polish):

* ``HoverCard``: what a pill is doing, centered right above it.
* ``PillMenu``: the right-click menu, opening right above the pill.
* ``ResizeChip``: the size and Reset / Cancel / Done while resizing.

They share the pill's material: a surface lit softly from above, a hairline and
a rim of light, plus a soft shadow that lifts them off the taskbar. They never
take keyboard focus away from what you're doing, and they only fade (opacity),
never change size while animating.
"""

from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget

from taskpill.ui import motion
from taskpill.ui.theme import Palette, qcolor, rim_light, surface_light, tabular, ui_font
from taskpill.ui.view_model import PillKind, PillModel

GAP_ABOVE = 8  # between a pill and the (visible) surface above it
RADIUS = 10.0
CARD_WIDTH = 280  # the visible card
# Room around a surface for its shadow. Less below than to the sides, so the
# window never reaches down over the pill (the shadow falls mostly downward).
SHADOW = QMargins(10, 6, 10, 6)
DOT = 6.0  # the state dot before the card's step line


def _popup_flags() -> Qt.WindowType:
    return (
        Qt.WindowType.ToolTip
        | Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowStaysOnTopHint
        | Qt.WindowType.WindowDoesNotAcceptFocus
        | Qt.WindowType.NoDropShadowWindowHint
    )


def place_above(size: QSize, anchor: QRect, inset: QMargins | None = None) -> QPoint:
    """Top-left for a window centered above ``anchor`` (below it if there's no
    room above), kept on the anchor's screen. ``inset`` is the window's
    see-through shadow margin: the gap is measured to the visible surface."""
    inset = inset or QMargins()
    screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
    area = screen.geometry() if screen else QRect(0, 0, 10000, 10000)
    x = anchor.center().x() - size.width() // 2
    y = anchor.top() - GAP_ABOVE - (size.height() - inset.bottom())
    if y + inset.top() < area.top():
        y = anchor.bottom() + GAP_ABOVE - inset.top()
    x = max(area.left() + 4 - inset.left(),
            min(x, area.right() - size.width() - 4 + inset.right()))
    return QPoint(x, y)


def paint_material(p: QPainter, rect: QRectF, radius: float, pal: Palette,
                   shadow: bool = True) -> None:
    """The popups' surface: shadow, top-lit fill, hairline and rim of light."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if shadow:
        strength = 0.34 if pal.dark else 0.10
        for spread, alpha, drop in ((1.0, 0.55, 1.0), (3.5, 0.28, 2.0), (6.5, 0.12, 3.0)):
            color = QColor(0, 0, 0)
            color.setAlphaF(strength * alpha)
            r = rect.adjusted(-spread, -spread + drop, spread, spread + drop - 1)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(r, radius + spread, radius + spread)
    top, bottom = surface_light(pal)
    light = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    light.setColorAt(0.0, top)
    light.setColorAt(1.0, bottom)
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    p.fillPath(path, light)
    hair = qcolor(pal.hairline)
    if pal.dark:
        hair = hair.lighter(170)
    p.setPen(QPen(hair, 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    rim = rim_light(pal)
    if rim.alpha():
        fade = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.top() + 14))
        fade.setColorAt(0.0, rim)
        clear = QColor(rim)
        clear.setAlpha(0)
        fade.setColorAt(1.0, clear)
        p.setPen(QPen(fade, 1))
        p.drawRoundedRect(rect.adjusted(1.5, 1.5, -1.5, -1.5), radius - 1, radius - 1)


class _Surface(QWidget):
    """A floating panel in the pill's material, with room around it for a shadow."""

    def __init__(self, pal: Palette) -> None:
        super().__init__(None)
        self._pal = pal
        self.setWindowFlags(_popup_flags())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

    def set_palette(self, pal: Palette) -> None:
        self._pal = pal
        self.update()

    def surface_rect(self) -> QRectF:
        return QRectF(self.rect().marginsRemoved(SHADOW))

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        paint_material(p, self.surface_rect(), RADIUS, self._pal)
        self.paint_extras(p)
        p.end()

    def paint_extras(self, p: QPainter) -> None:
        """Subclasses draw on top of the surface here."""


def _label(text: str, font: QFont, color: str, wrap_width: int | None = None) -> QLabel:
    label = QLabel(text)
    label.setFont(font)
    label.setStyleSheet(f"color: {color}; background: transparent;")
    label.setTextFormat(Qt.TextFormat.PlainText)
    if wrap_width:
        label.setWordWrap(True)
        label.setFixedWidth(wrap_width)  # wrapped labels need a real width
    return label


class HoverCard(_Surface):
    """What a session is doing. Fades in over 0.12 s; fades out after a short
    grace period, so moving between pills doesn't flicker.

    Lines: the prompt; the step (after a dot in the state's color); how long
    it has been running; and the folder, only when two sessions share a name.
    """

    HIDE_DELAY_MS = 120
    PAD = QMargins(13, 10, 13, 11)

    def __init__(self, pal: Palette) -> None:
        super().__init__(pal)
        # It's only to read: the mouse goes straight through to what's below.
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(SHADOW + self.PAD)
        self._layout.setSpacing(3)
        self._session: str | None = None
        self._dot_color = QColor(pal.working)
        self._opacity = motion.Animated(0.0, motion.FADE)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._step)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)

    @property
    def session(self) -> str | None:
        return self._session if self.isVisible() else None

    @property
    def hiding(self) -> bool:
        return self._hide_timer.isActive() or (
            self.isVisible() and self._opacity.target == 0.0)

    def show_for(self, model: PillModel, pill: QRect, show_folder: bool = False) -> None:
        """Show (or keep showing) the card for this pill. Cancels a pending hide:
        only call it when the mouse really is over the pill."""
        self._hide_timer.stop()
        self._fill(model, show_folder)
        appearing = not self.isVisible()
        if appearing:
            # Show it fully transparent first: wrapped text can measure differently
            # once the window exists, and the card must not move after it appears.
            self.setWindowOpacity(0.0)
            self._opacity.set(0.0, motion.time_now(), instant=True)
            self.show()
        self.adjustSize()
        self.move(place_above(self.size(), pill, SHADOW))
        if appearing or self._session != model.session_id or self._opacity.target == 0.0:
            self._session = model.session_id
            self._show_folder = show_folder
            self._opacity.set(1.0, motion.time_now())
            self._timer.start()

    def refresh(self, model: PillModel, pill: QRect) -> None:
        """New text for the same session. Never cancels a pending hide."""
        if not self.isVisible() or model.session_id != self._session:
            return
        self._fill(model, getattr(self, "_show_folder", False))
        self.adjustSize()
        self.move(place_above(self.size(), pill, SHADOW))

    def hide_soon(self) -> None:
        if self.isVisible() and not self._hide_timer.isActive():
            self._hide_timer.start(self.HIDE_DELAY_MS)

    def hide_now(self) -> None:
        self._hide_timer.stop()
        self._timer.stop()
        self.hide()
        self._session = None

    def _fade_out(self) -> None:
        self._opacity.set(0.0, motion.time_now())
        self._timer.start()

    def _step(self) -> None:
        now = motion.time_now()
        value = self._opacity.value(now)
        self.setWindowOpacity(value)
        if not self._opacity.running(now):
            self._timer.stop()
            if value == 0.0:
                self.hide()
                self._session = None

    def _lines(self) -> list[QLabel]:
        """The card's four lines, made once and then only updated, so the card's
        size never changes just because the labels were rebuilt."""
        if not hasattr(self, "_line_labels"):
            pal = self._pal
            width = CARD_WIDTH - self.PAD.left() - self.PAD.right()
            step = _label("", ui_font(12), pal.text_soft, width)
            step.setIndent(int(DOT + 7))  # room for the state dot
            self._line_labels = [
                _label("", ui_font(12.5, QFont.Weight.Medium), pal.text, width),  # prompt
                step,  # step / message
                _label("", tabular(ui_font(11.5)), pal.text_soft, width),  # elapsed
                _label("", ui_font(11.5), pal.text_soft, width),  # folder
            ]
            for label in self._line_labels:
                self._layout.addWidget(label)
            self._layout.insertSpacing(1, 2)
        return self._line_labels

    def _fill(self, model: PillModel, show_folder: bool) -> None:
        pal = self._pal
        t = model.tooltip
        if model.kind is PillKind.LIMITED:
            detail = t.note or model.detail  # Claude Code's words, e.g. "… resets at 3pm"
        elif model.kind is PillKind.NEEDS_YOU:
            detail = model.detail
        else:
            detail = "Done" if model.kind is PillKind.DONE else t.step or model.detail
        prompt, step, elapsed, folder = self._lines()
        for label, text in ((prompt, t.prompt), (step, detail), (elapsed, t.elapsed),
                            (folder, t.folder if show_folder else "")):
            label.setText(text)
            label.setVisible(bool(text))
        loud = model.kind in (PillKind.NEEDS_YOU, PillKind.LIMITED)
        color = pal.text if loud else pal.text_soft
        step.setStyleSheet(f"color: {color}; background: transparent;")
        self._dot_color = pal.edge(model.kind)
        self.update()

    def paint_extras(self, p: QPainter) -> None:
        step = self._lines()[1]
        if step.isHidden() or not step.text():
            return
        fm = step.fontMetrics()
        # centered on the first line's x-height, like a bullet
        cy = step.y() + step.contentsRect().top() + fm.ascent() - fm.xHeight() / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._dot_color)
        p.drawEllipse(QPointF(step.x() + DOT / 2 + 0.5, cy + 0.5), DOT / 2, DOT / 2)


class PillMenu(QMenu):
    """The right-click menu, in the pill's material, opening above the pill."""

    def __init__(self, pal: Palette) -> None:
        super().__init__(None)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._pal = pal
        accent = QColor(pal.working)
        selected = f"rgba({accent.red()},{accent.green()},{accent.blue()},0.22)"
        separator = "rgba(255,255,255,0.08)" if pal.dark else "rgba(0,0,0,0.08)"
        m = SHADOW
        # The surface itself is painted (paintEvent); the stylesheet only lays out items.
        self.setStyleSheet(f"""
            QMenu {{ background: transparent; border: none;
                     padding: {m.top() + 5}px {m.right() + 5}px
                              {m.bottom() + 5}px {m.left() + 5}px; }}
            QMenu::item {{ color: {pal.text}; padding: 5px 26px 5px 10px; border-radius: 6px;
                           font-size: 12.5px; margin: 0px; }}
            QMenu::item:selected {{ background: {selected}; }}
            QMenu::item:disabled {{ color: {pal.text_soft}; }}
            QMenu::separator {{ height: 1px; background: {separator}; margin: 4px 10px; }}
        """)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        paint_material(p, QRectF(self.rect().marginsRemoved(SHADOW)), RADIUS, self._pal)
        p.end()
        super().paintEvent(event)

    def add(self, text: str, slot) -> QAction:
        action = self.addAction(text)
        action.triggered.connect(slot)
        return action

    def popup_above(self, pill: QRect) -> None:
        self.popup(place_above(self.sizeHint(), pill, SHADOW))


class ResizeChip(_Surface):
    """Shown above the pill in resize mode: "260 × 34   Reset   Cancel   Done"."""

    reset = Signal()
    cancel = Signal()
    done = Signal()

    def __init__(self, pal: Palette) -> None:
        super().__init__(pal)
        row = QHBoxLayout(self)
        row.setContentsMargins(SHADOW + QMargins(13, 5, 5, 5))
        row.setSpacing(2)
        self.size_label = _label("", tabular(ui_font(12, QFont.Weight.DemiBold)), pal.text)
        self.size_label.setMinimumWidth(64)
        row.addWidget(self.size_label)
        row.addSpacing(8)
        self.buttons: dict[str, QPushButton] = {}
        for name, signal, primary in (("Reset", self.reset, False),
                                      ("Cancel", self.cancel, False),
                                      ("Done", self.done, True)):
            button = QPushButton(name)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(signal)
            button.setStyleSheet(self._button_style(pal, primary))
            row.addWidget(button)
            self.buttons[name] = button

    @staticmethod
    def _button_style(pal: Palette, primary: bool) -> str:
        if primary:
            text = "#15131F" if pal.dark else "#FFFFFF"
            lit = QColor(pal.working).lighter(112).name()
            return (f"QPushButton {{ color: {text}; border: none; border-radius: 7px;"
                    f" padding: 4px 13px; font-size: 12px; font-weight: 600;"
                    f" background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
                    f" stop:0 {lit}, stop:1 {pal.working}); }}"
                    f" QPushButton:hover {{ background: {lit}; }}")
        hover = "rgba(255,255,255,0.08)" if pal.dark else "rgba(0,0,0,0.06)"
        return (f"QPushButton {{ color: {pal.text_soft}; background: transparent; border: none;"
                f" border-radius: 7px; padding: 4px 10px; font-size: 12px; }}"
                f" QPushButton:hover {{ background: {hover}; color: {pal.text}; }}")

    def show_size(self, width: float, height: float, pill: QRect) -> None:
        self.size_label.setText(f"{round(width)} × {round(height)}")
        # Show first, then measure: before its first show the chip measures smaller
        # than it ends up, and on a Mac it then grew down over the pill (2026-11-22).
        if not self.isVisible():
            self.show()
        self.adjustSize()
        self.move(place_above(self.size(), pill, SHADOW))
