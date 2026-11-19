"""Colors and fonts from docs/design.md, for the OS light or dark theme."""

from __future__ import annotations

import sys
from dataclasses import dataclass, replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication

from taskpill.platform.base import HighContrastColors
from taskpill.ui.view_model import PillKind


@dataclass(frozen=True)
class Palette:
    surface: str
    hairline: str
    text: str
    text_soft: str
    working: str
    needs_you: str
    done: str
    dark: bool
    limited: str = "#FF5470"  # out of usage

    def edge(self, kind: PillKind) -> QColor:
        return {
            PillKind.WORKING: QColor(self.working),
            PillKind.NEEDS_YOU: QColor(self.needs_you),
            PillKind.DONE: QColor(self.done),
            PillKind.LIMITED: QColor(self.limited),
            PillKind.STALE: QColor(self.text_soft),
        }[kind]

    def with_accent(self, accent: str | None) -> Palette:
        """The accent picker (Phase 6) only changes the working color."""
        return replace(self, working=accent) if accent else self


DARK = Palette(
    surface="#262A33",
    hairline="#FFFFFF1A",
    text="#ECEEF3",
    text_soft="#A3A9B6",
    working="#8B7CFF",
    needs_you="#FFB020",
    done="#3DD68C",
    dark=True,
    limited="#FF5470",
)

LIGHT = Palette(
    surface="#FBFBFD",
    hairline="#0000001F",
    text="#1A1D24",
    text_soft="#5E6573",
    working="#5B4BE0",
    needs_you="#B87300",
    done="#138A54",
    dark=False,
    limited="#C2203F",
)


# Color choices per state (docs/design.md → State colors): name → (dark, light).
# The first of each is the default. No color appears in two sets, so two states
# never look the same (and each state has a second cue besides color anyway).
ACCENT_COLORS: dict[str, tuple[str, str]] = {  # while working
    "violet": ("#8B7CFF", "#5B4BE0"),
    "glacier": ("#4FA3FF", "#1F6FD1"),
    "orchid": ("#D46CF0", "#9B32B8"),
    "slate": ("#9AA8BD", "#4E5B70"),
    "rose": ("#FF7AA2", "#C2335F"),
}
NEEDS_YOU_COLORS: dict[str, tuple[str, str]] = {
    "amber": ("#FFB020", "#B87300"),
    "tangerine": ("#FF8A3D", "#C2541A"),
    "gold": ("#F2D33C", "#8A7400"),
}
DONE_COLORS: dict[str, tuple[str, str]] = {
    "mint": ("#3DD68C", "#138A54"),
    "teal": ("#2EC4C4", "#0D7F86"),
    "lime": ("#A3D94A", "#55860C"),
}
LIMITED_COLORS: dict[str, tuple[str, str]] = {  # out of usage
    "crimson": ("#FF5470", "#C2203F"),
    "copper": ("#E0915F", "#A0561F"),
    "steel": ("#8FB0D6", "#3F5F86"),
}
# settings field → its choices (settings_store.py keeps the same names; a test checks)
STATE_COLORS: dict[str, dict[str, tuple[str, str]]] = {
    "accent": ACCENT_COLORS,
    "needs_you_color": NEEDS_YOU_COLORS,
    "done_color": DONE_COLORS,
    "limited_color": LIMITED_COLORS,
}


def palette_for(dark: bool, accent: str = "violet", needs_you: str = "amber",
                done: str = "mint", limited: str = "crimson") -> Palette:
    base = DARK if dark else LIGHT
    i = 0 if dark else 1

    def pick(colors: dict[str, tuple[str, str]], name: str, fallback: str) -> str:
        return colors[name][i] if name in colors else fallback

    return replace(
        base,
        working=pick(ACCENT_COLORS, accent, base.working),
        needs_you=pick(NEEDS_YOU_COLORS, needs_you, base.needs_you),
        done=pick(DONE_COLORS, done, base.done),
        limited=pick(LIMITED_COLORS, limited, base.limited),
    )


def high_contrast_palette(colors: HighContrastColors) -> Palette:
    """The pill in the user's own Windows high-contrast theme. Every text and line is the
    theme's text color (never the gray, which means "disabled"), and the states keep
    their other cues: the dot, the check, the pause mark."""
    surface = colors.window
    needs = colors.highlight if colors.highlight.upper() != surface.upper() else colors.hotlight
    return Palette(
        surface=surface,
        hairline=colors.text,
        text=colors.text,
        text_soft=colors.text,
        working=colors.hotlight,
        needs_you=needs,
        done=colors.text,
        dark=qcolor(surface).lightness() < 128,
        limited=colors.gray,
    )


def qcolor(hex_rgba: str) -> QColor:
    """Accept #RRGGBB or #RRGGBBAA (Qt reads 8 digits as #AARRGGBB, so convert)."""
    if len(hex_rgba) == 9:
        color = QColor(hex_rgba[:7])
        color.setAlpha(int(hex_rgba[7:], 16))
        return color
    return QColor(hex_rgba)


def surface_light(pal: Palette) -> tuple[QColor, QColor]:
    """Top and bottom of a surface lit softly from above (docs/design.md → Polish)."""
    base = qcolor(pal.surface)
    if pal.dark:
        return base.lighter(112), base.darker(104)
    return QColor("#FFFFFF"), base.darker(103)


def rim_light(pal: Palette) -> QColor:
    """The 1 px highlight along a surface's top edge."""
    return QColor(255, 255, 255, 20 if pal.dark else 0)


def system_is_dark() -> bool:
    return QGuiApplication.styleHints().colorScheme() != Qt.ColorScheme.Light


def system_palette(accent: str = "violet") -> Palette:
    return palette_for(system_is_dark(), accent)


def ui_font(size_px: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    if sys.platform == "win32":
        family = "Segoe UI Variable Text"
    elif sys.platform == "darwin":
        family = ".AppleSystemUIFont"
    else:
        family = "Sans Serif"
    font = QFont(family)
    font.setPixelSize(round(size_px))
    font.setWeight(weight)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def tabular(font: QFont) -> QFont:
    """Same font with tabular figures, so a changing % doesn't jiggle."""
    font = QFont(font)
    font.setFeature(QFont.Tag("tnum"), 1)
    return font
