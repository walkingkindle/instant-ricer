"""Turn three dials into a Look. Pure: same dials, seed and wallpapers give the same Look."""
from __future__ import annotations

import random

from ricer.look import Dials, Dock, Look, WidgetSpec, dial_fraction
from ricer.palette import build_palette, nearest_gtk_accent, terminal_colors
from ricer.wallpapers import Wallpaper, choose

CLOCK_ANCHORS = ("top-center", "top-left", "top-right")


def bar_style(dials: Dials) -> str:
    if dials.ease >= 8:
        return "solid"                                       # readable, edge to edge
    if dials.cool <= 2:
        return "stock"                                       # minimal: leave the bar alone
    return "cards"


def dock(dials: Dials) -> Dock:
    ease = dial_fraction(dials.ease)
    return Dock(
        position="BOTTOM",
        autohide=dials.ease <= 6,
        floating=dials.ease <= 7,
        opacity=round(0.15 + 0.75 * ease, 2),
        icon_size=40 + 2 * round(8 * ease),
    )


def system_rows(dials: Dials) -> list[str]:
    rows = ["cpu", "ram", "temp"]
    if dials.ease >= 7:
        rows.append("gpu")
    if dials.ease >= 9:
        rows.append("battery")
    return rows


def widgets(dials: Dials, rng: random.Random | None = None) -> tuple[WidgetSpec, ...]:
    clock_anchor = rng.choice(CLOCK_ANCHORS) if rng else "top-center"
    corners = ["bottom-left", "bottom-right"]
    if rng and rng.random() < 0.5:
        corners.reverse()
    media_anchor, system_anchor = corners

    found = [WidgetSpec("clock", clock_anchor, {
        "size": round(64 + 76 * dial_fraction(dials.cool)),
        "thin": dials.cool >= 6,
        "seconds": dials.cool >= 5,
        "date": dials.cool >= 3 or dials.ease >= 3,
    })]
    if dials.cool >= 4 or dials.ease >= 6:
        found.append(WidgetSpec("media", media_anchor, {}))
    if dials.ease >= 4 or dials.cool >= 8:
        found.append(WidgetSpec("system", system_anchor, {"rows": system_rows(dials)}))
    return tuple(found)


def generate(dials: Dials, wallpapers: list[Wallpaper], seed: int = 0) -> Look:
    """Build the Look for these dials. Seed 0 is the canonical look; others are variants."""
    dials.validate()
    rng = random.Random(seed) if seed else None
    wallpaper = choose(wallpapers, dials, rng)
    palette = build_palette(list(wallpaper.colors), dials, rng)
    look = Look(
        dials=dials,
        seed=seed,
        wallpaper=wallpaper.path,
        palette=palette,
        gtk_accent=nearest_gtk_accent(palette.accent),
        bar_style=bar_style(dials),
        gradient=dials.cool >= 4,
        blur=dials.cool >= 5,
        dock=dock(dials),
        widget_scale=round(1.0 + 0.25 * dial_fraction(dials.ease), 2),
        terminal=terminal_colors(palette),
        widgets=widgets(dials, rng),
    )
    look.validate()
    return look
