"""Draw TaskPill's app icon and write it as a multi-size .ico (and a 512 px PNG).

    python packaging/make_icon.py packaging/taskpill.ico
    python packaging/make_icon.py build/taskpill.iconset   (macOS: then `iconutil -c icns`)

Big sizes: a slate rounded square holding a capsule whose violet edge runs
70% of the way round (the pill's "edge is the progress" idea). Small sizes
(≤ 32 px): the tray's simpler ring, which stays readable when tiny.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen, QPolygonF

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from taskpill.ui import geometry as g  # noqa: E402
from taskpill.ui.theme import DARK  # noqa: E402

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    tile = QRectF(0, 0, size, size).adjusted(size * 0.04, size * 0.04, -size * 0.04, -size * 0.04)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(DARK.surface))
    p.drawRoundedRect(tile, size * 0.22, size * 0.22)

    violet = QColor(DARK.working)
    track = QColor("#FFFFFF")
    track.setAlphaF(0.22)
    if size <= 32:
        stroke = max(1.6, size / 9)
        r = QRectF(size * 0.24, size * 0.24, size * 0.52, size * 0.52)
        p.setPen(QPen(track, stroke))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(r)
        p.setPen(QPen(violet, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(r, 90 * 16, -270 * 16)
    else:
        w, h = size * 0.70, size * 0.30
        x0, y0 = (size - w) / 2, (size - h) / 2
        stroke = size * 0.045
        p.setPen(QPen(track, stroke * 0.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(x0, y0, w, h), h / 2, h / 2)
        pts = g.capsule_polyline(w, h, 0.70, inset=0, step=max(1.0, size / 128))
        pen = QPen(violet, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolyline(QPolygonF([QPointF(x0 + x, y0 + y) for x, y in pts]))
    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


def write_ico(path: Path, images: list[tuple[int, bytes]]) -> None:
    """ICO with PNG-compressed entries (supported since Windows Vista)."""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, blob in images:
        dim = 0 if size >= 256 else size  # 0 means 256
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        blobs += blob
        offset += len(blob)
    path.write_bytes(header + entries + blobs)


# The PNGs a macOS .iconset folder needs: icon_<n>x<n>.png and the @2x versions.
ICONSET = [(16, "16x16"), (32, "16x16@2x"), (32, "32x32"), (64, "32x32@2x"),
           (128, "128x128"), (256, "128x128@2x"), (256, "256x256"), (512, "256x256@2x"),
           (512, "512x512"), (1024, "512x512@2x")]


def write_iconset(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for size, name in ICONSET:
        draw(size).save(str(folder / f"icon_{name}.png"))


def main(argv: list[str]) -> int:
    out = Path(argv[1] if len(argv) > 1 else "packaging/taskpill.ico")
    app = QGuiApplication.instance() or QGuiApplication(argv[:1])
    if out.suffix == ".iconset":
        write_iconset(out)
        del app
        print(f"wrote {out} ({len(ICONSET)} PNGs)")
        return 0
    write_ico(out, [(s, png_bytes(draw(s))) for s in SIZES])
    draw(512).save(str(out.with_suffix(".png")))
    del app
    print(f"wrote {out} ({len(SIZES)} sizes) and {out.with_suffix('.png')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
