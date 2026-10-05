#!/usr/bin/env python3
"""Developer tool: draw a look as it would appear on the desktop, without touching the desktop.

    .venv/bin/python tools/preview.py out.png                 the look ricer has applied now
    .venv/bin/python tools/preview.py out.png --cool 8 ...    a fresh look for these dials
    .venv/bin/python tools/preview.py out.png --grid 3x3 ...  several fresh looks on one sheet

Wallpaper, a sketch of the top bar and dock, and every widget in its zone. Widgets show
sample data (a fixed time, a made-up track) so that sheets can be compared.
"""
import argparse
import datetime
import json
import random
import time

import cairo
from PIL import Image

from ricer.capabilities import DEFAULT_SCREEN, font_voices, installed_font_families
from ricer.compose import compose, remember
from ricer.engine import widgets_config
from ricer.look import Dials, Look
from ricer.palette import hex_to_rgb
from ricer.paths import Paths
from ricer.placement import BAR_HEIGHT, arrange, dock_insets
from ricer.wallpapers import Library
from ricer.widgets.catalog import CATALOG
from ricer.widgets.style import Style

NOW = time.struct_time((2026, 10, 5, 18, 56, 41, 0, 278, 0))
TODAY, WHEN = datetime.date(2026, 10, 5), datetime.datetime(2026, 10, 5, 18, 56, 41)
TRACK = {"xesam:title": "Night Drive Through Shibuya", "xesam:artist": ["Example Artist"],
         "mpris:length": 215_000_000}


class Caps:
    """Just enough of Capabilities for widgets_config()."""
    widgets, clock_24h = True, True

    def __init__(self, font="Ubuntu Sans", mono="Ubuntu Sans Mono"):
        self.font = font
        self.fonts = font_voices(font, mono, installed_font_families())

    def font_for(self, voice):
        return self.fonts.get(voice) or self.font


def sample_widget(style, spec):
    kind, cls, options = spec["type"], CATALOG[spec["type"]][spec["design"]], spec["options"]
    if kind == "clock":
        return cls(style, options, now=lambda: NOW)
    if kind == "greeting":
        return cls(style, options, now=lambda: NOW)
    if kind == "calendar":
        return cls(style, options, today=lambda: TODAY)
    if kind == "progress":
        return cls(style, options, now=lambda: WHEN)
    widget = cls(style, options)
    if kind == "media":
        widget.running = widget.playing = True
        widget.metadata, widget.position = TRACK, 83_000_000
    if kind == "system":
        widget.cpu = 0.37
    return widget


def wallpaper_surface(path, screen):
    image = Image.open(path).convert("RGBA")
    zoom = max(screen[0] / image.width, screen[1] / image.height)
    image = image.resize((round(image.width * zoom), round(image.height * zoom)))
    x, y = (image.width - screen[0]) // 2, (image.height - screen[1]) // 2
    image = image.crop((x, y, x + screen[0], y + screen[1]))
    data = bytearray(image.tobytes("raw", "BGRa"))
    borrowed = cairo.ImageSurface.create_for_data(data, cairo.FORMAT_ARGB32, *screen)
    owned = cairo.ImageSurface(cairo.FORMAT_ARGB32, *screen)     # a copy that outlives `data`
    cr = cairo.Context(owned)
    cr.set_source_surface(borrowed, 0, 0)
    cr.paint()
    return owned


def sketch_bar(cr, look, screen):
    """A rough stand-in for the top bar, so the bar style is visible on the sheet."""
    card, text = hex_to_rgb(look.palette.card), hex_to_rgb(look.palette.text)
    accent, bar, w = hex_to_rgb(look.palette.accent), look.bar, screen[0]
    alpha = max(0.5, look.style.fill)
    pieces = {"cards": [(12, 7, 150, 34), (w / 2 - 80, 7, 160, 34), (w - 282, 7, 270, 34)],
              "island": [(12, 7, w - 24, 34)], "solid": [(0, 0, w, 34)],
              "stock": [(0, 0, w, 30)], "minimal": []}[bar.style]
    for x, y, width, height in pieces:
        radius = 0 if bar.style in ("solid", "stock") else min(look.style.radius, 17)
        cr.new_sub_path()
        cr.arc(x + width - radius, y + radius, radius, -1.5708, 0)
        cr.arc(x + width - radius, y + height - radius, radius, 0, 1.5708)
        cr.arc(x + radius, y + height - radius, radius, 1.5708, 3.1416)
        cr.arc(x + radius, y + radius, radius, 3.1416, 4.7124)
        cr.close_path()
        cr.set_source_rgba(*((0.07, 0.07, 0.07, 1.0) if bar.style == "stock" else (*card, alpha)))
        cr.fill()
    cr.select_font_face("Ubuntu Sans")
    cr.set_font_size(15)
    items = [(w / 2 - 42, "Oct 5  18:56", accent), (30, "● ○", text), (w - 120, "wifi  vol  pwr", text)]
    sides = {"left": 110, "center": w / 2 + 70, "right": w - 470}
    if bar.stats:
        items.append((sides[bar.stats_side], "  ".join(bar.stats), text))
    if bar.media:
        items.append((sides[bar.media_side] + (190 if bar.media_side == bar.stats_side and bar.stats else 0),
                      "♪ Night Drive ▶", text))
    for x, label, colour in items:
        cr.set_source_rgba(*colour, 0.95)
        cr.move_to(x, 29 if bar.style != "stock" else 21)
        cr.show_text(label)
        cr.new_path()


def sketch_dock(cr, look, screen):
    dock, (w, h) = look.dock, screen
    size, count = dock.icon_size, 7
    length, thick = count * (size + 10) + 16, size + 20
    colour = hex_to_rgb(look.palette.card) if dock.tint else (0.1, 0.1, 0.1)
    if dock.position == "BOTTOM":
        rect = (0, h - thick, w, thick) if not dock.floating else ((w - length) / 2, h - thick - 6, length, thick)
    else:
        x = 6 if dock.position == "LEFT" else w - thick - 6
        rect = ((0 if dock.position == "LEFT" else w - thick, BAR_HEIGHT, thick, h - BAR_HEIGHT)
                if not dock.floating else (x, (h - length) / 2, thick, length))
    cr.rectangle(*rect)
    cr.set_source_rgba(*colour, max(0.25, dock.opacity))
    cr.fill()
    for index in range(count):
        if dock.position == "BOTTOM":
            cx, cy = rect[0] + (rect[2] - length) / 2 + 13 + index * (size + 10) + size / 2, rect[1] + thick / 2
        else:
            cx, cy = rect[0] + thick / 2, rect[1] + (rect[3] - length) / 2 + 13 + index * (size + 10) + size / 2
        cr.arc(cx, cy, size / 2 - 3, 0, 6.2832)
        cr.set_source_rgba(1, 1, 1, 0.22)
        cr.fill()


def draw_look(look: Look, screen, caps) -> cairo.ImageSurface:
    surface = wallpaper_surface(look.wallpaper, screen)
    cr = cairo.Context(surface)
    sketch_bar(cr, look, screen)
    sketch_dock(cr, look, screen)
    config = widgets_config(look, caps)
    config = json.loads(json.dumps(config))
    style = Style.from_config(config)
    widgets = [sample_widget(style, spec) for spec in config["widgets"]]
    thick = look.dock.icon_size + 20
    area = [0, BAR_HEIGHT, screen[0], screen[1] - BAR_HEIGHT]
    if not look.dock.autohide:                               # a fixed dock shrinks the work area
        if look.dock.position == "BOTTOM":
            area[3] -= thick
        elif look.dock.position == "LEFT":
            area[0], area[2] = thick, area[2] - thick
        else:
            area[2] -= thick
    spots = arrange([(spec["anchor"], w.width, w.height) for spec, w in zip(config["widgets"], widgets)],
                    tuple(area), dock_insets(look.dock))
    for widget, (x, y) in zip(widgets, spots):
        cr.save()
        cr.translate(x, y)
        widget.draw(cr)
        cr.restore()
    return surface


def caption(cr, look, width, y):
    cr.select_font_face("Ubuntu Sans")
    cr.set_font_size(22)
    d = look.dials
    text = (f"cool {d.cool}  ease {d.ease}  warmth {d.warmth}  chaos {d.chaos}  seed {look.seed}   ·   "
            f"{look.layout}{' mirrored' if look.mirrored else ''}, bar {look.bar.style}, "
            f"{look.style.voice} type, {'no cards' if look.style.fill == 0 else look.style.border}")
    cr.set_source_rgba(0, 0, 0, 0.75)
    cr.rectangle(0, y, width, 34)
    cr.fill()
    cr.set_source_rgba(1, 1, 1, 0.95)
    cr.move_to(12, y + 24)
    cr.show_text(text)
    cr.new_path()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out")
    for name in ("cool", "ease", "warmth", "chaos"):
        parser.add_argument(f"--{name}", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--grid", default=None, help="COLSxROWS fresh looks on one sheet")
    parser.add_argument("--entropy", type=int, default=None, help="make a sheet repeatable")
    args = parser.parse_args()

    paths, caps, screen = Paths.from_env(), Caps(), DEFAULT_SCREEN
    fresh = args.grid or args.seed is not None or any(getattr(args, n) is not None for n in ("cool", "ease", "warmth", "chaos"))
    if not fresh:
        look = Look.from_dict(json.loads(paths.state_file.read_text())["look"])
        draw_look(look, screen, caps).write_to_png(args.out)
        print(f"{args.out}: the current look (seed {look.seed})")
        return

    dials = Dials(*(getattr(args, n) or 5 for n in ("cool", "ease", "warmth", "chaos")))
    walls = Library(paths.wallpapers, paths.wallpaper_cache).scan()
    cols, rows = (int(v) for v in (args.grid or "1x1").split("x"))
    entropy = random.Random(args.entropy) if args.entropy is not None else None
    history, looks = [], []
    for _ in range(cols * rows):
        look = compose(dials, walls, history, seed=args.seed, entropy=entropy)
        history = remember(history, look)
        looks.append(look)
    tile = (screen[0] // cols, screen[1] // cols) if cols > 1 else screen
    sheet = cairo.ImageSurface(cairo.FORMAT_ARGB32, tile[0] * cols, tile[1] * rows)
    cr = cairo.Context(sheet)
    for index, look in enumerate(looks):
        full = draw_look(look, screen, caps)
        caption(cairo.Context(full), look, screen[0], screen[1] - 34)
        cr.save()
        cr.translate((index % cols) * tile[0], (index // cols) * tile[1])
        cr.scale(tile[0] / screen[0], tile[1] / screen[1])
        cr.set_source_surface(full, 0, 0)
        cr.paint()
        cr.restore()
    sheet.write_to_png(args.out)
    print(f"{args.out}: {len(looks)} look(s) for cool {dials.cool} ease {dials.ease} warmth {dials.warmth} chaos {dials.chaos}")


if __name__ == "__main__":
    main()
