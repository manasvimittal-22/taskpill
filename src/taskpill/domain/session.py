"""One Claude Code session and its state machine.

    IDLE ──UserPromptSubmit──► WORKING ──PermissionRequest / question──► NEEDS_YOU
      ▲                          │  ▲                                     │
      │                          │  └────────── tool event ───────────────┘
      │                     Stop / StopFailure
      │                          ▼
      └──── acknowledge ───── DONE ──UserPromptSubmit / tool event──► WORKING

    WORKING ──StopFailure rate_limit / billing_error──► LIMITED ("Out of usage")
    LIMITED ──quota_auto_resume_fired / prompt / tool event──► WORKING
    LIMITED ──quota_auto_resume_stale──► NEEDS_YOU ("Usage is back: press Enter")
    LIMITED ──acknowledge (click)──► IDLE

Rules learned from how Claude Code sends events:
* IDLE sessions are hidden (registered at SessionStart, or after you click Done).
* ``Stop`` does not fire when you interrupt with Esc. The ``idle_prompt``
  notification that follows is our signal that the turn is over, so a working
  pill is hidden then. After Done it is ignored, so Done stays.
* SessionStart also fires on resume / after compaction: it never resets.
* Every transition method returns True when something visible changed.
"""

from __future__ import annotations

import os
from enum import Enum

from taskpill.domain.events import EventType, HookEvent
from taskpill.domain.progress import Progress, ProgressConfig
from taskpill.domain.steps import ASKING_TOOLS, describe_permission, describe_step

STALE_AFTER_SECONDS = 30 * 60

# notification_type values (Claude Code hooks docs, 2026-11).
_NEEDS_YOU_TYPES = {
    "permission_prompt",
    "elicitation_dialog",
    "elicitation_url_dialog",
    "agent_needs_input",
}
_IDLE_TYPE = "idle_prompt"

# A turn that failed because usage ran out (Manasvi, 2026-11-17: "when ran out of
# usage, show on pill"). Other StopFailure errors stay "Stopped with an error".
USAGE_ERRORS = {
    "rate_limit": "Out of usage",
    "billing_error": "Out of credits",
}
# After a claude.ai usage limit (Claude Code v2.1.234+).
_RESUMED = "quota_auto_resume_fired"  # Claude Code carried on by itself
_RESUME_NEEDS_ENTER = "quota_auto_resume_stale"  # the limit reset while asleep: press Enter
USAGE_BACK_MESSAGE = "Usage is back: press Enter to continue"


class SessionState(Enum):
    IDLE = "idle"
    WORKING = "working"
    NEEDS_YOU = "needs_you"
    DONE = "done"
    LIMITED = "limited"  # out of usage: calm, stays until Claude Code carries on or a click


_BUSY = (SessionState.WORKING, SessionState.NEEDS_YOU)


class Session:
    def __init__(
        self, session_id: str, now: float, progress_config: ProgressConfig | None = None
    ) -> None:
        self.session_id = session_id
        self.state = SessionState.IDLE
        self.cwd = ""
        self.prompt = ""
        self.step = ""
        self.message = ""
        self.pid_chain: tuple[int, ...] = ()
        self.created_at = now
        self.last_event_at = now
        self.task_started_at = now
        self.progress = Progress(progress_config)

    # ---- derived ---------------------------------------------------------
    @property
    def project_name(self) -> str:
        name = os.path.basename(self.cwd.rstrip("\\/").replace("\\", "/")) if self.cwd else ""
        return name or "Claude Code"

    @property
    def is_visible(self) -> bool:
        return self.state is not SessionState.IDLE

    def is_stale(self, now: float) -> bool:
        return (
            self.state is SessionState.WORKING
            and now - self.last_event_at >= STALE_AFTER_SECONDS
        )

    # ---- events ----------------------------------------------------------
    def apply(self, event: HookEvent, now: float) -> bool:
        """Apply one hook event. Returns True if anything visible changed."""
        self.last_event_at = now
        if event.cwd:
            self.cwd = event.cwd
        if event.pid_chain:
            self.pid_chain = event.pid_chain

        handler = {
            EventType.SESSION_START: self._on_session_start,
            EventType.USER_PROMPT_SUBMIT: self._on_prompt,
            EventType.PRE_TOOL_USE: self._on_tool,
            EventType.POST_TOOL_USE: self._on_tool,
            EventType.PERMISSION_REQUEST: self._on_permission_request,
            EventType.NOTIFICATION: self._on_notification,
            EventType.STOP: self._on_stop,
            EventType.STOP_FAILURE: self._on_stop_failure,
            EventType.SESSION_END: lambda _e, _n: False,  # the store removes the session
        }[event.type]
        return handler(event, now)

    def acknowledge(self) -> bool:
        """The user clicked a Done or Out-of-usage pill: hide it until the next prompt."""
        if self.state not in (SessionState.DONE, SessionState.LIMITED):
            return False
        self.state = SessionState.IDLE
        return True

    # ---- handlers --------------------------------------------------------
    def _on_session_start(self, _event: HookEvent, _now: float) -> bool:
        return False

    def _on_prompt(self, event: HookEvent, now: float) -> bool:
        self.state = SessionState.WORKING
        self.prompt = event.prompt
        self.step = "Thinking"
        self.message = ""
        self.task_started_at = now
        self.progress.start(now)
        return True

    def _on_tool(self, event: HookEvent, now: float) -> bool:
        self._ensure_working(now)

        if event.type is EventType.PRE_TOOL_USE and event.tool_name in ASKING_TOOLS:
            self._needs_you(ASKING_TOOLS[event.tool_name], now)
            return True

        self.state = SessionState.WORKING
        self.message = ""
        self.step = describe_step(event.tool_name, event.tool_input)
        if event.type is EventType.POST_TOOL_USE:
            self.progress.bump()
        return True

    def _on_permission_request(self, event: HookEvent, now: float) -> bool:
        self._ensure_working(now)
        self._needs_you(describe_permission(event.tool_name, event.tool_input), now)
        return True

    def _on_notification(self, event: HookEvent, now: float) -> bool:
        kind = event.notification_type

        if self.state is SessionState.LIMITED:
            if kind == _RESUMED:
                self.state = SessionState.WORKING
                self.step = "Thinking"
                self.message = ""
                self.progress.resume(now)
                return True
            if kind == _RESUME_NEEDS_ENTER:
                self._needs_you(USAGE_BACK_MESSAGE, now)
                return True
            return False  # still waiting for the limit to reset; idle_prompt isn't sent

        if kind == _IDLE_TYPE:
            if self.state not in _BUSY:
                return False  # a finished session waiting: Done stays
            self.state = SessionState.IDLE  # interrupted (no Stop is sent)
            self.message = ""
            self.progress.pause(now)
            return True

        if kind and kind not in _NEEDS_YOU_TYPES:
            return False  # auth_success, agent_completed, quota_*, … are not for us
        if self.state not in _BUSY:
            return False
        if self.state is SessionState.NEEDS_YOU and kind == "permission_prompt":
            return False  # PermissionRequest already gave a more specific message
        self._needs_you(event.message or "Needs your input", now)
        return True

    def _on_stop(self, _event: HookEvent, now: float) -> bool:
        return self._finish("Done", now)

    def _on_stop_failure(self, event: HookEvent, now: float) -> bool:
        label = USAGE_ERRORS.get(event.error)
        if label is None:
            return self._finish("Stopped with an error", now)
        changed = self.state is not SessionState.LIMITED or self.step != label
        self.state = SessionState.LIMITED
        self.step = label
        self.message = event.error_text or label  # e.g. "… resets at 3pm" when Claude says so
        self.progress.pause(now)  # the estimate freezes where it was
        return changed or bool(event.error_text)

    # ---- helpers ---------------------------------------------------------
    def _ensure_working(self, now: float) -> None:
        if self.state in (SessionState.IDLE, SessionState.DONE):
            # We missed the prompt (the app started mid-task) or Claude carried
            # on after Stop: start a fresh estimate.
            self.progress.start(now)
            self.task_started_at = now
            self.state = SessionState.WORKING
        elif self.state in (SessionState.NEEDS_YOU, SessionState.LIMITED):
            self.progress.resume(now)

    def _needs_you(self, message: str, now: float) -> None:
        self.state = SessionState.NEEDS_YOU
        self.message = message
        self.progress.pause(now)

    def _finish(self, step: str, now: float) -> bool:
        if self.state is SessionState.DONE:
            return False
        self.state = SessionState.DONE
        self.step = step
        self.message = ""
        self.progress.complete(now)
        return True
