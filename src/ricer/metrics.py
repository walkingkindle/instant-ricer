"""Sizes of widget designs in pixels.

Shared by the generator, which plans placement without a display, and the widgets, which
size themselves from the same numbers. Card designs are exact. Designs made of large text
are estimates here; those widgets measure their real text when they are built.
"""
from __future__ import annotations

import math

PAD = 18                             # inner padding of a card
ROW = 32                             # height of one bar row in system and progress cards
WIDTH_AWARE = {("calendar", "month"), ("calendar", "week"), ("calendar", "day"),
               ("media", "card"), ("media", "pill"), ("media", "cover"),
               ("system", "bars"), ("system", "rings"), ("progress", "bars")}
# designs that are a frame around content, as opposed to free-standing display text
STRUCTURED = {"calendar", "media", "system", "progress"}


def rows_card(count: int, width: float | None = None) -> tuple[float, float]:
    return width or 260, 36 + ROW * count


def system_size(design: str, rows: int, width: float | None = None) -> tuple[float, float]:
    if design == "rings":
        return width or 36 + 76 * rows, 116
    if design == "line":
        return 28 + 98 * rows, 42
    return rows_card(rows, width)


def media_size(design: str, width: float | None = None) -> tuple[float, float]:
    if design == "pill":
        return width or 340, 68
    if design == "cover":
        width = width or 232
        return width, width + 112
    return width or 420, 132


def month_cell(width: float) -> float:
    return (width - 2 * PAD) / 7


def calendar_size(design: str, width: float | None = None, weeks: int = 6) -> tuple[float, float]:
    if design == "week":
        return width or 308, 88
    if design == "day":
        return width or 230, 104
    width = width or 274
    return width, 62 + weeks * month_cell(width) * 0.86 + 14


def clock_size(design: str, size: float, seconds: bool, date: bool) -> tuple[float, float]:
    """Estimate for display clocks; `size` is the point size of the digits.

    Deliberately on the generous side: typefaces differ in width, and planning for a clock
    that turns out smaller is harmless while the reverse makes widgets collide.
    """
    date_h = size * 0.5 if date else 0
    if design == "stacked":
        return size * 1.75 + 40, size * 2.45 + date_h + 8
    if design == "analog":
        return size * 2 + 8, size * 2 + 8 + date_h * 0.8
    if design == "words":
        return size * 4.6 + 24, size * 2.0 + date_h
    return size * 4.6 + 40, 28 + size * (0.95 + (0.2 if seconds else 0)) + date_h


def greeting_size(size: float) -> tuple[float, float]:
    return size * 19, size * 2.2 + 34


def ornament_size(design: str, size: float) -> tuple[float, float]:
    if design == "skyline":
        return size * 1.9, size * 0.62
    if design == "sigil":
        return size * 0.6, size * 0.6                        # solid blocks carry more weight per pixel
    return size, size


def nominal(kind: str, design: str, options: dict, scale: float) -> tuple[int, int]:
    """Planned pixel size of a widget under the look's scale."""
    width = options.get("width")
    if kind == "clock":
        w, h = clock_size(design, options.get("size", 100), options.get("seconds", False),
                          options.get("date", True))
    elif kind == "greeting":
        w, h = greeting_size(options.get("size", 24) * scale)
    elif kind == "ornament":
        w, h = ornament_size(design, options.get("size", 200))
    else:
        if kind == "system":
            w, h = system_size(design, len(options.get("rows", ())), width)
        elif kind == "progress":
            w, h = rows_card(len(options.get("rows", ())), width)
        elif kind == "media":
            w, h = media_size(design, width)
        else:
            w, h = calendar_size(design, width)
        w, h = w * scale, h * scale
    return math.ceil(w), math.ceil(h)
