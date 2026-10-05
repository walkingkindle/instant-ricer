"""Clock widget: big time, optional seconds bar and date, drawn straight on the wallpaper."""
from __future__ import annotations

import math
import time

from ricer.widgets.drawing import draw_bar, draw_text, measure_text
from ricer.widgets.style import Style


class Clock:
    clickable = False

    def __init__(self, style: Style, options: dict, now=time.localtime):
        self.style = style
        self.now = now
        self.seconds = options.get("seconds", True)
        self.date = options.get("date", True)
        size = options.get("size", 120)
        weight = "Thin" if options.get("thin", True) else "Light"
        # the clock's size is its own setting; only the small date text follows the UI scale
        self.time_font = f"{style.font} {weight} {size}"
        self.date_font = style.font_desc(max(11, size / 6), "Light")
        self.spacing = size / 20

        self.time_w, self.time_h = measure_text("00:00", self.time_font, self.spacing)
        date_w, self.date_h = measure_text("WEDNESDAY, SEPTEMBER 30 · PM", self.date_font,
                                           self.spacing * 0.8)
        self.bar_w = self.time_w * 0.7
        self.width = math.ceil(max(self.time_w, date_w if self.date else 0)) + 40
        self.height = math.ceil(self.time_h + (26 if self.seconds else 8)
                                + (self.date_h + 14 if self.date else 0)) + 8

    def tick(self, _count: int) -> bool:
        return True

    def time_text(self, now) -> str:
        if self.style.clock_24h:
            return time.strftime("%H:%M", now)
        return time.strftime("%I:%M", now).lstrip("0")

    def date_text(self, now) -> str:
        text = time.strftime("%A, %B ", now).upper() + str(now.tm_mday)
        return text if self.style.clock_24h else f"{text} · {time.strftime('%p', now)}"

    def draw(self, cr) -> None:
        now = self.now()
        cx = self.width / 2
        draw_text(cr, self.time_text(now), self.time_font, cx, 0, self.style.text,
                  spacing=self.spacing, align="center", shadow=True)
        y = self.time_h + 8
        if self.seconds:
            # a thin track that fills up over the minute
            draw_bar(cr, self.style, cx - self.bar_w / 2, y + 6, self.bar_w, now.tm_sec / 59,
                     knob=True)
            y += 18
        if self.date:
            draw_text(cr, self.date_text(now), self.date_font, cx, y + 4, self.style.text,
                      alpha=0.95, spacing=self.spacing * 0.8, align="center", shadow=True)
