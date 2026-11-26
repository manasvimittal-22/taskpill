"""The settings window. Changes apply right away (no Save button)."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from taskpill import __version__
from taskpill.adapters.settings_store import Settings
from taskpill.platform.base import JUMP_KEYS
from taskpill.ui.os_words import WORDS
from taskpill.ui.settings_preview import SettingsPreview
from taskpill.ui.shell_style import shell_stylesheet
from taskpill.ui.theme import (
    ACCENT_COLORS,
    DONE_COLORS,
    LIMITED_COLORS,
    NEEDS_YOU_COLORS,
    Palette,
    qcolor,
)
from taskpill.ui.widgets import KeyCaps, Segmented, Swatches, Toggle

COLUMN_WIDTH = 332  # the old single column's width
COLUMN_GAP = 40
MARGIN = 24
WINDOW_WIDTH = 2 * COLUMN_WIDTH + COLUMN_GAP + 2 * MARGIN
SECTION_GAP = 10  # between section boxes
SECTION_PAD_X = 14  # inside a section box
SECTION_PAD_Y = 9
BUTTON_WIDTH = 120
# The connection band's words: the band is the page width, less its padding, dot, button.
CONNECTION_TEXT_WIDTH = WINDOW_WIDTH - 2 * MARGIN - 30 - 10 - 2 * 12 - BUTTON_WIDTH - 24
AUTO_QUIT_LABELS = [(5, "5 min"), (10, "10 min"), (30, "30 min"), (60, "1 h"), (0, "Never")]


class _StatusDot(QWidget):
    def __init__(self, pal: Palette, on: bool):
        super().__init__()
        self._pal, self._on = pal, on
        self.setFixedSize(10, 10)

    def set(self, pal: Palette, on: bool) -> None:
        self._pal, self._on = pal, on
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self._pal.done) if self._on else qcolor(self._pal.text_soft))
        p.drawEllipse(1, 1, 8, 8)
        p.end()


def _box_hint(text: str) -> QLabel:
    """A hint inside a section box. Wrapped labels need a real width, or Qt guesses their
    height wrong and clips the second line."""
    label = _label(text, "hint")
    label.setFixedWidth(COLUMN_WIDTH - 2 * SECTION_PAD_X)
    return label


def _label(text: str, role: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", role)
    label.setWordWrap(role in ("hint", "body", "error"))
    label.setIndent(0)  # a styled QLabel otherwise adds half an "x" of indent
    return label


class SettingsWindow(QWidget):
    settings_changed = Signal(object)  # Settings
    connect_requested = Signal()
    disconnect_requested = Signal()
    reset_position_requested = Signal()
    reset_size_requested = Signal()
    update_check_requested = Signal()
    update_install_requested = Signal()
    quit_requested = Signal()

    def __init__(self, settings: Settings, pal: Palette, connected: bool,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._settings = settings
        self._pal = pal
        self._connected = connected
        self.setObjectName("Shell")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setWindowTitle("TaskPill settings")
        self.setFixedWidth(WINDOW_WIDTH)
        page = QVBoxLayout(self)
        page.setContentsMargins(MARGIN, MARGIN - 4, MARGIN, 16)
        page.setSpacing(0)

        # 1. The live preview: real pills in your colors, on a strip like the taskbar
        # (UI rework, 2026-11-26). Every look change shows here at once.
        self.preview = SettingsPreview(pal, settings.glow, settings.dot)
        page.addWidget(self.preview)
        page.addSpacing(10)

        # 2. The connection, right under it: nothing works until it's connected, so it
        # can't be missed (Manasvi, 2026-11-26: "highlight the connect option").
        page.addWidget(self._build_connection(pal, connected))
        page.addSpacing(14)

        # 3. Two columns (Manasvi, 2026-11-17: one column was too long): how it looks and
        # sounds on the left, how it behaves on the right.
        columns = QHBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(COLUMN_GAP)
        page.addLayout(columns)
        left, right = self._column(columns), self._column(columns)
        self._build_look(left, settings)
        self._build_behavior(right, settings, pal)

        # 4. App-wide actions, apart from the settings they'd otherwise sit among.
        page.addSpacing(14)
        page.addWidget(self._rule())
        page.addSpacing(12)
        page.addLayout(self._build_footer())

        self.set_connected(connected)
        self.set_palette(pal)

    # ---- sections ----------------------------------------------------------------------
    def _build_connection(self, pal: Palette, connected: bool) -> QFrame:
        # A band that lights up in the accent while not connected; quiet once it is.
        self.connect_box = QFrame()
        self.connect_box.setObjectName("connectBox")
        band = QHBoxLayout(self.connect_box)
        band.setContentsMargins(16, 12, 14, 12)
        band.setSpacing(12)
        self.status_dot = _StatusDot(pal, connected)
        dot_column = QVBoxLayout()
        dot_column.setContentsMargins(0, 6, 0, 0)  # centered on the title's first line
        dot_column.addWidget(self.status_dot)
        dot_column.addStretch(1)
        band.addLayout(dot_column)
        words = QVBoxLayout()
        words.setSpacing(2)
        self.status_text = _label("", "strong")
        self.status_hint = _label("", "hint")
        self.status_hint.setFixedWidth(CONNECTION_TEXT_WIDTH)  # wrapped: needs a real width
        words.addWidget(self.status_text)
        words.addWidget(self.status_hint)
        band.addLayout(words)
        band.addStretch(1)
        self.connect_button = QPushButton()
        self.connect_button.setFixedWidth(BUTTON_WIDTH)
        self.connect_button.clicked.connect(self._on_connect_clicked)
        band.addWidget(self.connect_button, 0, Qt.AlignmentFlag.AlignVCenter)
        return self.connect_box

    def _build_look(self, column: QVBoxLayout, settings: Settings) -> None:
        box = self._section(column, "Colors", first=True)
        # One row per state (Manasvi, 2026-11-17); each state has its own set.
        self.swatches = self._color_row(box, "Working", ACCENT_COLORS, "accent")
        self.needs_you_swatches = self._color_row(box, "Needs you", NEEDS_YOU_COLORS,
                                                  "needs_you_color")
        self.done_swatches = self._color_row(box, "Done", DONE_COLORS, "done_color")
        self.limited_swatches = self._color_row(box, "Out of usage", LIMITED_COLORS,
                                                "limited_color")

        box = self._section(column, "When a session needs you")
        self.glow = self._toggle_row(box, "Glow softly", settings.glow, "glow")
        self.dot = self._toggle_row(box, "Show a dot on the edge", settings.dot, "dot")
        self.expand = self._toggle_row(box, "Open circles to show the message",
                                       settings.expand_needs_you, "expand_needs_you")

        box = self._section(column, "Sounds")
        self.sound_needs_you = self._toggle_row(box, "When a session needs you",
                                                settings.sound_needs_you, "sound_needs_you")
        self.sound_done = self._toggle_row(box, "When a session is done", settings.sound_done,
                                           "sound_done")

        box = self._section(column, "Motion")
        self.reduced = self._toggle_row(box, "Reduce motion", settings.reduced_motion,
                                        "reduced_motion")
        self.motion_hint = _box_hint("")
        box.addWidget(self.motion_hint)
        self.set_system_motion(False)
        column.addStretch(1)

    def _build_behavior(self, column: QVBoxLayout, settings: Settings, pal: Palette) -> None:
        box = self._section(column, "Full-screen apps", first=True)
        self.fullscreen = self._toggle_row(box, "Hide the pills", settings.hide_in_fullscreen,
                                           "hide_in_fullscreen")
        # Its own switch now (Manasvi, 2026-11-17); it was a fixed rule before.
        self.fullscreen_needs_you = self._toggle_row(
            box, "Still show sessions that need you", settings.needs_you_in_fullscreen,
            "needs_you_in_fullscreen")

        box = self._section(column, "Shortcuts")
        self.jump_hotkey = self._toggle_row(box, "Turn on the jump shortcut", settings.jump_hotkey,
                                            "jump_hotkey")
        self.jump_hint = _box_hint("")
        box.addWidget(self.jump_hint)
        box.addSpacing(2)
        self.key_caps = [
            self._key_row(box, "Go to the waiting session", JUMP_KEYS),
            self._key_row(box, "Move between settings", ("Tab",)),
            self._key_row(box, "Switch on or off", ("Space",)),
            self._key_row(box, "Change a choice", ("←", "→")),
        ]
        self.set_hotkey_status(False)

        box = self._section(column, "Quit when idle for")
        self.auto_quit = Segmented(pal, AUTO_QUIT_LABELS, settings.auto_quit_minutes)
        self.auto_quit.setAccessibleName("Quit when idle for")
        self.auto_quit.changed.connect(lambda v: self._update(auto_quit_minutes=v))
        box.addWidget(self.auto_quit)
        box.addWidget(_box_hint("Claude Code starts TaskPill again when you next use it."))

        box = self._section(column, "Updates")
        self.check_updates = self._toggle_row(box, "Check once a day",
                                              settings.check_updates, "check_updates")
        update_row = QHBoxLayout()
        update_row.setContentsMargins(0, 0, 0, 0)
        self.update_text = _label("", "hint")
        self.update_text.setWordWrap(False)
        self.update_button = QPushButton()
        self.update_button.clicked.connect(self._on_update_clicked)
        update_row.addWidget(self.update_text, 1)
        update_row.addWidget(self.update_button)
        box.addLayout(update_row)
        self._update_action = "check"
        self.set_update_status("From source, updates come with git.", None)
        column.addStretch(1)

    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addWidget(_label(f"TaskPill {__version__}", "hint"))
        footer.addStretch(1)
        reset = QPushButton("Reset position")
        reset.setToolTip(f"Back next to {WORDS.home}.")
        reset.clicked.connect(self.reset_position_requested)
        # Reset size lives here (Manasvi, 2026-11-17), not in the pill's menu.
        self.reset_size_button = QPushButton("Reset size")
        self.reset_size_button.setToolTip(f"Back to {WORDS.default_size}.")
        self.reset_size_button.clicked.connect(self.reset_size_requested)
        self.quit_button = QPushButton("Quit TaskPill")
        self.quit_button.setToolTip("Claude Code starts it again when you next use it.")
        self.quit_button.clicked.connect(self.quit_requested)
        for button in (reset, self.reset_size_button, self.quit_button):
            button.setAccessibleDescription(button.toolTip())
            footer.addWidget(button)
        return footer

    @staticmethod
    def _rule() -> QFrame:
        line = QFrame()
        line.setObjectName("rule")
        line.setFixedHeight(1)
        return line

    @staticmethod
    def _section(column: QVBoxLayout, title: str, first: bool = False) -> QVBoxLayout:
        """A section in its own outlined box (Manasvi, 2026-11-26: "each section … to have
        a border around it"). Returns the layout its rows go in."""
        if not first:
            column.addSpacing(SECTION_GAP)
        frame = QFrame()
        frame.setObjectName("section")
        frame.setAccessibleName(title)
        box = QVBoxLayout(frame)
        box.setContentsMargins(SECTION_PAD_X, SECTION_PAD_Y - 4, SECTION_PAD_X, SECTION_PAD_Y)
        box.setSpacing(4)
        box.addWidget(_label(title, "section"))
        column.addWidget(frame)
        return box

    # ---- public ------------------------------------------------------------------------
    @property
    def settings(self) -> Settings:
        return self._settings

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        self.status_dot.set(self._pal, connected)
        if connected:
            self.status_text.setText("Connected to Claude Code")
            self.status_hint.setText("New Claude Code sessions show up as pills. TaskPill's "
                                     "hooks live in ~/.claude/settings.json.")
        else:
            self.status_text.setText("Not connected to Claude Code")
            self.status_hint.setText("Connect so your sessions show up as pills. TaskPill "
                                     "adds hooks to ~/.claude/settings.json and backs it up "
                                     "first.")
        self.connect_button.setText("Disconnect" if connected else "Connect")
        self.connect_button.setProperty("role", "" if connected else "primary")
        self.connect_box.setProperty("needsConnect", not connected)
        for widget in (self.connect_button, self.connect_box):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def set_system_motion(self, windows_reduces: bool) -> None:
        """The system's own reduce-motion switch also turns motion off; say so."""
        text = "No glow pulse, no sliding. Changes are instant."
        if windows_reduces:
            text += f" {WORDS.system} is set to reduce motion, so TaskPill already does."
        self.motion_hint.setText(text)

    def set_hotkey_status(self, active: bool) -> None:
        """Say whether the jump shortcut is really listening (another app may own the key)."""
        keys = "+".join(JUMP_KEYS)
        if not self._settings.jump_hotkey:
            text = "Turned off."
        elif active:
            text = "Works from any app, longest wait first."
        else:
            text = f"Another app is using {keys}, so this shortcut can't start."
        self.jump_hint.setText(text)

    def set_update_status(self, text: str, action: str | None,
                          button: str = "") -> None:
        """``action``: "check", "install", "open" or None (no button)."""
        self.update_text.setText(text)
        self._update_action = action or ""
        self.update_button.setVisible(action is not None)
        self.update_button.setText(button)
        self.update_button.setProperty("role", "primary" if action == "install" else "")
        self.update_button.style().unpolish(self.update_button)
        self.update_button.style().polish(self.update_button)

    def _on_update_clicked(self) -> None:
        if self._update_action == "check":
            self.update_check_requested.emit()
        elif self._update_action in ("install", "open"):
            self.update_install_requested.emit()

    def set_palette(self, pal: Palette) -> None:
        self._pal = pal
        self.setStyleSheet(shell_stylesheet(pal))
        for w in (self.glow, self.expand, self.dot, self.reduced, self.fullscreen,
                  self.fullscreen_needs_you, self.sound_needs_you, self.sound_done,
                  self.jump_hotkey, *self.key_caps, self.check_updates,
                  self.swatches, self.needs_you_swatches, self.done_swatches,
                  self.limited_swatches, self.auto_quit):
            w.set_palette(pal)
        self.preview.set_palette(pal)
        self.status_dot.set(pal, self._connected)

    # ---- building ----------------------------------------------------------------------
    @staticmethod
    def _column(outer: QHBoxLayout) -> QVBoxLayout:
        # A fixed width, so wrapped hints know how wide they are (Qt guesses wrong otherwise).
        holder = QWidget()
        holder.setFixedWidth(COLUMN_WIDTH)
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        outer.addWidget(holder, 0, Qt.AlignmentFlag.AlignTop)
        return column

    def _row(self, root: QVBoxLayout, text: str, control: QWidget, role: str = "label",
             hint: str | None = None) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        label = _label(text, role)
        label.setWordWrap(False)  # a row label shares its line with a control: keep it to one line
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        label.setBuddy(control)
        row.addWidget(label)
        row.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(row)
        if hint:
            root.addWidget(_label(hint, "hint"))

    def _key_row(self, root: QVBoxLayout, text: str, keys: tuple[str, ...]) -> KeyCaps:
        caps = KeyCaps(self._pal, keys)
        self._row(root, text, caps)
        return caps

    def _color_row(self, root: QVBoxLayout, text: str,
                   colors: dict[str, tuple[str, str]], field: str) -> Swatches:
        swatches = Swatches(self._pal, getattr(self._settings, field), colors=colors)
        swatches.setAccessibleName(f"{text} color")
        swatches.changed.connect(lambda name: self._update(**{field: name}))
        self._row(root, text, swatches)
        return swatches

    def _toggle_row(self, root: QVBoxLayout, text: str, value: bool, field: str,
                    hint: str | None = None) -> Toggle:
        toggle = Toggle(self._pal, value)
        toggle.setAccessibleName(text)
        toggle.toggled.connect(lambda on: self._update(**{field: on}))
        self._row(root, text, toggle, hint=hint)
        return toggle

    def _update(self, **changes) -> None:
        self._settings = replace(self._settings, **changes)
        self.preview.set_needs_you_look(self._settings.glow, self._settings.dot)
        self.settings_changed.emit(self._settings)  # the app answers with set_hotkey_status

    def _on_connect_clicked(self) -> None:
        if self._connected:
            self.disconnect_requested.emit()
        else:
            self.connect_requested.emit()
