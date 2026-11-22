"""The window that holds the row of pills.

One frameless, see-through, always-on-top window draws every pill. That keeps
the row's layout, z-order and dragging in one place.

* Animations are painted values (``motion.Animated``) driven by one timer
  that only runs while something moves. The OS window only changes width
  when an animation starts (to fit both the old and new layouts) and after it
  ends (to fit the new one), never in between. Its height never changes: it
  always fits the tallest pill the user can choose.
* The window is anchored at a point (``set_anchor``): its right edge
  (Windows) or its center (macOS). Resizing keeps the anchor still.
* Fully transparent pixels let clicks through to the taskbar below.
* Hover shows a card right above the pill; right-click asks for the menu
  (``menu_requested``); resize mode lets the user drag the pill's size.
"""

from __future__ import annotations

import html
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAccessible,
    QAccessibleEvent,
    QColor,
    QCursor,
    QMouseEvent,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import QWidget

from taskpill.ui import geometry as g
from taskpill.ui import motion, spoken
from taskpill.ui.pill_painter import Fonts, PillLook, paint_pill
from taskpill.ui.popups import HoverCard, ResizeChip
from taskpill.ui.theme import Palette, qcolor, system_palette
from taskpill.ui.view_model import PillKind, PillModel

FRAME_MS = 16
DRAG_THRESHOLD = 4
GRIP_HIT = 8.0  # extra grab room around a resize grip
HOVER_POLL_MS = 100  # macOS: how often the pointer is checked for hover


@dataclass
class RowOptions:
    anchor: g.Anchor = g.Anchor.RIGHT
    glow: bool = True
    expand_needs_you: bool = True
    dot: bool = True
    reduced_motion: bool = False
    # macOS sends no mouse-move events to an app that isn't active, and TaskPill
    # never is, so hover comes from polling the pointer (found on a Mac, 2026-11-22).
    poll_hover: bool = False
    circle_by_default: bool = False  # what Reset size goes back to (a circle on a Mac)


@dataclass
class _Item:
    model: PillModel
    width: motion.Animated
    opacity: motion.Animated
    edge: motion.Animated
    x: motion.Animated
    needs_you_since: float = 0.0
    leaving: bool = False
    placed: bool = False


@dataclass
class _Resize:
    """State while the user is resizing the pill."""

    target: str  # the session whose pill shows at full size with grips
    original: g.Dims  # for Cancel
    grips: motion.Animated = field(default_factory=lambda: motion.Animated(0.0, motion.FADE))
    ending: bool = False
    drag: str | None = None  # "width" or "height" while a grip is held
    press: QPointF = field(default_factory=QPointF)
    start: g.Dims = field(default_factory=g.Dims)


class PillRow(QWidget):
    clicked = Signal(str)  # session_id
    moved = Signal(QPoint)  # new anchor point after a drag
    menu_requested = Signal(str, QRect)  # session_id, the pill's rect on screen
    resize_finished = Signal(object)  # the chosen g.Dims (Done)
    resize_cancelled = Signal()

    def __init__(self, options: RowOptions | None = None, palette: Palette | None = None,
                 clock=time.monotonic, dims: g.Dims = g.DEFAULT) -> None:
        super().__init__(None)
        self._options = options or RowOptions()
        self._palette = palette or system_palette()
        self._clock = clock
        self._dims = dims
        self._height = motion.Animated(dims.height, motion.MORPH)
        self._items: dict[str, _Item] = {}
        self._order: list[str] = []
        self._anchor = QPoint(0, 0)
        self._window_w = 0  # the width we last gave the window (0 = not placed yet)
        self._room: float | None = None
        self._bar_height: float | None = None  # macOS: the pill fits in the menu bar
        self._last_models: list[PillModel] = []
        self._spoken_key: frozenset = frozenset()  # what a screen reader was last told
        self._spoken_waiting: set[str] = set()
        self._sessions = 0  # sessions running, shown or not (decides circles vs pills)
        self._hovered: str | None = None
        self._press: QPoint | None = None
        self._dragging = False
        self._resize: _Resize | None = None
        self._card: HoverCard | None = None
        self._chip: ResizeChip | None = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setFixedHeight(int(g.window_height()))

        self._frame = QTimer(self)
        self._frame.setInterval(FRAME_MS)
        self._frame.timeout.connect(self._tick)
        self._hover_watch = QTimer(self)
        self._hover_watch.setInterval(200)
        self._hover_watch.timeout.connect(self._check_hover)
        self._cursor_pos = QCursor.pos  # replaceable in tests
        self._hover_poll = QTimer(self)
        self._hover_poll.setInterval(HOVER_POLL_MS)
        self._hover_poll.timeout.connect(self.poll_hover)

    # ---- public API -----------------------------------------------------------
    def set_anchor(self, point: QPoint) -> None:
        """Right edge (Windows) or left edge (macOS) of the row, in screen pixels."""
        self._anchor = QPoint(point)
        if self._window_w:
            self._place(self._window_w)

    def anchor(self) -> QPoint:
        return QPoint(self._anchor)

    @property
    def dims(self) -> g.Dims:
        """The size the user set (what Settings saves)."""
        return self._dims

    def shown_dims(self) -> g.Dims:
        """The size actually drawn: the user's size, fitted to the macOS menu bar
        (its height, and the room up to the first menu-bar icon). Windows: the same."""
        room = self._room if self._options.anchor is g.Anchor.LEFT else None
        return g.fit_dims(self._dims, self._bar_height, room)

    def set_dims(self, dims: g.Dims, *, instant: bool = False) -> None:
        """The pill's size (from Settings, or live while resizing)."""
        self._dims = dims
        self._refit(instant=instant)

    def set_room(self, room: float | None) -> None:
        """Free width next to the anchor (e.g. up to the taskbar's app icons)."""
        if room == self._room:
            return
        self._room = room
        self._refit()

    def set_bar_height(self, height: float | None) -> None:
        """macOS: the pill is never taller than this (None: no limit)."""
        if height == self._bar_height:
            return
        self._bar_height = height
        self._refit()

    def _refit(self, *, instant: bool = False) -> None:
        self._height.set(self.shown_dims().height, self._clock(),
                         instant=instant or self._options.reduced_motion)
        self._retarget(instant=instant)
        self._update_chip()

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        # The popups are rebuilt in the new colors the next time they're needed.
        for popup in (self._card, self._chip):
            if popup is not None:
                popup.hide()
                popup.deleteLater()
        self._card = self._chip = None
        self._update_chip()
        self.update()

    def _update_accessibility(self, models: list[PillModel]) -> None:
        """Give screen readers the words for what is painted, and speak up on real news
        (a session started waiting for you, finished, ran out of usage), not on % ticks."""
        # Windows reads the *name*, so the words go there; the description repeats them
        # for readers that look at it. (Checked with UI Automation, 2026-11-18.)
        words = spoken.describe(models)
        self.setAccessibleName(f"{spoken.NAME}: {words}" if words else spoken.NAME)
        self.setAccessibleDescription(words)
        key = spoken.announcement_key(models)
        if key == self._spoken_key:
            return
        newly_waiting = spoken.needs_you_ids(models) - self._spoken_waiting
        self._spoken_key = key
        self._spoken_waiting = spoken.needs_you_ids(models)
        if QAccessible.isActive():
            events = QAccessible.Event
            kind = events.Alert if newly_waiting else events.DescriptionChanged
            QAccessible.updateAccessibility(QAccessibleEvent(self, kind))

    def set_options(self, options: RowOptions) -> None:
        self._options = options
        self._update_hover_poll()
        self._retarget()

    def _update_hover_poll(self) -> None:
        on = self._options.poll_hover and self.has_pills()
        if on and not self._hover_poll.isActive():
            self._hover_poll.start()
        elif not on and self._hover_poll.isActive():
            self._hover_poll.stop()

    def poll_hover(self) -> None:
        """What a mouse move would do, from where the pointer is right now."""
        if self.resizing or self._press is not None or self.isHidden():
            return
        local = QPointF(self.mapFromGlobal(self._cursor_pos()))
        item = self._item_at(local) if self.rect().contains(local.toPoint()) else None
        sid = item.model.session_id if item else None
        if sid == self._hovered:
            return
        if item is None:
            self.leaveEvent(None)
            return
        self._hovered = sid
        self.update()
        self._show_card(item)

    def set_models(self, models: list[PillModel], sessions: int | None = None) -> None:
        """``sessions``: how many sessions are running, including ones hidden right
        now (full screen hides all but needs-you pills). Pills collapse to circles
        when 2+ are running, so a needs-you circle stays a circle over a full-screen
        app (Manasvi, 2026-11-17). Defaults to ``len(models)``."""
        self._sessions = len(models) if sessions is None else max(sessions, len(models))
        now = self._clock()
        instant = self._options.reduced_motion
        incoming = {m.session_id for m in models}

        for item in self._items.values():
            if item.model.session_id not in incoming and not item.leaving:
                item.leaving = True
                item.opacity.set(0.0, now, instant=instant)

        self._last_models = list(models)
        self._update_accessibility(models)
        for m in models:
            item = self._items.get(m.session_id)
            target_w = self._target_width(m, models)
            if item is None:
                item = _Item(
                    model=m,
                    width=motion.Animated(target_w, motion.MORPH),
                    opacity=motion.Animated(0.0, motion.FADE),
                    edge=motion.Animated(m.fraction, motion.EDGE),
                    x=motion.Animated(0.0, motion.MORPH),
                )
                item.opacity.set(1.0, now, instant=instant)
                self._items[m.session_id] = item
                self._order.append(m.session_id)
            else:
                item.leaving = False
                item.opacity.set(1.0, now, instant=instant)
                item.width.set(target_w, now, instant=instant)
                item.edge.set(m.fraction, now, instant=instant)
            if m.kind is PillKind.NEEDS_YOU and (
                item.model.kind is not PillKind.NEEDS_YOU or item.needs_you_since == 0.0
            ):
                item.needs_you_since = now
            item.model = m

        if self._resize is not None and self._resize.target not in incoming:
            self._end_resize()  # the pill being resized went away
        self._update_hover_poll()
        self._relayout()
        self._refresh_card()

    def has_pills(self) -> bool:
        return any(not i.leaving for i in self._items.values())

    # ---- resize mode -------------------------------------------------------------
    @property
    def resizing(self) -> bool:
        return self._resize is not None and not self._resize.ending

    def begin_resize(self, session_id: str | None = None) -> bool:
        """Show the pill at full size with grips to drag. False if there's no pill."""
        live = [sid for sid in self._order if not self._items[sid].leaving]
        if not live:
            return False
        target = session_id if session_id in live else live[0]
        self._resize = _Resize(target=target, original=self._dims)
        self._resize.grips.set(1.0, self._clock(), instant=self._options.reduced_motion)
        self._hide_card()
        self._retarget()
        self._update_chip()
        return True

    def finish_resize(self) -> None:
        if self.resizing:
            dims = self._dims
            self._end_resize()
            self.resize_finished.emit(dims)

    def cancel_resize(self) -> None:
        if self.resizing:
            original = self._resize.original
            self._end_resize()
            self.set_dims(original)
            self.resize_cancelled.emit()

    def reset_size(self) -> None:
        """Back to the default size (stays in resize mode if it's on)."""
        self.set_dims(g.default_dims(self._options.circle_by_default))

    def _end_resize(self) -> None:
        if self._resize is None:
            return
        self._resize.ending = True
        self._resize.drag = None
        self._resize.grips.set(0.0, self._clock(), instant=self._options.reduced_motion)
        if self._chip is not None:
            self._chip.hide()
        self.unsetCursor()
        self._retarget()

    def _target_rect(self, now: float) -> QRectF | None:
        if self._resize is None or self._resize.target not in self._items:
            return None
        return self._rect(self._items[self._resize.target], now)

    def _grips(self, rect: QRectF) -> dict[str, QRectF]:
        span = max(14.0, rect.height() * 0.55)
        cy = rect.center().y()
        # The free edge sets the width; the other end stays by the anchor: the
        # left edge on Windows, the right edge on macOS (the left end is by the notch).
        edge_x = rect.right() if self._options.anchor is g.Anchor.LEFT else rect.left()
        return {
            "width": QRectF(edge_x - 3, cy - span / 2, 6, span),
            # the top edge sets the height (grows evenly up and down). It sits a
            # little above the edge so it doesn't melt into the progress line,
            # which starts at the top center too.
            "height": QRectF(rect.center().x() - 14, rect.top() - 6, 28, 7),
        }

    def _grip_at(self, pos: QPointF) -> str | None:
        rect = self._target_rect(self._clock())
        if rect is None or not self.resizing:
            return None
        for name, grip in self._grips(rect).items():
            if grip.adjusted(-GRIP_HIT, -GRIP_HIT, GRIP_HIT, GRIP_HIT).contains(pos):
                return name
        return None

    def _drag_resize(self, pos: QPointF) -> None:
        r = self._resize
        dx = r.press.x() - pos.x()  # dragging left makes it wider (right on macOS)
        dy = r.press.y() - pos.y()  # dragging up makes it taller
        if r.drag == "width":
            grow = {g.Anchor.RIGHT: dx, g.Anchor.LEFT: -dx}.get(self._options.anchor, 2 * dx)
            dims = g.Dims(r.start.width + grow, r.start.height)
        else:
            dims = g.Dims(r.start.width, r.start.height + 2 * dy)
        if dims != self._dims:
            # Follow the mouse, but ease the snap into (or out of) a circle.
            self.set_dims(dims, instant=dims.is_circle == self._dims.is_circle)

    def _update_chip(self) -> None:
        if not self.resizing:
            return
        rect = self._target_rect(self._clock())
        if rect is None:
            return
        if self._chip is None:
            self._chip = ResizeChip(self._palette)
            self._chip.reset.connect(self.reset_size)
            self._chip.cancel.connect(self.cancel_resize)
            self._chip.done.connect(self.finish_resize)
        # where the pill will be once it settles at its new size
        target = QRectF(rect)
        shown = self.shown_dims()
        target.setHeight(shown.height)
        target.moveTop((self.height() - shown.height) / 2)
        self._chip.show_size(shown.width, shown.height, self._global(target))

    # ---- layout & animation ------------------------------------------------------
    def _target_width(self, m: PillModel, models: list[PillModel]) -> float:
        dims = self.shown_dims()
        if self.resizing and m.session_id == self._resize.target:
            return dims.full
        # A pill that needs you stays at the size the user set (Manasvi, 2026-11-17:
        # "leave it in the size it was set on"): a circle opens to that width,
        # never wider. (A circle-sized pill opens to MIN_WIDTH, so text fits.)
        wide = min(g.fit_wide(self._room, len(models), dims), dims.text_width)
        return g.target_width(
            m.kind is PillKind.NEEDS_YOU,
            self._sessions >= 2,
            self._options.expand_needs_you,
            wide,
            done=m.kind is PillKind.DONE,
            dims=dims,
        )

    def _retarget(self, *, instant: bool = False) -> None:
        now = self._clock()
        for m in self._last_models:
            item = self._items.get(m.session_id)
            if item is not None and not item.leaving:
                item.width.set(self._target_width(m, self._last_models), now,
                               instant=instant or self._options.reduced_motion)
        self._relayout(instant=instant)

    def _relayout(self, *, instant: bool = False) -> None:
        now = self._clock()
        # Leaving pills stay where they are while they fade; the rest close the gap.
        live = [self._items[i] for i in self._order if not self._items[i].leaving]
        targets = [i.width.target for i in live]
        target_window = g.window_width(targets) if targets else 0.0
        if self.resizing:
            # Room for the widest pill the user could drag to, so the window
            # never resizes under the mouse.
            widest = [g.MAX_WIDTH if i.model.session_id == self._resize.target else w
                      for i, w in zip(live, targets, strict=True)]
            spare = g.MAX_WIDTH if self._options.anchor is g.Anchor.CENTER else 0.0
            target_window = max(target_window, g.window_width(widest) + spare)
        # Fit both the old and the new layout until the animation ends.
        container = max(target_window, float(self._window_w))
        xs = g.layout_row(targets, self._options.anchor, container)
        self._place(int(round(container)))
        for item, x in zip(live, xs, strict=True):
            if not item.placed:
                item.x.set(x, now, instant=True)  # a new pill fades in where it belongs
                item.placed = True
            else:
                item.x.set(x, now, instant=instant or self._options.reduced_motion)
        self._start_frames()

    def _place(self, width: int) -> None:
        width = max(1, width)
        if self._options.anchor is g.Anchor.RIGHT:
            left = self._anchor.x() - width
        elif self._options.anchor is g.Anchor.LEFT:
            left = self._anchor.x() - int(g.MARGIN)
        else:
            left = self._anchor.x() - width // 2
        top = self._anchor.y() - self.height() // 2
        moved_by = self.x() - left
        if moved_by and self._window_w:
            # The window's left edge moved: shift pills so nothing jumps on screen.
            for item in self._items.values():
                item.x.shift(moved_by)
        self._window_w = width
        self.setGeometry(QRect(left, top, width, self.height()))

    def _animating(self, now: float) -> bool:
        resize_moving = self._resize is not None and self._resize.grips.running(now)
        return resize_moving or self._height.running(now) or any(
            i.width.running(now) or i.opacity.running(now) or i.edge.running(now)
            or i.x.running(now)
            for i in self._items.values()
        )

    def _glowing(self) -> bool:
        return self._options.glow and not self._options.reduced_motion and any(
            i.model.kind is PillKind.NEEDS_YOU and not i.leaving for i in self._items.values()
        )

    def _start_frames(self) -> None:
        if not self._frame.isActive():
            self._frame.start()
        self.update()

    def _tick(self) -> None:
        now = self._clock()
        if self._animating(now):
            self.update()
            return
        if self._resize is not None and self._resize.ending:
            self._resize = None  # the grips have faded out
        # Everything settled (a glow may go on): drop pills that faded out and
        # shrink the window to fit (not while resizing: the user is dragging).
        if not self._glowing():
            self._frame.stop()
        gone = [sid for sid, i in self._items.items() if i.leaving]
        for sid in gone:
            del self._items[sid]
            self._order.remove(sid)
        if self._resize is None and (
            gone or self.width() != int(round(self._settled_width()))
        ):
            self._relayout_settled()
        self.update()

    def _settled_width(self) -> float:
        widths = [self._items[i].width.target for i in self._order]
        return g.window_width(widths) if widths else 1.0

    def _relayout_settled(self) -> None:
        now = self._clock()
        width = self._settled_width()
        xs = g.layout_row([self._items[i].width.target for i in self._order],
                          self._options.anchor, width)
        self._place(int(round(width)))
        for sid, x in zip(self._order, xs, strict=True):
            self._items[sid].x.set(x, now, instant=True)

    # ---- painting ----------------------------------------------------------------
    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt naming)
        now = self._clock()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        grips = self._resize.grips.value(now) if self._resize is not None else 0.0
        for sid in self._order:
            item = self._items[sid]
            rect = self._rect(item, now)
            glow = motion.glow(now, item.needs_you_since) if self._glowing() else (
                1.0 if item.model.kind is PillKind.NEEDS_YOU and self._options.glow else 0.0
            )
            is_target = self._resize is not None and sid == self._resize.target
            look = PillLook(
                morph=g.morph_of(rect.width(), self._dims_for_morph(rect.height())),
                opacity=item.opacity.value(now),
                edge=item.edge.value(now),
                glow=glow,
                show_dot=self._options.dot,
                show_glow=self._options.glow,
                hovered=sid == self._hovered and not self.resizing,
                resizing=grips if is_target else 0.0,
            )
            paint_pill(p, rect, item.model, look, self._palette,
                       Fonts.for_height(rect.height()))
            if is_target and grips > 0:
                self._paint_grips(p, rect, grips)
        p.end()

    def _dims_for_morph(self, height: float) -> g.Dims:
        shown = self.shown_dims()
        return g.Dims(shown.text_width, height, min_height=shown.min_height)

    def _paint_grips(self, p: QPainter, rect: QRectF, alpha: float) -> None:
        p.save()
        p.setOpacity(alpha)
        accent = QColor(self._palette.working)
        for name, grip in self._grips(rect).items():
            held = self._resize is not None and self._resize.drag == name
            grip = grip.adjusted(-1, -1, 1, 1) if held else grip
            p.setPen(QPen(qcolor(self._palette.surface), 2.5))
            p.setBrush(accent)
            radius = min(grip.width(), grip.height()) / 2
            p.drawRoundedRect(grip, radius, radius)
        p.restore()

    # ---- mouse ------------------------------------------------------------------
    def _rect(self, item: _Item, now: float) -> QRectF:
        h = self._height.value(now)
        return QRectF(item.x.value(now), (self.height() - h) / 2, item.width.value(now), h)

    def _global(self, rect: QRectF) -> QRect:
        return QRect(self.mapToGlobal(rect.topLeft().toPoint()), rect.size().toSize())

    def _item_at(self, pos: QPointF) -> _Item | None:
        now = self._clock()
        for sid in reversed(self._order):
            item = self._items[sid]
            if not item.leaving and self._rect(item, now).contains(pos):
                return item
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._hide_card()
        if self.resizing:
            grip = self._grip_at(event.position())
            if grip is not None and event.button() == Qt.MouseButton.LeftButton:
                self._resize.drag = grip
                self._resize.press = event.position()
                self._resize.start = self._dims
                self.update()
            return
        if event.button() == Qt.MouseButton.RightButton:
            item = self._item_at(event.position())
            if item is not None:
                rect = self._rect(item, self._clock())
                self.menu_requested.emit(item.model.session_id, self._global(rect))
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.globalPosition().toPoint()
            self._dragging = False

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.resizing:
            if self._resize.drag is not None:
                self._drag_resize(event.position())
                return
            grip = self._grip_at(event.position())
            if grip == "width":
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif grip == "height":
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            else:
                self.unsetCursor()
            return
        if self._press is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._press
            if self._dragging or delta.manhattanLength() > DRAG_THRESHOLD:
                self._dragging = True
                self._hide_card()
                self._press = event.globalPosition().toPoint()
                self._anchor += delta
                self.move(self.pos() + delta)
            return
        item = self._item_at(event.position())
        sid = item.model.session_id if item else None
        if sid != self._hovered:
            self._hovered = sid
            self.update()
        if item is not None:
            self._show_card(item)
        elif self._card is not None:
            self._card.hide_soon()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.resizing:
            if self._resize.drag is not None:
                self._resize.drag = None
                self.update()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._dragging:
            self.moved.emit(self.anchor())
        else:
            item = self._item_at(event.position())
            if item is not None:
                self.clicked.emit(item.model.session_id)
        self._press = None
        self._dragging = False

    def leaveEvent(self, _event) -> None:  # noqa: N802
        if self._hovered is not None:
            self._hovered = None
            self.update()
        if self._card is not None:
            self._card.hide_soon()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._hide_card()
        if self._chip is not None:
            self._chip.hide()
        super().hideEvent(event)

    # ---- hover card ---------------------------------------------------------------
    def _show_card(self, item: _Item) -> None:
        if self._card is None:
            self._card = HoverCard(self._palette)
        self._card.show_for(item.model, self._global(self._settled_rect(item)),
                            show_folder=self._title_is_shared(item))
        self._hover_watch.start()

    def _title_is_shared(self, item: _Item) -> bool:
        """The folder is only worth a line when two sessions have the same name
        (Manasvi, 2026-11-17: "no need to show the folder location always")."""
        return any(other is not item and not other.leaving
                   and other.model.title == item.model.title
                   for other in self._items.values())

    def _refresh_card(self) -> None:
        """Keep the card's text current (the % and elapsed time change).

        Only updates it: it must never cancel a pending hide, or a busy session
        (new events every second) kept the card up after the mouse left.
        """
        if self._card is None or self._card.session is None:
            return
        item = self._items.get(self._card.session)
        if item is None or item.leaving or self._hovered != self._card.session:
            self._card.hide_soon()
        else:
            self._card.refresh(item.model, self._global(self._settled_rect(item)))

    def _settled_rect(self, item: _Item) -> QRectF:
        # Where the pill will settle, so the card doesn't jump after a morph.
        rect = self._rect(item, self._clock())
        rect.setWidth(item.width.target)
        rect.moveLeft(item.x.target)
        return rect

    def _check_hover(self) -> None:
        """Backstop for a missed leave event (Windows can skip it when the mouse
        leaves through the window's see-through margin): hide the card once the
        cursor is no longer over the hovered pill."""
        item = self._items.get(self._hovered) if self._hovered else None
        over = item is not None and self._global(self._rect(item, self._clock())).adjusted(
            -2, -2, 2, 2).contains(self._cursor_pos())
        if not over:
            self._hover_watch.stop()
            self.leaveEvent(None)

    def _hide_card(self) -> None:
        self._hover_watch.stop()
        if self._card is not None:
            self._card.hide_now()


def tooltip_html(model: PillModel) -> str:
    """Plain-text summary used by the tray and tests (the pill uses HoverCard)."""
    t = model.tooltip
    lines = []
    if t.prompt:
        lines.append(f"<b>{html.escape(t.prompt)}</b>")
    if model.kind is PillKind.LIMITED:
        lines.append(html.escape(t.note or model.detail))
    elif model.kind is PillKind.NEEDS_YOU:
        lines.append(html.escape(model.detail))
    elif t.step:
        lines.append(html.escape(t.step))
    lines.append(html.escape(t.elapsed))
    if t.folder:
        lines.append(f"<span style='opacity:.7'>{html.escape(t.folder)}</span>")
    return "<br>".join(lines)
