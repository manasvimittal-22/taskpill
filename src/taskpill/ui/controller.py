"""Keeps the pill row in step with the session store.

* Rebuilds the pill models when a session changes, and once a second while
  anything is on screen (the estimated % keeps growing between events).
* Clicking a Done pill hides it. Clicking any pill also asks ``focus`` to
  bring that session's window forward (the platform code comes in Phases 4–5).
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

from taskpill.domain.session import Session, SessionState
from taskpill.services.clock import Clock
from taskpill.services.session_store import SessionStore
from taskpill.ui.pill_row import PillRow
from taskpill.ui.view_model import PillKind, PillModel, build_models

REFRESH_MS = 1000

FocusWindow = Callable[[Session], None]


class PillController(QObject):
    def __init__(
        self,
        store: SessionStore,
        row: PillRow,
        clock: Clock,
        focus: FocusWindow | None = None,
        on_models: Callable[[list[PillModel]], None] | None = None,
        on_cue: Callable[[PillKind, bool], None] | None = None,
    ) -> None:
        super().__init__(row)
        self._store = store
        self._row = row
        self._clock = clock
        self._focus = focus
        self._on_models = on_models
        self._on_cue = on_cue  # (kind, shown): a session just became needs-you or done
        self._kinds: dict[str, PillKind] = {}
        self._quiet = False
        self._needs_you_in_quiet = True  # a setting (Manasvi, 2026-11-17)
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)

        store.on_changed(lambda _s: self.refresh())
        store.on_removed(lambda _sid: self.refresh())
        row.clicked.connect(self.click)

    def set_quiet(self, quiet: bool) -> None:
        """Quiet = a full-screen app is in front: only sessions that need you show."""
        if quiet != self._quiet:
            self._quiet = quiet
            self.refresh()

    def set_needs_you_in_fullscreen(self, show: bool) -> None:
        """Whether sessions that need you still show over a full-screen app."""
        if show != self._needs_you_in_quiet:
            self._needs_you_in_quiet = show
            self.refresh()

    def window_came_forward(self, handle: int,
                            window_for: Callable[[Session], int | None]) -> None:
        """You switched to a window yourself: clear the Done pills of the sessions
        that run in it (Manasvi, 2026-11-17). Only on a *switch*, so a session that
        finishes while you're already in its window still shows Done."""
        for session in list(self._store.visible()):
            done = session.state is SessionState.DONE
            if done and session.pid_chain and window_for(session) == handle:
                self._store.acknowledge(session.session_id)

    def refresh(self) -> None:
        models = build_models(self._store.visible(), self._clock.now())
        if self._on_models is not None:
            self._on_models(models)  # everything, before the full-screen filter
        sessions = len(models)
        everything = models
        if self._quiet:
            models = [m for m in models
                      if self._needs_you_in_quiet and m.kind is PillKind.NEEDS_YOU]
        self._row.set_models(models, sessions)
        self._report_changes(everything, {m.session_id for m in models})
        if models:
            if not self._row.isVisible():
                self._row.show()
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
            # the row hides itself once the last pill has faded out
            QTimer.singleShot(250, self._hide_if_empty)

    def _report_changes(self, models: list[PillModel], shown: set[str]) -> None:
        """Tell ``on_cue`` about sessions that just became needs-you or done."""
        kinds = {m.session_id: m.kind for m in models}
        if self._on_cue is not None:
            for sid, kind in kinds.items():
                if kind in (PillKind.NEEDS_YOU, PillKind.DONE) and self._kinds.get(sid) != kind:
                    self._on_cue(kind, sid in shown)
        self._kinds = kinds

    def _hide_if_empty(self) -> None:
        if not self._row.has_pills():
            self._row.hide()

    def click(self, session_id: str) -> None:
        """A pill was clicked (on the taskbar, or in VS Code's status bar)."""
        session = self._store.get(session_id)
        if session is None:
            return
        if self._focus is not None:
            # A platform that can't focus must not leave Done stuck.
            with contextlib.suppress(Exception):
                self._focus(session)
        if session.state in (SessionState.DONE, SessionState.LIMITED):
            self._store.acknowledge(session_id)
