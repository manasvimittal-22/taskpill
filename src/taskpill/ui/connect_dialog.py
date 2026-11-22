"""First-launch prompt: "Connect TaskPill to Claude Code?"

It shows a real pill at the top (drawn by the same painter), so the prompt
shows what you'll get instead of describing it.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from taskpill.ui import geometry as g
from taskpill.ui.os_words import WORDS
from taskpill.ui.pill_painter import Fonts, PillLook, paint_pill
from taskpill.ui.shell_style import shell_stylesheet
from taskpill.ui.theme import Palette
from taskpill.ui.view_model import PillKind, PillModel, Tooltip

# Returns None when it worked, or a sentence saying what went wrong.
ConnectAction = Callable[[], str | None]

SAMPLE = PillModel("sample", "taskpill", "Editing login.py", PillKind.WORKING, 42,
                   Tooltip("", "", "", ""))


class _SamplePill(QWidget):
    def __init__(self, pal: Palette):
        super().__init__()
        self._pal = pal
        self._fonts = Fonts()
        self.setFixedHeight(int(g.HEIGHT + 16))

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(int(g.FULL_WIDTH), int(g.HEIGHT + 16))

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        rect = QRectF(0, 8, g.FULL_WIDTH, g.HEIGHT)
        paint_pill(p, rect, SAMPLE, PillLook(edge=0.42), self._pal, self._fonts)
        p.end()


class ConnectDialog(QDialog):
    def __init__(self, pal: Palette, connect: ConnectAction, parent: QWidget | None = None):
        super().__init__(parent)
        self._connect = connect
        self.setObjectName("Shell")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setWindowTitle("TaskPill")
        self.setFixedWidth(420)
        self.setStyleSheet(shell_stylesheet(pal))

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(10)
        root.addWidget(_SamplePill(pal))

        title = QLabel("Connect TaskPill to Claude Code")
        title.setProperty("role", "title")
        root.addWidget(title)

        body = QLabel(
            "TaskPill shows what each Claude Code session is doing. To hear about it, "
            "it adds a few hooks to your Claude Code settings (~/.claude/settings.json).\n\n"
            f"A backup is made first, and you can disconnect any time from {WORDS.menu}."
        )
        body.setProperty("role", "body")
        body.setWordWrap(True)
        # Wrapped labels need a real width, or Qt guesses their height wrong and clips them.
        text_width = 420 - 2 * 28
        body.setFixedWidth(text_width)
        root.addWidget(body)

        self.error = QLabel("")
        self.error.setProperty("role", "error")
        self.error.setWordWrap(True)
        self.error.setFixedWidth(text_width)
        self.error.hide()
        root.addWidget(self.error)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        later = QPushButton("Not now")
        later.clicked.connect(self.reject)
        self.connect_button = QPushButton("Connect")
        self.connect_button.setProperty("role", "primary")
        self.connect_button.setDefault(True)
        self.connect_button.clicked.connect(self._on_connect)
        buttons.addWidget(later)
        buttons.addWidget(self.connect_button)
        root.addSpacing(6)
        root.addLayout(buttons)

    def _on_connect(self) -> None:
        problem = self._connect()
        if problem is None:
            self.accept()
            return
        self.error.setText(f"Couldn't connect: {problem} Nothing was changed.")
        self.error.show()
        self.adjustSize()
