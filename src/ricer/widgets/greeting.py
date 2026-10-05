"""Greeting widget: a time-of-day line with the user's name, and the date under it."""
from __future__ import annotations

import math
import os
import pwd
import time

from ricer.widgets.drawing import Widget, align_x, draw_text, measure_text
from ricer.widgets.style import Style


def greeting_for(hour: int) -> str:
    if 5 <= hour < 12:
        return "Good morning"
    if 12 <= hour < 18:
        return "Good afternoon"
    if 18 <= hour < 23:
        return "Good evening"
    return "Good night"


def first_name(lookup=None) -> str:
    """The user's first name from the account's real name, else the login name; '' if unknown."""
    try:
        entry = (lookup or pwd.getpwuid)(os.getuid())
    except (KeyError, OSError):
        return ""
    real = entry.pw_gecos.split(",")[0].split()
    return real[0] if real else entry.pw_name.capitalize()


class Greeting(Widget):
    def __init__(self, style: Style, options: dict, now=time.localtime, name: str | None = None):
        super().__init__(style, options)
        self.now = now
        self.name = (first_name() if name is None else name) if options.get("name", True) else ""
        size = options.get("size", 24) * style.scale
        self.font = style.show(size, shift=-0.1)
        self.date_font = style.ui(12, "Medium")
        self.pad = style.px(18) if self.fill > 0 else 10
        line_w, self.line_h = measure_text(self.line(13), self.font)       # the longest greeting
        date_w, self.date_h = measure_text(style.label("Wednesday, September 30"), self.date_font,
                                           style.label_spacing)
        self.width = math.ceil(max(line_w, date_w) + 2 * self.pad)
        self.height = math.ceil(self.pad + self.line_h + self.date_h + style.px(4) + self.pad)
        self._shown = None

    def line(self, hour: int) -> str:
        return f"{greeting_for(hour)}, {self.name}" if self.name else greeting_for(hour)

    def tick(self, _count: int) -> bool:
        now = self.now()
        shown, self._shown = self._shown, (now.tm_hour, now.tm_yday)
        return shown != self._shown

    def draw(self, cr) -> None:
        now, style = self.now(), self.style
        self.draw_card(cr)
        x = align_x(self.align, self.width, self.pad)
        draw_text(cr, self.line(now.tm_hour), self.font, x, self.pad, style.text, align=self.align,
                  shadow=self.bare)
        date = style.label(time.strftime("%A, %B ", now) + str(now.tm_mday))
        draw_text(cr, date, self.date_font, x, self.pad + self.line_h + style.px(4), style.accent,
                  spacing=style.label_spacing, align=self.align, shadow=self.bare, accent=style)


DESIGNS = {"plain": Greeting}
