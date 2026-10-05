"""Calendar widget in three designs: a month grid, a week strip, and a big day block."""
from __future__ import annotations

import calendar as months
import datetime
import math

from ricer import metrics
from ricer.widgets.drawing import Widget, draw_text, measure_text, rounded_rect, set_accent_source
from ricer.widgets.style import Style

WEEKDAYS = "MTWTFSS"                 # weeks start on Monday


class Calendar(Widget):
    design = "month"

    def __init__(self, style: Style, options: dict, today=datetime.date.today):
        super().__init__(style, options)
        self.today = today
        self.logical_width = options.get("width") or metrics.calendar_size(self.design)[0]
        self.width = math.ceil(style.px(self.logical_width))
        self.pad = style.px(metrics.PAD)
        self._day = None
        self.resize()

    def resize(self) -> None:
        self.height = math.ceil(self.style.px(metrics.calendar_size(self.design, self.logical_width)[1]))

    def tick(self, _count: int) -> bool:
        day = self.today()
        changed, self._day = day != self._day, day
        if changed:
            self.resize()                                    # a new month can need another row
        return changed

    def ink(self) -> tuple:
        """Colour for text drawn on top of an accent shape."""
        return self.style.card


class MonthCalendar(Calendar):
    design = "month"

    def weeks(self) -> list[list[int]]:
        day = self.today()
        return months.Calendar(firstweekday=0).monthdayscalendar(day.year, day.month)

    def resize(self) -> None:
        size = metrics.calendar_size("month", self.logical_width, len(self.weeks()))
        self.height = math.ceil(self.style.px(size[1]))

    def draw(self, cr) -> None:
        style, day, px = self.style, self.today(), self.style.px
        self.draw_card(cr)
        cell = (self.width - 2 * self.pad) / 7
        row_h = cell * 0.86

        draw_text(cr, style.label(day.strftime("%B")), style.ui(12, "Medium"), self.pad, px(15),
                  style.accent, spacing=style.label_spacing, shadow=self.bare, accent=style)
        draw_text(cr, str(day.year), style.ui(11), self.width - self.pad, px(16), style.text,
                  alpha=0.6, align="right", shadow=self.bare)
        for column, letter in enumerate(WEEKDAYS):
            draw_text(cr, letter, style.ui(9), self.pad + (column + 0.5) * cell, px(41), style.text,
                      alpha=0.5, align="center", shadow=self.bare)

        number_font, today_font = style.ui(11), style.ui(11, "Bold")
        text_h = measure_text("0", number_font)[1]
        for row, week in enumerate(self.weeks()):
            for column, number in enumerate(week):
                if not number:
                    continue
                cx = self.pad + (column + 0.5) * cell
                cy = px(62) + row * row_h + row_h / 2
                if number == day.day:
                    radius = min(row_h, cell) * 0.46
                    cr.arc(cx, cy, radius, 0, 2 * math.pi)
                    set_accent_source(cr, style, cx - radius, cx + radius)
                    cr.fill()
                    draw_text(cr, str(number), today_font, cx, cy - text_h / 2, self.ink(), align="center")
                else:
                    draw_text(cr, str(number), number_font, cx, cy - text_h / 2, style.text,
                              alpha=0.62 if column >= 5 else 0.92, align="center", shadow=self.bare)


class WeekCalendar(Calendar):
    design = "week"

    def draw(self, cr) -> None:
        style, day, px = self.style, self.today(), self.style.px
        self.draw_card(cr)
        column_w = (self.width - 2 * self.pad) / 7
        monday = day - datetime.timedelta(days=day.weekday())
        for column in range(7):
            date = monday + datetime.timedelta(days=column)
            cx = self.pad + (column + 0.5) * column_w
            current = date == day
            if current:
                rounded_rect(cr, cx - column_w / 2 + px(3), px(9), column_w - px(6), self.height - px(18),
                             min(style.radius, px(12)))
                set_accent_source(cr, style, cx - column_w / 2, cx + column_w / 2)
                cr.fill()
            colour = self.ink() if current else style.text
            draw_text(cr, WEEKDAYS[column], style.ui(9, "Medium"), cx, px(17), colour,
                      alpha=1.0 if current else 0.55, align="center", shadow=self.bare and not current)
            draw_text(cr, str(date.day), style.ui(15, "Bold" if current else "Medium"), cx, px(38), colour,
                      alpha=1.0 if current or column < 5 else 0.62, align="center",
                      shadow=self.bare and not current)


class DayCalendar(Calendar):
    """A big day number with the weekday and month beside it."""
    design = "day"

    def draw(self, cr) -> None:
        style, day, px = self.style, self.today(), self.style.px
        self.draw_card(cr)
        number_font = style.show(px(46), shift=0.1)
        number_w, number_h = measure_text("00", number_font)
        y = (self.height - number_h) / 2
        draw_text(cr, f"{day.day:02d}", number_font, self.pad, y, style.accent, shadow=self.bare,
                  accent=style)
        x = self.pad + number_w + px(14)
        draw_text(cr, style.label(day.strftime("%A")), style.ui(13, "Medium"), x, self.height / 2 - px(27),
                  style.text, spacing=style.label_spacing, shadow=self.bare)
        draw_text(cr, day.strftime("%B %Y"), style.ui(11), x, self.height / 2 - px(5), style.text,
                  alpha=0.72, shadow=self.bare)
        draw_text(cr, f"Week {day.isocalendar()[1]}", style.ui(9), x, self.height / 2 + px(14), style.text,
                  alpha=0.5, shadow=self.bare)


DESIGNS = {"month": MonthCalendar, "week": WeekCalendar, "day": DayCalendar}
