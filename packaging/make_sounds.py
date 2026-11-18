"""Make TaskPill's two sounds (docs/design.md → Sounds). Stdlib only.

    python packaging/make_sounds.py        writes src/taskpill/sounds/*.wav

Both are short, quiet, two-note chimes made of sine tones with a soft mallet
attack and a natural decay, so nothing is borrowed from anyone else:

* needs_you.wav: rising (E5 → A5), like a question. About 0.45 s.
* done.wav: falling (A5 → E5), like something settling. About 0.55 s.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

RATE = 44100
PEAK = 0.22  # about -13 dBFS: quiet, never startling
OUT = Path(__file__).resolve().parents[1] / "src" / "taskpill" / "sounds"


def note(freq: float, start: float, length: float, level: float = 1.0) -> list[tuple[int, float]]:
    """(sample index, value) pairs for one soft mallet note."""
    out = []
    first = int(start * RATE)
    for i in range(int(length * RATE)):
        t = i / RATE
        attack = min(1.0, t / 0.006)  # 6 ms: soft, no click
        decay = math.exp(-t / (length * 0.32))
        # the fundamental, a quiet octave and a faint fifth above: a warm, glassy tone
        tone = (math.sin(2 * math.pi * freq * t)
                + 0.18 * math.sin(2 * math.pi * 2 * freq * t) * math.exp(-t / 0.05)
                + 0.06 * math.sin(2 * math.pi * 3 * freq * t) * math.exp(-t / 0.03))
        out.append((first + i, level * attack * decay * tone))
    return out


def render(notes: list[list[tuple[int, float]]], seconds: float) -> bytes:
    buf = [0.0] * int(seconds * RATE)
    for n in notes:
        for i, v in n:
            if i < len(buf):
                buf[i] += v
    top = max(abs(v) for v in buf) or 1.0
    fade = int(0.02 * RATE)  # the last 20 ms fade to silence: no click at the end
    frames = bytearray()
    for i, v in enumerate(buf):
        tail = min(1.0, (len(buf) - i) / fade)
        frames += struct.pack("<h", int(v / top * PEAK * tail * 32767))
    return bytes(frames)


def write(name: str, data: bytes) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(data)
    return path


E5, A5 = 659.25, 880.0

SOUNDS = {
    "needs_you.wav": ([note(E5, 0.0, 0.30, 0.85), note(A5, 0.11, 0.34)], 0.46),
    "done.wav": ([note(A5, 0.0, 0.32, 0.8), note(E5, 0.13, 0.42)], 0.56),
}


def main() -> None:
    for name, (notes, seconds) in SOUNDS.items():
        print(write(name, render(notes, seconds)))


if __name__ == "__main__":
    main()
