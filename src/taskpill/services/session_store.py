"""Keeps every known session and tells listeners when one changes.

Single-threaded by design: the event server hands events to the Qt main
thread (via a signal) and only that thread calls the store.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from taskpill.domain.events import EventType, HookEvent
from taskpill.domain.progress import ProgressConfig
from taskpill.domain.session import Session, SessionState
from taskpill.services.clock import Clock

MAX_SESSIONS = 20
FORGET_IDLE_AFTER_SECONDS = 12 * 60 * 60

ChangedListener = Callable[[Session], None]
RemovedListener = Callable[[str], None]


@dataclass
class _Listeners:
    changed: list[ChangedListener]
    removed: list[RemovedListener]


class SessionStore:
    def __init__(
        self,
        clock: Clock,
        progress_config: ProgressConfig | None = None,
        max_sessions: int = MAX_SESSIONS,
    ) -> None:
        if max_sessions < 1:
            raise ValueError("max_sessions must be at least 1")
        self._clock = clock
        self._progress_config = progress_config
        self._max_sessions = max_sessions
        self._sessions: dict[str, Session] = {}
        self._listeners = _Listeners(changed=[], removed=[])

    # ---- listeners -------------------------------------------------------
    def on_changed(self, listener: ChangedListener) -> None:
        self._listeners.changed.append(listener)

    def on_removed(self, listener: RemovedListener) -> None:
        self._listeners.removed.append(listener)

    # ---- queries ---------------------------------------------------------
    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def all(self) -> list[Session]:
        """Every session, oldest first."""
        return sorted(self._sessions.values(), key=lambda s: s.created_at)

    def visible(self) -> list[Session]:
        """Sessions that should have a pill, oldest first (stable order on screen)."""
        return [s for s in self.all() if s.is_visible]

    def has_active(self) -> bool:
        """True while anything is on screen. Used for the auto-quit timer."""
        return any(s.is_visible for s in self._sessions.values())

    # ---- commands --------------------------------------------------------
    def apply(self, event: HookEvent) -> Session | None:
        now = self._clock.now()

        if event.type is EventType.SESSION_END:
            self._remove(event.session_id)
            return None

        session = self._sessions.get(event.session_id)
        if session is None:
            session = self._create(event.session_id, now)

        if session.apply(event, now):
            self._emit_changed(session)
        return session

    def acknowledge(self, session_id: str) -> bool:
        """The user clicked a Done pill."""
        session = self._sessions.get(session_id)
        if session is None or not session.acknowledge():
            return False
        self._emit_changed(session)
        return True

    def prune(self) -> list[str]:
        """Forget hidden sessions nobody has heard from in a long time.

        Covers sessions whose SessionEnd never arrived (terminal closed, crash).
        Returns the removed ids.
        """
        now = self._clock.now()
        old = [
            s.session_id
            for s in self._sessions.values()
            if s.state is SessionState.IDLE
            and now - s.last_event_at >= FORGET_IDLE_AFTER_SECONDS
        ]
        for session_id in old:
            self._remove(session_id)
        return old

    # ---- internals -------------------------------------------------------
    def _create(self, session_id: str, now: float) -> Session:
        if len(self._sessions) >= self._max_sessions:
            self._evict_one()
        session = Session(session_id, now, self._progress_config)
        self._sessions[session_id] = session
        return session

    def _evict_one(self) -> None:
        """Make room: drop the least recently heard-from session, hidden ones first."""
        victim = min(
            self._sessions.values(),
            key=lambda s: (s.is_visible, s.last_event_at),
        )
        self._remove(victim.session_id)

    def _remove(self, session_id: str) -> None:
        if self._sessions.pop(session_id, None) is not None:
            for listener in list(self._listeners.removed):
                listener(session_id)

    def _emit_changed(self, session: Session) -> None:
        for listener in list(self._listeners.changed):
            listener(session)
