"""Add TaskPill's hooks to Claude Code's settings.json, and take them out again.

What gets added, for each event we listen to (example for PreToolUse):

    "hooks": {
      "PreToolUse": [
        {"matcher": "*",
         "hooks": [{"type": "command",
                    "command": "C:\\Program Files\\TaskPill\\taskpill-hook.exe",
                    "args": ["--app", "C:\\Program Files\\TaskPill\\TaskPill.exe",
                             "--taskpill-hook"],
                    "async": true, "timeout": 10}]}
      ]
    }

Safety rules:
* A timestamped backup is made before every change (the newest 3 are kept).
* The file is written atomically. If it isn't valid JSON, or its shape is
  unexpected, nothing is written and ``SettingsFileError`` is raised.
* Everything that isn't ours is kept exactly as it was. Our entries are found
  by the ``--taskpill-hook`` marker, so installing twice changes nothing.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from taskpill.adapters.atomic import write_text_atomic

MARKER = "--taskpill-hook"
BACKUP_PREFIX = ".taskpill-backup-"
KEEP_BACKUPS = 3
HOOK_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class HookCommand:
    """How Claude Code should start the hook helper (exec form, no shell)."""

    command: str
    args: tuple[str, ...] = ()


@dataclass(frozen=True)
class _EventSpec:
    name: str
    matcher: str | None = None  # None → no matcher key (event has no matchers)
    run_async: bool = True


# SessionEnd stays synchronous: async hooks may be killed while Claude exits,
# and then the pill would never learn that the session ended.
EVENTS: tuple[_EventSpec, ...] = (
    _EventSpec("SessionStart"),
    _EventSpec("UserPromptSubmit"),
    _EventSpec("PreToolUse", matcher="*"),
    _EventSpec("PostToolUse", matcher="*"),
    _EventSpec("PermissionRequest", matcher="*"),
    _EventSpec("Notification"),
    _EventSpec("Stop"),
    _EventSpec("StopFailure"),
    _EventSpec("SessionEnd", run_async=False),
)


class SettingsFileError(Exception):
    """settings.json can't be changed safely; it was left untouched."""


@dataclass
class ChangeResult:
    changed: bool
    backup: Path | None = None
    events: list[str] = field(default_factory=list)


class HooksInstaller:
    def __init__(
        self,
        settings_path: Path,
        hook_command: HookCommand,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._path = settings_path
        self._hook = hook_command
        self._now = now

    # ---- queries ---------------------------------------------------------
    def is_installed(self) -> bool:
        settings = self._load()
        hooks = settings.get("hooks", {})
        return all(_has_ours(hooks.get(spec.name)) for spec in EVENTS)

    # ---- commands --------------------------------------------------------
    def install(self) -> ChangeResult:
        settings = self._load()
        hooks = settings.setdefault("hooks", {})
        before = json.dumps(settings, sort_keys=True)

        for spec in EVENTS:
            groups = _strip_ours(hooks.get(spec.name, []))
            groups.append(self._group(spec))
            hooks[spec.name] = groups

        if json.dumps(settings, sort_keys=True) == before:
            return ChangeResult(changed=False)
        backup = self._save(settings)
        return ChangeResult(changed=True, backup=backup, events=[s.name for s in EVENTS])

    def uninstall(self) -> ChangeResult:
        if not self._path.exists():
            return ChangeResult(changed=False)
        settings = self._load()
        hooks = settings.get("hooks")
        if not hooks:
            return ChangeResult(changed=False)

        removed: list[str] = []
        for name in list(hooks):
            groups = hooks[name]
            if not _has_ours(groups):
                continue
            kept = _strip_ours(groups)
            removed.append(name)
            if kept:
                hooks[name] = kept
            else:
                del hooks[name]
        if not removed:
            return ChangeResult(changed=False)
        if not hooks:
            del settings["hooks"]
        backup = self._save(settings)
        return ChangeResult(changed=True, backup=backup, events=removed)

    # ---- internals -------------------------------------------------------
    def _group(self, spec: _EventSpec) -> dict[str, Any]:
        handler: dict[str, Any] = {
            "type": "command",
            "command": self._hook.command,
            "args": [*self._hook.args, MARKER],
            "timeout": HOOK_TIMEOUT_SECONDS,
        }
        if spec.run_async:
            handler["async"] = True
        group: dict[str, Any] = {}
        if spec.matcher is not None:
            group["matcher"] = spec.matcher
        group["hooks"] = [handler]
        return group

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            text = self._path.read_text(encoding="utf-8-sig")
        except OSError as e:
            raise SettingsFileError(f"can't read {self._path}: {e}") from e
        if not text.strip():
            return {}
        try:
            data = json.loads(text)
        except ValueError as e:
            raise SettingsFileError(f"{self._path} is not valid JSON: {e}") from e
        if not isinstance(data, dict):
            raise SettingsFileError(f"{self._path} must contain a JSON object")
        hooks = data.get("hooks")
        if hooks is not None and not isinstance(hooks, dict):
            raise SettingsFileError('"hooks" in settings.json must be an object')
        for name, groups in (hooks or {}).items():
            if not isinstance(groups, list):
                raise SettingsFileError(f'"hooks.{name}" in settings.json must be a list')
        return data

    def _save(self, settings: dict[str, Any]) -> Path | None:
        backup = self._backup()
        try:
            write_text_atomic(
                self._path, json.dumps(settings, indent=2, ensure_ascii=False) + "\n"
            )
        except BaseException:
            # Nothing changed, so the backup would only be clutter.
            if backup is not None:
                backup.unlink(missing_ok=True)
            raise
        return backup

    def _backup(self) -> Path | None:
        if not self._path.exists():
            return None
        stamp = self._now().strftime("%Y%m%d-%H%M%S-%f")
        backup = self._path.with_name(f"{self._path.name}{BACKUP_PREFIX}{stamp}")
        shutil.copy2(self._path, backup)
        old = sorted(self._path.parent.glob(f"{self._path.name}{BACKUP_PREFIX}*"))
        for extra in old[:-KEEP_BACKUPS]:
            extra.unlink(missing_ok=True)
        return backup


def _is_ours(handler: object) -> bool:
    if not isinstance(handler, dict):
        return False
    args = handler.get("args")
    if isinstance(args, list) and MARKER in args:
        return True
    command = handler.get("command")
    return isinstance(command, str) and MARKER in command


def _has_ours(groups: object) -> bool:
    if not isinstance(groups, list):
        return False
    return any(
        isinstance(g, dict) and any(_is_ours(h) for h in g.get("hooks", []) or [])
        for g in groups
    )


def _strip_ours(groups: list[Any]) -> list[Any]:
    """Copy of ``groups`` without our handlers; groups left empty are dropped."""
    kept: list[Any] = []
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
            kept.append(group)  # not ours and not understood: leave it alone
            continue
        handlers = [h for h in group["hooks"] if not _is_ours(h)]
        if len(handlers) == len(group["hooks"]):
            kept.append(group)
        elif handlers:
            kept.append({**group, "hooks": handlers})
    return kept
