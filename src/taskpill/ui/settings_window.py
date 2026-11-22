"""The settings window. Changes apply right away (no Save button)."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from taskpill.adapters.settings_store import Settings
from taskpill.platform.base import JUMP_KEYS
from taskpill.ui.os_words import WORDS
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
RESET_BUTTON_WIDTH = 144
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
        # Two columns side by side (Manasvi, 2026-11-17: the single column was too
        # long): what the pill looks like on the left, how TaskPill behaves on the right.
        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 18, 24, 22)
        outer.setSpacing(COLUMN_GAP)
        left, right = self._column(outer), self._column(outer)
        self.setFixedWidth(2 * COLUMN_WIDTH + COLUMN_GAP + 48)

        root = left

        root.addWidget(_label("When a session needs you", "section"))
        self.glow = self._toggle_row(root, "Glow softly", settings.glow, "glow")
        self.expand = self._toggle_row(root, "Open circles to show the message",
                                       settings.expand_needs_you, "expand_needs_you")
        self.dot = self._toggle_row(root, "Show a dot on the edge", settings.dot, "dot")

        root.addSpacing(14)
        root.addWidget(_label("Colors", "section"))
        # One row per state (Manasvi, 2026-11-17); each state has its own set.
        self.swatches = self._color_row(root, "Working", ACCENT_COLORS, "accent")
        self.needs_you_swatches = self._color_row(root, "Needs you", NEEDS_YOU_COLORS,
                                                  "needs_you_color")
        self.done_swatches = self._color_row(root, "Done", DONE_COLORS, "done_color")
        self.limited_swatches = self._color_row(root, "Out of usage", LIMITED_COLORS,
                                                "limited_color")

        root.addSpacing(14)
        root.addWidget(_label("Sounds", "section"))
        self.sound_needs_you = self._toggle_row(root, "When a session needs you",
                                                settings.sound_needs_you, "sound_needs_you")
        self.sound_done = self._toggle_row(root, "When a session is done", settings.sound_done,
                                           "sound_done")

        root.addSpacing(14)
        root.addWidget(_label("Shortcuts", "section"))
        self.jump_hotkey = self._toggle_row(root, "Turn on the jump shortcut", settings.jump_hotkey,
                                            "jump_hotkey")
        self.jump_hint = _label("", "hint")
        root.addWidget(self.jump_hint)
        self.key_caps = [
            self._key_row(root, "Go to the waiting session", JUMP_KEYS),
            self._key_row(root, "Move between settings", ("Tab",)),
            self._key_row(root, "Switch on or off", ("Space",)),
            self._key_row(root, "Change a choice", ("←", "→")),
        ]
        self.set_hotkey_status(False)
        root.addStretch(1)
        root = right
        root.addWidget(_label("Behavior", "section"))
        self.fullscreen = self._toggle_row(root, "Hide during full-screen apps",
                                           settings.hide_in_fullscreen, "hide_in_fullscreen")
        # Its own switch now (Manasvi, 2026-11-17); it was a fixed rule before.
        self.fullscreen_needs_you = self._toggle_row(
            root, "Still show sessions that need you", settings.needs_you_in_fullscreen,
            "needs_you_in_fullscreen", hint="Over a full-screen app, only these pop up.")
        root.addSpacing(8)
        root.addWidget(_label("Quit when idle for", "label"))
        self.auto_quit = Segmented(pal, AUTO_QUIT_LABELS, settings.auto_quit_minutes)
        self.auto_quit.changed.connect(lambda v: self._update(auto_quit_minutes=v))
        root.addSpacing(4)
        root.addWidget(self.auto_quit)
        root.addWidget(_label("Claude Code starts TaskPill again when you next use it.", "hint"))
        self.quit_button = QPushButton("Quit TaskPill")
        self.quit_button.setFixedWidth(RESET_BUTTON_WIDTH)
        self.quit_button.clicked.connect(self.quit_requested)
        self._row(root, "Close TaskPill now.", self.quit_button, role="hint")

        root.addSpacing(14)
        root.addWidget(_label("Motion", "section"))
        self.reduced = self._toggle_row(root, "Reduce motion", settings.reduced_motion,
                                        "reduced_motion")
        self.motion_hint = _label("", "hint")
        root.addWidget(self.motion_hint)
        self.set_system_motion(False)

        root.addSpacing(14)
        root.addWidget(_label("Claude Code", "section"))
        status = QHBoxLayout()
        status.setSpacing(8)
        self.status_dot = _StatusDot(pal, connected)
        self.status_text = _label("", "label")
        self.connect_button = QPushButton()
        self.connect_button.clicked.connect(self._on_connect_clicked)
        status.addWidget(self.status_dot)
        status.addWidget(self.status_text)
        status.addStretch(1)
        status.addWidget(self.connect_button)
        root.addLayout(status)
        root.addWidget(_label("TaskPill listens through hooks in ~/.claude/settings.json. "
                              "A backup is made before every change.", "hint"))

        root.addSpacing(14)
        root.addWidget(_label("Updates", "section"))
        self.check_updates = self._toggle_row(root, "Check for updates once a day",
                                              settings.check_updates, "check_updates")
        update_row = QHBoxLayout()
        update_row.setContentsMargins(0, 2, 0, 2)
        self.update_text = _label("", "hint")
        self.update_text.setWordWrap(False)
        self.update_button = QPushButton()
        self.update_button.clicked.connect(self._on_update_clicked)
        update_row.addWidget(self.update_text, 1)
        update_row.addWidget(self.update_button)
        root.addLayout(update_row)
        self._update_action = "check"
        self.set_update_status("From source, updates come with git.", None)

        root.addSpacing(14)
        root.addWidget(_label("Position and size", "section"))
        reset = QPushButton("Reset position")
        reset.clicked.connect(self.reset_position_requested)
        self._row(root, f"Back next to {WORDS.home}.", reset, role="hint")
        # Reset size lives here (Manasvi, 2026-11-17), not in the pill's menu.
        self.reset_size_button = QPushButton("Reset size")
        self.reset_size_button.clicked.connect(self.reset_size_requested)
        self._row(root, f"Back to {WORDS.default_size}.", self.reset_size_button, role="hint")
        # The two buttons line up. (A fixed width: sizeHint is measured before the
        # stylesheet's padding applies, so matching sizeHints doesn't work.)
        for button in (reset, self.reset_size_button):
            button.setFixedWidth(RESET_BUTTON_WIDTH)
        root.addStretch(1)

        self.set_connected(connected)
        self.set_palette(pal)

    # ---- public ------------------------------------------------------------------------
    @property
    def settings(self) -> Settings:
        return self._settings

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        self.status_dot.set(self._pal, connected)
        self.status_text.setText("Connected" if connected else "Not connected")
        self.connect_button.setText("Disconnect" if connected else "Connect")
        self.connect_button.setProperty("role", "" if connected else "primary")
        self.connect_button.style().unpolish(self.connect_button)
        self.connect_button.style().polish(self.connect_button)

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
            text = "Works from any app. The session waiting longest comes first."
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
        row.setContentsMargins(0, 2, 0, 2)
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
        self.settings_changed.emit(self._settings)  # the app answers with set_hotkey_status

    def _on_connect_clicked(self) -> None:
        if self._connected:
            self.disconnect_requested.emit()
        else:
            self.connect_requested.emit()
