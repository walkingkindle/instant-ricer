"""Ornament widget: a small abstract figure generated from the look's seed.

It shows no information. It is there so that no two looks are quite alike.
"""
from __future__ import annotations

import math
import random

import cairo

from ricer import metrics
from ricer.widgets.drawing import Widget, rounded_rect, set_accent_source
from ricer.widgets.style import Style


class Ornament(Widget):
    design = "orbits"

    def __init__(self, style: Style, options: dict):
        super().__init__(style, options)
        self.size = options.get("size", 200)
        self.seed = options.get("seed", 0)
        width, height = metrics.ornament_size(self.design, self.size)
        self.width, self.height = math.ceil(width), math.ceil(height)

    def rng(self) -> random.Random:
        """The same figure every time it is drawn."""
        return random.Random(f"{self.seed}/{self.design}")


class Orbits(Ornament):
    """Concentric rings, some arcs lit in the accent, a few small bodies on them."""
    design = "orbits"

    def draw(self, cr) -> None:
        rng, style = self.rng(), self.style
        cx = cy = self.size / 2
        outer = self.size / 2 - 6
        rings = rng.randint(3, 5)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        for ring in range(rings):
            radius = outer * (ring + 1) / rings * rng.uniform(0.94, 1.0)
            cr.set_line_width(1.2)
            cr.set_source_rgba(*style.text, 0.28)
            cr.arc(cx, cy, radius, 0, 2 * math.pi)
            cr.stroke()
            if rng.random() < 0.7:                           # a lit arc
                start, sweep = rng.uniform(0, 2 * math.pi), rng.uniform(0.5, 2.4)
                cr.set_line_width(2.6 + 1.6 * style.weight)
                set_accent_source(cr, style, cx - radius, cx + radius, 0.9)
                cr.arc(cx, cy, radius, start, start + sweep)
                cr.stroke()
            if rng.random() < 0.6:                           # a body on the ring
                angle = rng.uniform(0, 2 * math.pi)
                colour = rng.choice((style.text, style.accent, style.accent2))
                cr.set_source_rgba(*colour, 0.95)
                cr.arc(cx + math.cos(angle) * radius, cy + math.sin(angle) * radius,
                       rng.uniform(3, 6.5), 0, 2 * math.pi)
                cr.fill()
        cr.set_source_rgba(*style.accent, 0.95)
        cr.arc(cx, cy, 4 + 3 * style.weight, 0, 2 * math.pi)
        cr.fill()


class Sigil(Ornament):
    """A mirrored block pattern, like a seal for this particular look."""
    design = "sigil"

    def draw(self, cr) -> None:
        rng, style = self.rng(), self.style
        cells = rng.choice((5, 5, 7))
        gap = self.width * 0.045
        cell = (self.width - gap * (cells + 1)) / cells
        half = (cells + 1) // 2
        pattern = [[rng.random() < 0.52 for _ in range(half)] for _ in range(cells)]
        lit = {(rng.randrange(cells), rng.randrange(half)) for _ in range(cells // 2)}
        for row in range(cells):
            for column in range(cells):
                source = min(column, cells - 1 - column)     # mirror left to right
                if not pattern[row][source]:
                    continue
                x, y = gap + column * (cell + gap), gap + row * (cell + gap)
                rounded_rect(cr, x, y, cell, cell, min(style.radius * 0.5, cell * 0.5))
                if (row, source) in lit:
                    set_accent_source(cr, style, 0, self.width, 0.95)
                else:
                    cr.set_source_rgba(*style.text, 0.5)
                cr.fill()


class Skyline(Ornament):
    """A row of bars of wandering height: a skyline, or a sound wave, in the accent."""
    design = "skyline"

    def draw(self, cr) -> None:
        rng, style = self.rng(), self.style
        count = rng.randint(16, 26)
        gap = self.width / count * 0.34
        bar = (self.width - gap * (count - 1)) / count
        level, base = rng.uniform(0.3, 0.7), self.height - 3
        set_accent_source(cr, style, 0, self.width, 0.92)
        for index in range(count):
            level = max(0.12, min(1.0, level + rng.uniform(-0.28, 0.28)))
            height = (self.height - 8) * level
            rounded_rect(cr, index * (bar + gap), base - height, bar, height, min(bar / 2, style.radius * 0.4))
            cr.fill()
        cr.set_source_rgba(*style.text, 0.5)
        cr.set_line_width(1.5)
        cr.move_to(0, base + 1.5)
        cr.line_to(self.width, base + 1.5)
        cr.stroke()


DESIGNS = {"orbits": Orbits, "sigil": Sigil, "skyline": Skyline}
