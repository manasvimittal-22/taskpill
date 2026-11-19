"""What a screen reader is told about the pills."""

from PySide6.QtCore import QPoint
from PySide6.QtGui import QAccessible

from taskpill.ui import pill_row, spoken
from taskpill.ui.pill_row import PillRow, RowOptions
from taskpill.ui.theme import DARK
from taskpill.ui.view_model import PillKind, PillModel, Tooltip


def model(sid="a", kind=PillKind.WORKING, percent=42, detail="Editing login.py", title="taskpill"):
    return PillModel(sid, title, detail, kind, percent, Tooltip("", "", "", ""))


def test_each_state_is_said_in_plain_words():
    assert spoken.describe_one(model()) == "taskpill: working, 42 percent. Editing login.py."
    assert spoken.describe_one(model(kind=PillKind.NEEDS_YOU, detail="Needs permission to run ls")
                               ) == "taskpill: needs you. Needs permission to run ls."
    assert spoken.describe_one(model(kind=PillKind.DONE)) == "taskpill: done."
    assert spoken.describe_one(model(kind=PillKind.LIMITED, detail="Out of usage")
                               ) == "taskpill: Out of usage."
    assert "30 minutes" in spoken.describe_one(model(kind=PillKind.STALE))


def test_a_message_that_ends_with_a_full_stop_does_not_get_two():
    said = spoken.describe_one(model(kind=PillKind.NEEDS_YOU, detail="Plan ready."))
    assert said.endswith("Plan ready.") and not said.endswith("..")


def test_several_sessions_say_how_many():
    said = spoken.describe([model("a"), model("b", kind=PillKind.DONE, title="couchwave")])
    assert said == ("2 sessions. taskpill: working, 42 percent. Editing login.py. "
                    "couchwave: done.")
    assert spoken.describe([]) == ""


def test_percent_ticks_are_not_news_but_state_changes_are():
    base = spoken.announcement_key([model(percent=10)])
    assert spoken.announcement_key([model(percent=55, detail="Reading b.py")]) == base
    assert spoken.announcement_key([model(kind=PillKind.DONE)]) != base
    asking = spoken.announcement_key([model(kind=PillKind.NEEDS_YOU, detail="Question A")])
    assert spoken.announcement_key([model(kind=PillKind.NEEDS_YOU, detail="Question B")]) != asking


# ---- the row ---------------------------------------------------------------------------------
def make_row(qtbot):
    row = PillRow(RowOptions(), DARK)
    qtbot.addWidget(row)
    row.set_anchor(QPoint(1000, 500))
    return row


def record_events(monkeypatch):
    sent = []
    monkeypatch.setattr(pill_row.QAccessible, "isActive", staticmethod(lambda: True))
    monkeypatch.setattr(pill_row.QAccessible, "updateAccessibility",
                        staticmethod(lambda event: sent.append(event.type())))
    return sent


def test_the_row_carries_a_name_and_the_words(qtbot):
    row = make_row(qtbot)
    row.set_models([model()])
    assert row.accessibleName() == "TaskPill: taskpill: working, 42 percent. Editing login.py."
    assert row.accessibleDescription() == "taskpill: working, 42 percent. Editing login.py."
    row.set_models([model(kind=PillKind.DONE)])
    assert row.accessibleName() == "TaskPill: taskpill: done."
    row.set_models([])
    assert row.accessibleName() == "TaskPill"


def test_a_session_that_starts_waiting_raises_an_alert_once(qtbot, monkeypatch):
    row = make_row(qtbot)
    sent = record_events(monkeypatch)
    row.set_models([model()])
    ask = model(kind=PillKind.NEEDS_YOU, detail="Needs permission to run ls")
    row.set_models([ask])
    row.set_models([ask])  # the same news again: silence
    assert sent == [QAccessible.Event.DescriptionChanged, QAccessible.Event.Alert]


def test_percent_ticks_stay_quiet(qtbot, monkeypatch):
    row = make_row(qtbot)
    sent = record_events(monkeypatch)
    row.set_models([model(percent=10)])
    sent.clear()
    row.set_models([model(percent=11)])
    row.set_models([model(percent=12, detail="Reading x.py")])
    assert sent == []
    assert "12 percent" in row.accessibleDescription()  # still readable on demand


def test_no_events_without_a_screen_reader(qtbot, monkeypatch):
    row = make_row(qtbot)
    sent = []
    monkeypatch.setattr(pill_row.QAccessible, "isActive", staticmethod(lambda: False))
    monkeypatch.setattr(pill_row.QAccessible, "updateAccessibility",
                        staticmethod(lambda event: sent.append(event)))
    row.set_models([model(kind=PillKind.NEEDS_YOU, detail="x")])
    assert sent == []
