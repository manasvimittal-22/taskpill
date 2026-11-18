from __future__ import annotations

from typing import Any

import pytest

from taskpill.domain.events import HookEvent


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def make_event(name: str, session_id: str = "s1", **extra: Any) -> HookEvent:
    payload = {"session_id": session_id, "hook_event_name": name, **extra}
    return HookEvent.from_payload(payload)
