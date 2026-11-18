"""Write files so they are either fully old or fully new, never half-written."""

from __future__ import annotations

import contextlib
import os
import tempfile
import time
from pathlib import Path

# On Windows, replacing a file fails with "Access is denied" while another
# program (Claude Code, VS Code's file watcher, an antivirus) has it open for a
# moment. Seen live on 2026-11-17. A few short retries get past it.
REPLACE_TRIES = 8
REPLACE_WAIT = 0.05


def _replace(src: Path, dst: Path, sleep=time.sleep) -> None:
    for attempt in range(REPLACE_TRIES):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == REPLACE_TRIES - 1:
                raise
            sleep(REPLACE_WAIT * (attempt + 1))


def write_text_atomic(path: Path, text: str, *, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if private and os.name == "posix":
            os.chmod(tmp, 0o600)
        _replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
