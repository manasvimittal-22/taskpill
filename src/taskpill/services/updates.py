"""Checking for a newer TaskPill (Phase 10; Manasvi: "do this also before the final
public app").

The network work runs on a background thread; results come back on the Qt thread
through the ``changed`` signal. Everything outside is injected (the fetcher, the
downloader, the installer launcher, wall-clock time), so tests never touch the
network.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from taskpill.domain.updates import Release, due, is_newer


class UpdateState(Enum):
    IDLE = "idle"  # not checked yet (or checks are off)
    CHECKING = "checking"
    UP_TO_DATE = "up_to_date"
    AVAILABLE = "available"
    DOWNLOADING = "downloading"
    FAILED = "failed"


@dataclass(frozen=True)
class UpdateStatus:
    state: UpdateState
    release: Release | None = None
    message: str = ""


class UpdateService(QObject):
    changed = Signal(object)  # UpdateStatus
    _finished = Signal(object)  # from the worker thread → the Qt thread

    def __init__(
        self,
        current_version: str,
        fetch: Callable[[], Release | None],
        download: Callable[[Release], Path],
        launch: Callable[[Path], None],
        wall_clock: Callable[[], float],
        run_in_background: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        super().__init__()
        self._current = current_version
        self._fetch = fetch
        self._download = download
        self._launch = launch
        self._now = wall_clock
        self._run = run_in_background or _thread
        self.status = UpdateStatus(UpdateState.IDLE)
        self._finished.connect(self._set)
        self._announced: str | None = None

    # ---- checking ------------------------------------------------------------------------
    def check_if_due(self, last_check: float) -> bool:
        """Start a check if a day has passed since ``last_check``. True if started."""
        if not due(last_check, self._now()):
            return False
        self.check_now()
        return True

    def check_now(self) -> None:
        if self.status.state in (UpdateState.CHECKING, UpdateState.DOWNLOADING):
            return
        self._set(UpdateStatus(UpdateState.CHECKING, self.status.release))

        def work() -> None:
            try:
                release = self._fetch()
            except Exception as e:  # UpdateError carries a readable message
                self._finished.emit(UpdateStatus(UpdateState.FAILED, None, str(e)))
                return
            if release is not None and is_newer(release.version, self._current):
                self._finished.emit(UpdateStatus(UpdateState.AVAILABLE, release))
            else:
                self._finished.emit(UpdateStatus(UpdateState.UP_TO_DATE))

        self._run(work)

    # ---- installing ----------------------------------------------------------------------
    def install(self) -> None:
        """Download the installer and run it. The installer closes TaskPill, installs
        the new version over it (settings and hooks stay) and starts it again."""
        release = self.status.release
        if self.status.state is not UpdateState.AVAILABLE or release is None:
            return
        self._set(UpdateStatus(UpdateState.DOWNLOADING, release))

        def work() -> None:
            try:
                path = self._download(release)
                self._launch(path)
            except Exception as e:
                self._finished.emit(UpdateStatus(UpdateState.AVAILABLE, release, str(e)))

        self._run(work)

    def take_announcement(self) -> Release | None:
        """The release to announce once (a tray notification), or None."""
        r = self.status.release
        if self.status.state is UpdateState.AVAILABLE and r and self._announced != r.version:
            self._announced = r.version
            return r
        return None

    def _set(self, status: UpdateStatus) -> None:
        self.status = status
        self.changed.emit(status)


def _thread(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, name="taskpill-update", daemon=True).start()
