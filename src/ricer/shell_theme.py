"""Render the GNOME Shell stylesheet (top bar and its menus) for a Look."""
from __future__ import annotations

from importlib import resources
from string import Template

from ricer.look import Look
from ricer.palette import hex_to_rgb

BASE_FONT_SIZE = 11                  # pt, the stock top-bar text size
FLOATING_HEIGHT = 44                 # px: bar styles that float leave room around their pieces
SLIM_HEIGHT = 34
STYLED = ("minimal", "island", "cards", "solid")             # every bar style except "stock"
BORDERS = {"none": "transparent", "hairline": "rgba(255, 255, 255, 0.10)"}


def _rgb_triplet(color: str) -> str:
    return ", ".join(str(round(c * 255)) for c in hex_to_rgb(color))


def _template(name: str) -> Template:
    return Template(resources.files("ricer").joinpath("data", name).read_text())


def render(look: Look, base_import: str) -> str:
    """CSS for the look's bar style, layered over the stock theme named by `base_import`.

    `base_import` is the argument of the CSS @import, e.g. 'url("/usr/share/.../gnome-shell.css")'.
    """
    bar = look.bar.style
    if bar not in STYLED:
        raise ValueError(f"bar style {bar!r} has no stylesheet")
    palette, style = look.palette, look.style
    floating = round(FLOATING_HEIGHT * style.scale)
    # a very round style turns the pieces into pills; no rounder than that is possible
    radius = min(style.radius, (floating - 10) // 2)
    values = {
        "base_import": base_import,
        "accent": palette.accent,
        "accent_end": palette.accent2 if style.gradient else palette.accent,
        "accent2_rgb": _rgb_triplet(palette.accent2),
        "text": palette.text,
        "text_rgb": _rgb_triplet(palette.text),
        "accent_rgb": _rgb_triplet(palette.accent),
        "card": palette.card,
        "card_rgb": _rgb_triplet(palette.card),
        "bar_alpha": max(0.5, style.fill),                   # the bar always needs a readable backing
        "solid_alpha": max(0.85, style.fill),
        "border": BORDERS.get(style.border, f"rgba({_rgb_triplet(palette.accent)}, 0.85)"),
        "radius": radius,
        "button_radius": max(4, radius - 4),
        "menu_radius": min(24, style.radius + 2),
        "card_radius": max(3, min(16, style.radius - 4)),    # cards inside a menu, a step tighter
        "font_size": round(BASE_FONT_SIZE * style.scale, 1),
        "panel_height": floating,
        "island_height": floating - 10,                      # its 7px + 3px margins make up the rest
        "slim_height": round(SLIM_HEIGHT * style.scale),
    }
    return (_template("common.css.tmpl").substitute(values)
            + _template(f"{bar}.css.tmpl").substitute(values))
