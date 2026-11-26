"""Stylesheet for the app's normal windows (settings, Connect prompt), from the palette."""

from __future__ import annotations

from taskpill.ui.theme import Palette, qcolor


def shell_stylesheet(pal: Palette) -> str:
    # rgba(), not 8-digit hex: Qt stylesheets read #AARRGGBB, not #RRGGBBAA.
    primary_text = "#15131F" if pal.dark else "#FFFFFF"
    border = "rgba(255,255,255,0.15)" if pal.dark else "rgba(0,0,0,0.18)"
    hover = "rgba(255,255,255,0.07)" if pal.dark else "rgba(0,0,0,0.05)"
    accent = qcolor(pal.working)
    tint = f"rgba({accent.red()},{accent.green()},{accent.blue()},{0.12 if pal.dark else 0.07})"
    return f"""
    QWidget#Shell {{ background: {pal.surface}; }}
    QWidget#Shell QLabel {{ color: {pal.text}; background: transparent; }}
    QLabel[role="section"] {{
        font-size: 13px; font-weight: 600; padding: 6px 0px 0px 0px; margin: 0px;
    }}
    QLabel[role="title"] {{ font-size: 15px; font-weight: 600; }}
    QLabel[role="label"] {{ font-size: 12.5px; }}
    QLabel[role="hint"], QLabel[role="body"] {{ color: {pal.text_soft}; font-size: 12px; }}
    QLabel[role="error"] {{ color: {pal.needs_you}; font-size: 12px; }}
    QPushButton {{
        color: {pal.text}; background: transparent; border: 1px solid {border};
        border-radius: 8px; padding: 5px 14px; font-size: 12.5px; min-height: 18px;
    }}
    QPushButton:hover {{ background: {hover}; }}
    QPushButton:focus {{ border: 2px solid {pal.working}; padding: 4px 13px; }}
    QPushButton[role="primary"] {{
        color: {primary_text}; background: {pal.working}; border: 1px solid {pal.working};
        font-weight: 600;
    }}
    QPushButton[role="primary"]:hover {{ background: {pal.working}; border-color: {pal.text}; }}
    QLabel[role="strong"] {{ font-size: 13px; font-weight: 600; }}
    QFrame#rule {{ background: {border}; border: none; }}
    QFrame#section {{ border: 1px solid {border}; border-radius: 10px; background: transparent; }}
    QFrame#connectBox {{
        border: 1px solid {border}; border-radius: 10px; background: transparent;
    }}
    QFrame#connectBox[needsConnect="true"] {{
        border: 2px solid {pal.working}; background: {tint};
    }}
    QToolTip {{
        background: {pal.surface}; color: {pal.text}; border: 1px solid {border};
        border-radius: 8px; padding: 6px 8px; font-size: 12px;
    }}
    """
