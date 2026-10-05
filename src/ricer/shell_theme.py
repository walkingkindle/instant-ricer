"""Render the GNOME Shell stylesheet (top bar and its menus) for a Look."""
from __future__ import annotations

from importlib import resources
from string import Template

from ricer.look import Look
from ricer.palette import hex_to_rgb

BASE_FONT_SIZE = 11                  # pt, the stock top-bar text size
PANEL_HEIGHTS = {"cards": 44, "solid": 34}


def _rgb_triplet(color: str) -> str:
    return ", ".join(str(round(c * 255)) for c in hex_to_rgb(color))


def _template(name: str) -> Template:
    return Template(resources.files("ricer").joinpath("data", name).read_text())


def render(look: Look, base_import: str) -> str:
    """CSS for the look's bar style, layered over the stock theme named by `base_import`.

    `base_import` is the argument of the CSS @import, e.g. 'url("/usr/share/.../gnome-shell.css")'.
    """
    if look.bar_style not in PANEL_HEIGHTS:
        raise ValueError(f"bar style {look.bar_style!r} has no stylesheet")
    palette = look.palette
    values = {
        "base_import": base_import,
        "accent": palette.accent,
        "accent_end": palette.accent2 if look.gradient else palette.accent,
        "accent2_rgb": _rgb_triplet(palette.accent2),
        "text": palette.text,
        "card": palette.card,
        "card_rgb": _rgb_triplet(palette.card),
        "card_alpha": palette.card_alpha,
        "font_size": round(BASE_FONT_SIZE * look.widget_scale, 1),
        "panel_height": round(PANEL_HEIGHTS[look.bar_style] * look.widget_scale),
    }
    return (_template("common.css.tmpl").substitute(values)
            + _template(f"{look.bar_style}.css.tmpl").substitute(values))
