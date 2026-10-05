#!/usr/bin/env python3
"""Developer tool: draw every widget design under several styles on one sheet.

    .venv/bin/python tools/contact_sheet.py out.png [wallpaper]

This is how new designs are judged before they go anywhere near a real desktop: each
column is one style (card shape, typeface, weight, colours), each cell a design.
"""
import datetime
import sys
import time

import cairo
from PIL import Image

from ricer.look import DESIGNS
from ricer.palette import hex_to_rgb
from ricer.widgets.catalog import CATALOG
from ricer.widgets.style import Style

NOW = time.struct_time((2026, 10, 5, 18, 56, 41, 0, 278, 0))
TODAY = datetime.date(2026, 10, 5)
WHEN = datetime.datetime(2026, 10, 5, 18, 56, 41)
TRACK = {"xesam:title": "Night Drive Through Shibuya", "xesam:artist": ["Example Artist"],
         "mpris:length": 215_000_000}

AMBER, VIOLET, CYAN, PINK = "#f2c27d", "#b88cff", "#74c8f1", "#f17ca0"
STYLES = [
    ("glass · ui · light", dict(accent=AMBER, accent2=VIOLET, fill=0.58, border="hairline", radius=18,
                                weight=0.2, display="Ubuntu Sans", caps=True, gradient=True, scale=1.0)),
    ("outline · mono · cold", dict(accent=CYAN, accent2=VIOLET, fill=0.42, border="accent", radius=6,
                                   weight=0.5, display="Ubuntu Sans Mono", caps=True, gradient=False,
                                   scale=1.0)),
    ("bare · serif · warm", dict(accent=AMBER, accent2=PINK, fill=0.0, border="none", radius=24,
                                 weight=0.35, display="Noto Serif Display", caps=False, gradient=True,
                                 scale=1.0)),
    ("solid · condensed · heavy · big", dict(accent=PINK, accent2=AMBER, fill=0.85, border="none",
                                             radius=12, weight=0.85, display="Ubuntu Sans Condensed",
                                             caps=True, gradient=True, scale=1.2)),
]
OPTIONS = {
    "clock": {"size": 96, "seconds": True, "date": True},
    "greeting": {"size": 26},
    "system": {"rows": ["cpu", "ram", "temp", "gpu"]},
    "progress": {"rows": ["day", "week", "month", "year"]},
    "ornament": {"size": 200, "seed": 20261005},
}
COLUMN, GUTTER, HEADER = 700, 26, 44


def make_style(spec: dict) -> Style:
    spec = dict(spec)
    return Style(accent=hex_to_rgb(spec.pop("accent")), accent2=hex_to_rgb(spec.pop("accent2")),
                 text=hex_to_rgb("#f2f7ff"), hot=hex_to_rgb("#ff6b6b"), card=hex_to_rgb("#14121f"),
                 font="Ubuntu Sans", **spec)


def make_widget(kind: str, design: str, style: Style):
    options = {**OPTIONS.get(kind, {}), "fill": style.fill}
    cls = CATALOG[kind][design]
    if kind == "clock":
        return cls(style, options, now=lambda: NOW)
    if kind == "greeting":
        return cls(style, options, now=lambda: NOW, name="Aleksa")
    if kind == "calendar":
        return cls(style, options, today=lambda: TODAY)
    if kind == "progress":
        return cls(style, options, now=lambda: WHEN)
    widget = cls(style, options)
    if kind == "media":
        widget.running = widget.playing = True
        widget.metadata, widget.position = TRACK, 83_000_000
    if kind == "system":
        widget.cpu, widget.gpu = 0.37, 71.0
    return widget


def main():
    out = sys.argv[1]
    cells = [(kind, design) for kind, designs in DESIGNS.items() for design in designs]
    columns = []
    for _name, spec in STYLES:
        style = make_style(spec)
        columns.append([make_widget(kind, design, style) for kind, design in cells])
    row_heights = [max(column[i].height for column in columns) + 30 for i in range(len(cells))]
    width = len(STYLES) * COLUMN
    height = HEADER + sum(row_heights) + GUTTER

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)
    if len(sys.argv) > 2:                                    # tile a wallpaper behind, for realism
        image = Image.open(sys.argv[2]).convert("RGBA")
        scale = max(width / image.width, 1080 / image.height)
        image = image.resize((round(image.width * scale), round(image.height * scale)))
        tile = cairo.ImageSurface.create_for_data(
            bytearray(image.tobytes("raw", "BGRa")), cairo.FORMAT_ARGB32, image.width, image.height)
        for y in range(0, height, image.height):
            cr.set_source_surface(tile, 0, y)
            cr.paint()
    else:
        cr.set_source_rgb(0.16, 0.2, 0.3)
        cr.paint()

    cr.select_font_face("Ubuntu Sans")
    for index, (name, _spec) in enumerate(STYLES):
        cr.set_source_rgba(1, 1, 1, 0.9)
        cr.set_font_size(17)
        cr.move_to(index * COLUMN + GUTTER, 28)
        cr.show_text(name)
        cr.new_path()
    y = HEADER
    for row, (kind, design) in enumerate(cells):
        for index, column in enumerate(columns):
            widget = column[row]
            cr.save()
            cr.translate(index * COLUMN + GUTTER, y + 22)
            widget.draw(cr)
            cr.restore()
            cr.set_source_rgba(1, 1, 1, 0.55)
            cr.set_font_size(11)
            cr.move_to(index * COLUMN + GUTTER, y + 14)
            cr.show_text(f"{kind} / {design}   {widget.width}x{widget.height}")
            cr.new_path()
        y += row_heights[row]
    surface.write_to_png(out)
    print(f"{out}: {len(cells)} designs x {len(STYLES)} styles, {width}x{height}")


if __name__ == "__main__":
    main()
