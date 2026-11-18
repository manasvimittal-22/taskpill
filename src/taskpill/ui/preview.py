"""Render every pill state to a PNG, on taskbar-like backgrounds, for design review.

    python -m taskpill.ui.preview out.png [--scale 2]
"""

from __future__ import annotations

import argparse
import sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter

from taskpill.ui import geometry as g
from taskpill.ui.pill_painter import Fonts, PillLook, paint_pill
from taskpill.ui.theme import DARK, LIGHT, Palette, ui_font
from taskpill.ui.view_model import PillKind, PillModel, Tooltip

TIP = Tooltip(prompt="", step="", elapsed="", folder="")


def model(kind: PillKind, detail: str, percent: int, title: str = "taskpill") -> PillModel:
    return PillModel("x", title, detail, kind, percent, TIP)


ROWS: list[tuple[str, list[tuple[PillModel, PillLook]]]] = [
    ("Working 42%", [(model(PillKind.WORKING, "Editing login.py", 42), PillLook(edge=0.42))]),
    ("Working 7%", [(model(PillKind.WORKING, "Thinking", 7), PillLook(edge=0.07))]),
    (
        "Needs you, glow peak",
        [
            (
                model(PillKind.NEEDS_YOU, "Needs permission to run npm install", 38),
                PillLook(edge=0.38, glow=1.0, show_dot=True),
            )
        ],
    ),
    ("Done", [(model(PillKind.DONE, "Done", 100), PillLook(edge=1.0))]),
    (
        "Stale",
        [(model(PillKind.STALE, "Running pytest", 81), PillLook(edge=0.81))],
    ),
    (
        "Long names",
        [
            (
                model(PillKind.WORKING, "Running npm run build --workspaces --if-present", 63,
                      title="a-really-long-project-folder-name"),
                PillLook(edge=0.63),
            )
        ],
    ),
    (
        "Three sessions",
        [
            (model(PillKind.WORKING, "", 42), PillLook(morph=0, edge=0.42)),
            (model(PillKind.NEEDS_YOU, "", 17), PillLook(morph=0, edge=0.17, glow=0.6,
                                                         show_dot=True)),
            (model(PillKind.DONE, "", 100), PillLook(morph=0, edge=1.0)),
        ],
    ),
    (
        "Morph 75%",
        [(model(PillKind.WORKING, "Editing login.py", 42), PillLook(morph=0.75, edge=0.42))],
    ),
    (
        "Morph 50%",
        [(model(PillKind.WORKING, "Editing login.py", 42), PillLook(morph=0.5, edge=0.42))],
    ),
    (
        "Morph 20%",
        [(model(PillKind.WORKING, "Editing login.py", 42), PillLook(morph=0.2, edge=0.42))],
    ),
]

TASKBARS = [("Windows dark taskbar", "#1F1F1F", DARK), ("Windows light taskbar", "#EEEEEE", LIGHT)]


def render(path: str, scale: float) -> None:
    label_w, row_h, col_w = 170.0, 52.0, g.FULL_WIDTH + 60
    width = label_w + col_w * len(TASKBARS)
    height = 40 + row_h * len(ROWS)
    image = QImage(int(width * scale), int(height * scale), QImage.Format.Format_ARGB32)
    image.fill(QColor("#FFFFFF"))
    p = QPainter(image)
    p.scale(scale, scale)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    fonts = Fonts()
    label_font = ui_font(12)
    head_font = ui_font(12, QFont.Weight.DemiBold)

    for c, (name, bg, pal) in enumerate(TASKBARS):
        x0 = label_w + c * col_w
        p.fillRect(QRectF(x0, 0, col_w, height), QColor(bg))
        p.setFont(head_font)
        p.setPen(QColor(pal.text))
        p.drawText(QRectF(x0 + 16, 8, col_w, 24), Qt.AlignmentFlag.AlignVCenter, name)
        for r, (_label, pills) in enumerate(ROWS):
            _draw_row(p, pills, x0 + 20, 40 + r * row_h + (row_h - g.HEIGHT) / 2, pal, fonts)

    p.setFont(label_font)
    p.setPen(QColor("#333333"))
    for r, (label, _) in enumerate(ROWS):
        p.drawText(QRectF(12, 40 + r * row_h, label_w, row_h), Qt.AlignmentFlag.AlignVCenter,
                   label)
    p.end()
    image.save(path)


def _draw_row(p, pills, x, y, pal: Palette, fonts: Fonts) -> None:
    for m, look in pills:
        w = g.pill_width(look.morph)
        paint_pill(p, QRectF(x, y, w, g.HEIGHT), m, look, pal, fonts)
        x += w + g.GAP


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--scale", type=float, default=2.0)
    args = parser.parse_args(argv)
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    render(args.out, args.scale)
    del app
    return 0


if __name__ == "__main__":
    sys.exit(main())
