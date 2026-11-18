"""runtime.json: tells the hook helper (and the VS Code extension) how to reach the app.

Example contents:
    {"port": 51234, "token": "q3J…", "pid": 4120, "version": "0.1.0"}

The token is a fresh random secret every time the app starts. Only programs
that can read this file (your user account) can talk to the app.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from taskpill.adapters.atomic import write_text_atomic


@dataclass(frozen=True)
class RuntimeInfo:
    port: int
    token: str
    pid: int
    version: str


def write_runtime(path: Path, info: RuntimeInfo) -> None:
    write_text_atomic(path, json.dumps(asdict(info)) + "\n", private=True)


def read_runtime(path: Path) -> RuntimeInfo | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        info = RuntimeInfo(
            port=data["port"], token=data["token"], pid=data["pid"], version=data["version"]
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not (isinstance(info.port, int) and 0 < info.port < 65536 and isinstance(info.token, str)):
        return None
    return info


def remove_runtime_if_owned(path: Path, pid: int) -> None:
    """Delete runtime.json at exit, unless a newer app instance has replaced it."""
    info = read_runtime(path)
    if info is not None and info.pid == pid:
        with contextlib.suppress(OSError):
            path.unlink()
