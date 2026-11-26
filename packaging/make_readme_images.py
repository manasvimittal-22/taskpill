"""Render the README's pictures with the app's own painter (docs/design.md → README).

    python packaging/make_readme_images.py      writes docs/images/*.png

Every pill, card and window here is drawn by the real code, so the pictures can
never drift from what TaskPill looks like. Run it on Windows (real fonts; the
offscreen platform has none) after any design change.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from taskpill.adapters.settings_store import Settings  # noqa: E402
from taskpill.ui import geometry as g  # noqa: E402
from taskpill.ui.pill_row import PillRow, RowOptions  # noqa: E402
from taskpill.ui.popups import HoverCard  # noqa: E402
from taskpill.ui.settings_window import SettingsWindow  # noqa: E402
from taskpill.ui.theme import DARK, LIGHT, Palette, ui_font  # noqa: E402
from taskpill.ui.view_model import PillKind, PillModel, Tooltip  # noqa: E402

OUT = ROOT / "docs" / "images"
SCALE = 2  # crisp on high-DPI screens; GitHub scales the image down

TASKBAR_DARK, TASKBAR_LIGHT = "#1C1C1C", "#EEEEEE"
DESKTOP_DARK = ("#1B1E27", "#12141A")
DESKTOP_LIGHT = ("#DCE3EE", "#C9D2E0")

PROMPT = "Fix the login bug where the session cookie expires too early"
LIMIT = "Claude usage limit reached. Your limit will reset at 3pm."


def model(sid, kind, detail, pct, title="taskpill", note=""):
    tip = Tooltip(PROMPT, detail, "Running for 3 min" if kind is PillKind.WORKING
                  else "Ran for 41 min", "C:/code/taskpill", note=note)
    return PillModel(sid, title, detail, kind, pct, tip)


WORKING = model("w", PillKind.WORKING, "Editing login.py", 42)
NEEDS = model("n", PillKind.NEEDS_YOU, "Needs permission to run npm install", 38)
DONE = model("d", PillKind.DONE, "Done", 100)
LIMITED = model("l", PillKind.LIMITED, "Out of usage", 63, note=LIMIT)


class _Clock:
    t = 100.0

    def __call__(self):
        return self.t


def pills(pal: Palette, models: list[PillModel], expand: bool = False) -> QImage:
    """The real pill row, settled, as an image (with its transparent margin)."""
    clock = _Clock()
    row = PillRow(RowOptions(expand_needs_you=expand), pal, clock=clock)
    row.set_anchor(QPoint(1200, 600))
    row.set_models(models)
    clock.t += 5
    row._tick()
    image = row.grab().toImage()
    row.deleteLater()
    return image


def card(pal: Palette, m: PillModel) -> QImage:
    c = HoverCard(pal)
    c._fill(m, False)
    c.adjustSize()
    return c.grab().toImage()


def logical(image: QImage) -> tuple[float, float]:
    r = image.devicePixelRatio()
    return image.width() / r, image.height() / r


def canvas(w: int, h: int) -> tuple[QImage, QPainter]:
    image = QImage(w * SCALE, h * SCALE, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.scale(SCALE, SCALE)
    return image, p


def rounded_clip(p: QPainter, w: float, h: float, radius: float = 14) -> None:
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
    p.setClipPath(path)


def taskbar(p: QPainter, w: float, top: float, dark: bool, clock_text=("4:12 PM", "11/17/2026"),
            chevron_x: float | None = None) -> float:
    """A plain Windows-11-like taskbar strip (no real app icons). Returns the x of
    the "^" arrow, which the pills sit next to."""
    h = 48
    p.fillRect(QRectF(0, top, w, h), QColor(TASKBAR_DARK if dark else TASKBAR_LIGHT))
    line = QColor(255, 255, 255, 18) if dark else QColor(0, 0, 0, 22)
    p.fillRect(QRectF(0, top, w, 1), line)
    ink = QColor("#E6E6E6" if dark else "#1A1A1A")
    # clock (two lines, right-aligned)
    p.setPen(ink)
    p.setFont(ui_font(11.5))
    right = w - 16
    p.drawText(QRectF(right - 90, top + 7, 90, 17), Qt.AlignmentFlag.AlignRight, clock_text[0])
    p.drawText(QRectF(right - 90, top + 24, 90, 17), Qt.AlignmentFlag.AlignRight, clock_text[1])
    # tray glyphs: wifi, speaker (simple strokes), then the ^ arrow
    pen = QPen(ink, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    cy = top + h / 2
    sx = right - 130
    p.drawLine(QPointF(sx, cy - 3), QPointF(sx + 3, cy - 3))  # speaker body
    p.drawLine(QPointF(sx + 3, cy - 3), QPointF(sx + 7, cy - 7))
    p.drawLine(QPointF(sx + 7, cy - 7), QPointF(sx + 7, cy + 7))
    p.drawLine(QPointF(sx + 7, cy + 7), QPointF(sx + 3, cy + 3))
    p.drawLine(QPointF(sx + 3, cy + 3), QPointF(sx, cy + 3))
    p.drawLine(QPointF(sx, cy + 3), QPointF(sx, cy - 3))
    p.drawArc(QRectF(sx + 6, cy - 5, 8, 10), -50 * 16, 100 * 16)
    wx = sx - 30
    for r in (3.0, 6.5, 10.0):
        p.drawArc(QRectF(wx - r, cy + 4 - r, 2 * r, 2 * r), 50 * 16, 80 * 16)
    ax = chevron_x if chevron_x is not None else wx - 34
    p.drawLine(QPointF(ax - 4.5, cy + 2.5), QPointF(ax, cy - 2.5))
    p.drawLine(QPointF(ax, cy - 2.5), QPointF(ax + 4.5, cy + 2.5))
    return ax


def place_row(p: QPainter, row: QImage, right_x: float, center_y: float) -> QRectF:
    w, h = logical(row)
    rect = QRectF(right_x - w + g.MARGIN, center_y - h / 2, w, h)
    p.drawImage(rect, row)
    return rect


def save(image: QImage, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    image.save(str(OUT / name))
    print(OUT / name)


# ---- the pictures ------------------------------------------------------------------------
def hero() -> None:
    """The pill on a taskbar, its hover card above it, on a calm dark desktop."""
    w, h = 900, 215
    image, p = canvas(w, h)
    rounded_clip(p, w, h)
    sky = QLinearGradient(0, 0, 0, h)
    sky.setColorAt(0, QColor(DESKTOP_DARK[0]))
    sky.setColorAt(1, QColor(DESKTOP_DARK[1]))
    p.fillRect(QRectF(0, 0, w, h), sky)
    top = h - 48
    arrow = taskbar(p, w, top, dark=True)
    row = pills(DARK, [WORKING])
    rect = place_row(p, row, arrow - 12, top + 24)
    c = card(DARK, WORKING)
    cw, ch = logical(c)
    pill_center = rect.right() - g.MARGIN - g.FULL_WIDTH / 2
    p.drawImage(QRectF(pill_center - cw / 2, top + 24 - 16 - 8 - ch + 6, cw, ch), c)
    p.end()
    save(image, "hero.png")


def states() -> None:
    """Every state, on a dark and a light taskbar."""
    rows = [("Working", [WORKING]), ("Needs you", [NEEDS]), ("Done", [DONE]),
            ("Out of usage", [LIMITED])]
    w, row_h = 900, 64
    h = row_h * len(rows) + 16
    image, p = canvas(w, h)
    rounded_clip(p, w, h)
    half = w / 2
    for col, (dark, pal) in enumerate(((True, DARK), (False, LIGHT))):
        x0 = col * half
        p.fillRect(QRectF(x0, 0, half, h), QColor(TASKBAR_DARK if dark else TASKBAR_LIGHT))
        for i, (label, ms) in enumerate(rows):
            cy = 8 + row_h * i + row_h / 2
            p.setPen(QColor("#8E949E" if dark else "#5E6573"))
            p.setFont(ui_font(12.5, QFont.Weight.DemiBold))
            p.drawText(QRectF(x0 + 22, cy - 10, 110, 20), Qt.AlignmentFlag.AlignVCenter, label)
            # the needs-you pill shown as a lone pill (its message inside)
            row = pills(pal, ms, expand=True)
            place_row(p, row, x0 + half - 18, cy)
    p.end()
    save(image, "states.png")


def sessions() -> None:
    """Several sessions at once collapse into circles: %, ?, ✓, pause."""
    w, h = 900, 96
    image, p = canvas(w, h)
    rounded_clip(p, w, h)
    sky = QLinearGradient(0, 0, 0, h)
    sky.setColorAt(0, QColor(DESKTOP_DARK[0]))
    sky.setColorAt(1, QColor(DESKTOP_DARK[1]))
    p.fillRect(QRectF(0, 0, w, h), sky)
    top = h - 48
    arrow = taskbar(p, w, top, dark=True)
    many = [model("a", PillKind.WORKING, "x", 42), model("b", PillKind.NEEDS_YOU, "x", 17),
            model("c", PillKind.DONE, "Done", 100), model("d", PillKind.LIMITED, "x", 63),
            model("e", PillKind.WORKING, "x", 8)]
    place_row(p, pills(DARK, many), arrow - 12, top + 24)
    p.end()
    save(image, "sessions.png")


def _status_glyph(p: QPainter, kind: str, center: QPointF, color: QColor) -> None:
    """Simple line glyphs in the spirit of VS Code's status icons (drawn, not its font)."""
    pen = QPen(color, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    x, y = center.x(), center.y()
    if kind == "working":  # a spinner arc
        p.drawArc(QRectF(x - 5, y - 5, 10, 10), 90 * 16, -270 * 16)
    elif kind == "needs":  # a bell
        path = QPainterPath()
        path.moveTo(x - 5, y + 3)
        path.cubicTo(x - 4, y - 1, x - 5, y - 6, x, y - 6)
        path.cubicTo(x + 5, y - 6, x + 4, y - 1, x + 5, y + 3)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(x - 1.5, y + 5), QPointF(x + 1.5, y + 5))
    elif kind == "done":  # a check
        p.drawLine(QPointF(x - 4.5, y), QPointF(x - 1.5, y + 3))
        p.drawLine(QPointF(x - 1.5, y + 3), QPointF(x + 4.5, y - 3.5))
    elif kind == "limited":  # a pause
        p.drawLine(QPointF(x - 2, y - 4), QPointF(x - 2, y + 4))
        p.drawLine(QPointF(x + 2, y - 4), QPointF(x + 2, y + 4))


def vscode() -> None:
    """VS Code's status bar with the TaskPill item in each state (drawn simply)."""
    rows = [("working", "taskpill 42%", None), ("needs", "taskpill needs you", "#A6740F"),
            ("limited", "taskpill out of usage", None), ("done", "taskpill done", None)]
    w, bar_h, gap = 900, 26, 10
    h = len(rows) * (bar_h + gap) + gap
    image, p = canvas(w, h)
    rounded_clip(p, w, h, 10)
    p.fillRect(QRectF(0, 0, w, h), QColor("#1F1F1F"))
    p.setFont(ui_font(12))
    soft = QColor("#9DA1A6")
    for i, (kind, text, bg) in enumerate(rows):
        top = gap + i * (bar_h + gap)
        bar = QRectF(0, top, w, bar_h)
        p.fillRect(bar, QColor("#181818"))
        p.setPen(soft)
        p.drawText(QRectF(14, top, 300, bar_h), Qt.AlignmentFlag.AlignVCenter,
                   "main    0 problems")
        tw = p.fontMetrics().horizontalAdvance(text) + 40
        item = QRectF(w - 16 - tw, top, tw, bar_h)
        if bg:
            p.fillRect(item, QColor(bg))
        ink = QColor("#FFFFFF") if bg else QColor("#E0E0E0")
        _status_glyph(p, kind, QPointF(item.left() + 14, item.center().y()), ink)
        p.setPen(ink)
        p.drawText(item.adjusted(26, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, text)
        x = item.left() - 18
        for other in ("Ln 12, Col 4", "UTF-8", "Python"):
            p.setPen(soft)
            ow = p.fontMetrics().horizontalAdvance(other)
            p.drawText(QRectF(x - ow, top, ow, bar_h), Qt.AlignmentFlag.AlignVCenter, other)
            x -= ow + 22
    p.end()
    save(image, "vscode.png")


MAC_BAR = 37  # a notched MacBook's menu bar, in points
MAC_NOTCH_W = 200
MAC_GAP = 8  # between the notch and the row (platform/base.py NOTCH_GAP)


def mac_pills(models: list[PillModel], dims: g.Dims) -> QImage:
    """The real row as macOS sets it up: grows right from the notch, fitted to the bar."""
    clock = _Clock()
    # expand_needs_you is off by default (Settings: "Open circles to show the message").
    row = PillRow(RowOptions(anchor=g.Anchor.LEFT, circle_by_default=True,
                             expand_needs_you=False), DARK, clock=clock, dims=dims)
    row.set_bar_height(round(MAC_BAR - 2 * max(2.0, MAC_BAR * 0.08)))
    row.set_anchor(QPoint(600, 600))
    row.set_models(models)
    clock.t += 5
    row._tick()
    image = row.grab().toImage()
    row.deleteLater()
    return image


def mac_bar(p: QPainter, w: float, notch_left: float) -> float:
    """A plain macOS-like menu bar, cropped to the notch and the right side: the notch,
    then simple status glyphs and a clock (no real icons, no logos). Returns the x where
    TaskPill's row starts."""
    h = MAC_BAR
    p.fillRect(QRectF(0, 0, w, h), QColor(24, 25, 30, 235))
    p.fillRect(QRectF(0, h - 1, w, 1), QColor(255, 255, 255, 14))
    notch = QPainterPath()
    notch.addRoundedRect(QRectF(notch_left, -12, MAC_NOTCH_W, h + 12), 11, 11)
    p.fillPath(notch, QColor("#000000"))
    ink = QColor("#E8E8EA")
    p.setPen(ink)
    p.setFont(ui_font(13))
    x = 18  # plain menu words left of the notch (no app name, no logo)
    for word in ("File", "Edit", "View", "Window"):
        ww = p.fontMetrics().horizontalAdvance(word)
        if x + ww > notch_left - 12:
            break
        p.drawText(QRectF(x, 0, ww, h), Qt.AlignmentFlag.AlignVCenter, word)
        x += ww + 20
    right = w - 16
    clock_text = "Thu 26 Nov  4:12 PM"
    tw = p.fontMetrics().horizontalAdvance(clock_text)
    p.drawText(QRectF(right - tw, 0, tw, h), Qt.AlignmentFlag.AlignVCenter, clock_text)
    pen = QPen(ink, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    cy = h / 2
    bx = right - tw - 46  # battery
    p.drawRoundedRect(QRectF(bx, cy - 5.5, 24, 11), 3, 3)
    p.fillRect(QRectF(bx + 2.5, cy - 3, 15, 6), ink)
    p.drawLine(QPointF(bx + 26.5, cy - 2), QPointF(bx + 26.5, cy + 2))
    wx = bx - 26  # wifi
    for r in (2.5, 6.0, 9.5):
        p.drawArc(QRectF(wx - r, cy + 5 - r, 2 * r, 2 * r), 50 * 16, 80 * 16)
    return notch_left + MAC_NOTCH_W + MAC_GAP


def mac_desktop(p: QPainter, w: float, h: float) -> None:
    sky = QLinearGradient(0, 0, w, h)
    sky.setColorAt(0, QColor("#2A2440"))
    sky.setColorAt(1, QColor("#141722"))
    p.fillRect(QRectF(0, 0, w, h), sky)


def place_row_left(p: QPainter, row: QImage, left_x: float, center_y: float) -> QRectF:
    w, h = logical(row)
    rect = QRectF(left_x - g.MARGIN, center_y - h / 2, w, h)
    p.drawImage(rect, row)
    return rect


def mac() -> None:
    """The pill in the Mac menu bar right of the notch, with its card under it."""
    w, h = 900, 142
    image, p = canvas(w, h)
    rounded_clip(p, w, h)
    mac_desktop(p, w, h)
    start = mac_bar(p, w, notch_left=150)
    rect = place_row_left(p, mac_pills([WORKING], g.DEFAULT), start, MAC_BAR / 2)
    c = card(DARK, WORKING)
    cw, ch = logical(c)
    pill_center = rect.left() + g.MARGIN + g.FULL_WIDTH / 2
    p.drawImage(QRectF(pill_center - cw / 2, MAC_BAR - 2, cw, ch), c)
    p.end()
    save(image, "mac.png")


def mac_sessions() -> None:
    """A Mac starts with circles: one session, then several."""
    w, h = 900, 44
    image, p = canvas(w, h)
    rounded_clip(p, w, h, 10)
    mac_desktop(p, w, h)
    start = mac_bar(p, w, notch_left=150)
    many = [model("a", PillKind.WORKING, "x", 42), model("b", PillKind.NEEDS_YOU, "x", 17),
            model("c", PillKind.DONE, "Done", 100), model("d", PillKind.LIMITED, "x", 63)]
    place_row_left(p, mac_pills(many, g.default_dims(True)), start, MAC_BAR / 2)
    p.end()
    save(image, "mac-sessions.png")


def settings() -> None:
    window = SettingsWindow(Settings(), DARK, connected=True)
    window.adjustSize()
    shot = window.grab().toImage()
    w, h = logical(shot)
    image, p = canvas(int(w), int(h))
    rounded_clip(p, w, h, 12)
    p.drawImage(QRectF(0, 0, w, h), shot)
    p.end()
    save(image, "settings.png")


def main() -> None:
    QApplication.instance() or QApplication(sys.argv[:1])
    hero()
    states()
    sessions()
    # vscode()  # the extension is on hold (2026-11-17); its picture isn't in the README
    settings()
    mac()
    mac_sessions()


if __name__ == "__main__":
    main()
