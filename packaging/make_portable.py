"""Pack the built app folder into the portable .zip (called by build_windows.ps1).

    python packaging/make_portable.py <version>

Python's zipfile instead of PowerShell 5.1's Compress-Archive, which fails with
"access denied" on some PyInstaller files.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(version: str) -> Path:
    app = ROOT / "dist" / "TaskPill"
    target = ROOT / "dist" / f"TaskPill-{version}-portable.zip"
    target.unlink(missing_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(app.rglob("*")):
            if path.is_file():
                z.write(path, Path("TaskPill") / path.relative_to(app))
        # portable.txt: how to use it, and the marker that makes updates open the page
        z.write(ROOT / "packaging" / "portable.txt", Path("TaskPill") / "portable.txt")
    print(target)
    return target


if __name__ == "__main__":
    main(sys.argv[1])
