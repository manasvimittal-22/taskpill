"""Hook events coming from Claude Code, parsed and validated.

The payload is whatever Claude Code writes to the hook's stdin, plus a
``pid_chain`` list added by our hook helper. Anything we don't understand is
rejected with ``InvalidEventError``, so the rest of the app only ever sees
clean, size-limited data.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

MAX_SESSION_ID = 200
MAX_PROMPT = 500
MAX_MESSAGE = 300
MAX_PATH = 1000
MAX_TOOL_NAME = 200
MAX_NOTIFICATION_TYPE = 50
MAX_ERROR_TYPE = 50
MAX_PID_CHAIN = 32


class InvalidEventError(ValueError):
    """The payload is not a hook event we can use."""


class EventType(Enum):
    SESSION_START = "SessionStart"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    PERMISSION_REQUEST = "PermissionRequest"
    NOTIFICATION = "Notification"
    STOP = "Stop"
    STOP_FAILURE = "StopFailure"
    SESSION_END = "SessionEnd"

    @classmethod
    def parse(cls, raw: object) -> EventType:
        for member in cls:
            if member.value == raw:
                return member
        raise InvalidEventError(f"unsupported hook event: {raw!r}")


@dataclass(frozen=True)
class HookEvent:
    session_id: str
    type: EventType
    cwd: str = ""
    prompt: str = ""
    message: str = ""
    notification_type: str = ""
    tool_name: str = ""
    tool_input: Mapping[str, Any] = field(default_factory=dict)
    pid_chain: tuple[int, ...] = ()
    # StopFailure only: the error type ("rate_limit", …) and Claude Code's error text
    error: str = ""
    error_text: str = ""

    @classmethod
    def from_payload(cls, payload: object) -> HookEvent:
        if not isinstance(payload, Mapping):
            raise InvalidEventError("payload must be a JSON object")

        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id.strip():
            raise InvalidEventError("session_id is required")
        if len(session_id) > MAX_SESSION_ID:
            raise InvalidEventError("session_id is too long")

        tool_input = payload.get("tool_input")
        return cls(
            session_id=session_id,
            type=EventType.parse(payload.get("hook_event_name")),
            cwd=_text(payload.get("cwd"), MAX_PATH),
            prompt=_text(payload.get("prompt"), MAX_PROMPT),
            message=_text(payload.get("message"), MAX_MESSAGE),
            notification_type=_text(payload.get("notification_type"), MAX_NOTIFICATION_TYPE),
            tool_name=_text(payload.get("tool_name"), MAX_TOOL_NAME),
            tool_input=tool_input if isinstance(tool_input, Mapping) else {},
            pid_chain=_pid_chain(payload.get("pid_chain")),
            error=_text(payload.get("error"), MAX_ERROR_TYPE),
            error_text=_text(payload.get("last_assistant_message"), MAX_MESSAGE)
            or _text(payload.get("error_details"), MAX_MESSAGE),
        )


def _text(value: object, limit: int) -> str:
    """Return a clean single string, cut to ``limit`` characters."""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if len(value) > limit:
        return value[: limit - 1].rstrip() + "…"
    return value


def _pid_chain(value: object) -> tuple[int, ...]:
    if not isinstance(value, list | tuple):
        return ()
    pids = [p for p in value if isinstance(p, int) and not isinstance(p, bool) and p > 0]
    return tuple(pids[:MAX_PID_CHAIN])
