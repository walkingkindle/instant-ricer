"""Clock widget in four designs: digital, stacked, analog and words."""
from __future__ import annotations

import math
import time

import cairo

from ricer.widgets.drawing import (Widget, align_x, draw_bar, draw_text, measure_ink, measure_text,
                                   set_accent_source)
from ricer.widgets.style import Style

HOURS = ("twelve", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
         "eleven")
LEADS = {5: "five past", 10: "ten past", 15: "quarter past", 20: "twenty past",
         25: "twenty-five past", 30: "half past", 35: "twenty-five to", 40: "twenty to",
         45: "quarter to", 50: "ten to", 55: "five to"}


def time_text(style: Style, now) -> str:
    if style.clock_24h:
        return time.strftime("%H:%M", now)
    return time.strftime("%I:%M", now).lstrip("0")


def long_date(now) -> str:
    return time.strftime("%A, %B ", now) + str(now.tm_mday)


def short_date(now) -> str:
    return f"{time.strftime('%a', now)} {now.tm_mday} {time.strftime('%b', now)}"


def time_in_words(hour: int, minute: int) -> tuple[str, str]:
    """('twenty past', 'six'), to the nearest five minutes. On the hour: ('six', "o'clock")."""
    rounded = round(minute / 5) * 5
    if rounded > 30:
        hour += 1                                            # "quarter to seven"
    word = HOURS[hour % 12]
    if rounded in (0, 60):
        return word, "o'clock"
    return LEADS[rounded], word


class Clock(Widget):
    """Shared by the designs: the time source, the date line, and when to redraw."""

    def __init__(self, style: Style, options: dict, now=time.localtime):
        super().__init__(style, options)
        self.now = now
        self.size = options.get("size", 100)
        self.seconds = options.get("seconds", False)
        self.date = options.get("date", True)
        self.pad = style.px(20) if self.fill > 0 else 14
        # the date follows the clock's own size, not the look's text scale
        self.date_font = f"{style.font} {max(11, self.size / 6.5):g}"
        self.date_spacing = self.size / 26 if style.caps else 0
        self._minute = -1

    def date_line(self, now) -> str:
        text = self.style.label(long_date(now))
        return text if self.style.clock_24h else f"{text} · {time.strftime('%p', now)}"

    def date_size(self) -> tuple[int, int]:
        """Room for the longest date line, so the widget keeps one size all year."""
        sample = "Wednesday, September 30" + ("" if self.style.clock_24h else " · PM")
        return measure_text(self.style.label(sample), self.date_font, self.date_spacing)

    def draw_date(self, cr, now, y: float, text: str | None = None) -> None:
        draw_text(cr, text or self.date_line(now), self.date_font, align_x(self.align, self.width, self.pad),
                  y, self.style.text, alpha=0.92, spacing=self.date_spacing, align=self.align,
                  shadow=self.bare)

    def tick(self, _count: int) -> bool:
        minute = self.now().tm_min
        changed, self._minute = minute != self._minute, minute
        return self.seconds or changed


class DigitalClock(Clock):
    """One line of large digits, an optional seconds bar, the date."""

    def __init__(self, style: Style, options: dict, now=time.localtime):
        super().__init__(style, options, now)
        self.font = style.show(self.size, shift=-0.15)
        self.spacing = self.size / 20
        self.time_w, self.time_h = measure_ink("00:00", self.font, self.spacing)
        date_w, self.date_h = self.date_size() if self.date else (0, 0)
        self.bar_w = self.time_w * 0.7
        self.gap = self.size * 0.2
        self.width = math.ceil(max(self.time_w, date_w) + 2 * self.pad)
        self.height = math.ceil(self.pad + self.time_h + (self.gap if self.seconds else 0)
                                + (self.gap * 0.7 + self.date_h if self.date else 0) + self.pad)

    def draw(self, cr) -> None:
        now, style = self.now(), self.style
        self.draw_card(cr)
        x = align_x(self.align, self.width, self.pad)
        draw_text(cr, time_text(style, now), self.font, x, self.pad, style.text, spacing=self.spacing,
                  align=self.align, shadow=self.bare, ink=True)
        y = self.pad + self.time_h
        if self.seconds:
            # a thin track that fills up over the minute
            start = {"left": self.pad, "right": self.width - self.pad - self.bar_w}.get(
                self.align, (self.width - self.bar_w) / 2)
            y += self.gap
            draw_bar(cr, style, start, y, self.bar_w, now.tm_sec / 59, knob=True)
        if self.date:
            self.draw_date(cr, now, y + self.gap * 0.7)


class StackedClock(Clock):
    """Hours above minutes in heavy digits; the minutes take the accent."""

    def __init__(self, style: Style, options: dict, now=time.localtime):
        super().__init__(style, options, now)
        self.font = style.show(self.size * 0.95, shift=0.2)
        self.digit_w, self.digit_h = measure_ink("00", self.font)
        self.gap = self.size * 0.14
        self.date_spacing = self.size / 22
        date_w, self.date_h = (measure_text("WED 30 SEP", self.date_font, self.date_spacing)
                               if self.date else (0, 0))
        self.width = math.ceil(max(self.digit_w, date_w) + 2 * self.pad)
        self.height = math.ceil(self.pad + 2 * self.digit_h + self.gap
                                + (self.gap + self.date_h if self.date else 0) + self.pad)

    def draw(self, cr) -> None:
        now, style = self.now(), self.style
        self.draw_card(cr)
        x = align_x(self.align, self.width, self.pad)
        hours, minutes = time_text(style, now).split(":")
        draw_text(cr, hours.zfill(2), self.font, x, self.pad, style.text, align=self.align,
                  shadow=self.bare, ink=True)
        y = self.pad + self.digit_h + self.gap
        draw_text(cr, minutes, self.font, x, y, style.accent, align=self.align, shadow=self.bare,
                  accent=style, ink=True)
        if self.date:
            self.draw_date(cr, now, y + self.digit_h + self.gap, short_date(now).upper())


class AnalogClock(Clock):
    """A dial with hour marks and hands; the second hand takes the accent."""

    def __init__(self, style: Style, options: dict, now=time.localtime):
        super().__init__(style, options, now)
        self.diameter = self.size * 2
        self.date_spacing = self.size / 22
        # a short date, so the line stays about as wide as the dial above it
        date_w, self.date_h = (measure_text("WED 30 SEP", self.date_font, self.date_spacing)
                               if self.date else (0, 0))
        self.width = math.ceil(max(self.diameter + 8, date_w + 8))
        self.height = math.ceil(self.diameter + 8 + (self.date_h + 12 if self.date else 0))

    def _hand(self, cr, cx, cy, turn: float, length: float, width: float) -> None:
        angle = turn * 2 * math.pi - math.pi / 2
        cr.set_line_width(width)
        cr.move_to(cx - math.cos(angle) * length * 0.12, cy - math.sin(angle) * length * 0.12)
        cr.line_to(cx + math.cos(angle) * length, cy + math.sin(angle) * length)
        cr.stroke()

    def draw(self, cr) -> None:
        now, style = self.now(), self.style
        radius = self.diameter / 2
        cx, cy = align_x(self.align, self.width, radius + 4), radius + 4
        heavy = 1 + style.weight                             # 1 thin .. 2 heavy

        if self.fill > 0:                                    # the face
            cr.arc(cx, cy, radius, 0, 2 * math.pi)
            cr.set_source_rgba(*style.card, self.fill)
            cr.fill()
        cr.arc(cx, cy, radius - 1, 0, 2 * math.pi)           # the rim
        if style.border == "accent":
            set_accent_source(cr, style, cx - radius, cx + radius, 0.9)
        else:
            cr.set_source_rgba(*style.text, 0.35)
        cr.set_line_width(1.5 * heavy)
        cr.stroke()

        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        for mark in range(12):                               # hour marks; quarters are longer
            angle = mark / 12 * 2 * math.pi
            inner = radius * (0.84 if mark % 3 == 0 else 0.90)
            cr.set_source_rgba(*style.text, 0.85 if mark % 3 == 0 else 0.45)
            cr.set_line_width((2.2 if mark % 3 == 0 else 1.4) * heavy)
            cr.move_to(cx + math.cos(angle) * inner, cy + math.sin(angle) * inner)
            cr.line_to(cx + math.cos(angle) * radius * 0.95, cy + math.sin(angle) * radius * 0.95)
            cr.stroke()

        minutes = now.tm_min + now.tm_sec / 60
        for shadow in ((2, 0.30),) if self.bare else ():     # a little depth on a bare dial
            cr.set_source_rgba(0, 0, 0, shadow[1])
            self._hand(cr, cx, cy + shadow[0], (now.tm_hour % 12 + minutes / 60) / 12, radius * 0.52, 5 * heavy)
            self._hand(cr, cx, cy + shadow[0], minutes / 60, radius * 0.78, 3.2 * heavy)
        cr.set_source_rgba(*style.text, 0.97)
        self._hand(cr, cx, cy, (now.tm_hour % 12 + minutes / 60) / 12, radius * 0.52, 5 * heavy)
        self._hand(cr, cx, cy, minutes / 60, radius * 0.78, 3.2 * heavy)
        set_accent_source(cr, style, cx - radius, cx + radius)
        if self.seconds:
            self._hand(cr, cx, cy, now.tm_sec / 60, radius * 0.84, 1.6)
        cr.arc(cx, cy, 4.5 * heavy, 0, 2 * math.pi)
        cr.fill()

        if self.date:
            draw_text(cr, short_date(now).upper(), self.date_font, cx, self.diameter + 14, style.text,
                      alpha=0.92, spacing=self.date_spacing, align="center", shadow=self.bare)


class WordClock(Clock):
    """The time written out: a small lead-in line and the hour as the big word."""

    def __init__(self, style: Style, options: dict, now=time.localtime):
        super().__init__(style, options, now)
        self.lead_font = style.show(self.size * 0.30, shift=-0.1)
        self.hour_font = style.show(self.size * 0.56, shift=0.15)
        self.spacing = self.size / 40 if style.caps else 0
        leads = [style.label(text) for text in (*LEADS.values(), *HOURS)]
        hours = [style.label(text) for text in (*HOURS, "o'clock")]
        self.lead_h = measure_text(leads[0], self.lead_font, self.spacing)[1]
        self.hour_h = measure_text(hours[0], self.hour_font, self.spacing)[1]
        widest = max([measure_text(text, self.lead_font, self.spacing)[0] for text in leads]
                     + [measure_text(text, self.hour_font, self.spacing)[0] for text in hours])
        date_w, self.date_h = self.date_size() if self.date else (0, 0)
        self.width = math.ceil(max(widest, date_w) + 2 * self.pad)
        self.height = math.ceil(self.pad + self.lead_h + self.hour_h * 0.92
                                + (self.date_h + 10 if self.date else 0) + self.pad)

    def draw(self, cr) -> None:
        now, style = self.now(), self.style
        self.draw_card(cr)
        x = align_x(self.align, self.width, self.pad)
        lead, hour = time_in_words(now.tm_hour, now.tm_min)
        draw_text(cr, style.label(lead), self.lead_font, x, self.pad, style.text, alpha=0.9,
                  spacing=self.spacing, align=self.align, shadow=self.bare)
        y = self.pad + self.lead_h * 0.86
        draw_text(cr, style.label(hour), self.hour_font, x, y, style.accent, spacing=self.spacing,
                  align=self.align, shadow=self.bare, accent=style)
        if self.date:
            self.draw_date(cr, now, y + self.hour_h + 6)


DESIGNS = {"digital": DigitalClock, "stacked": StackedClock, "analog": AnalogClock, "words": WordClock}
