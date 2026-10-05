"""Progress widget: how far through the day, week, month and year it is."""
from __future__ import annotations

import calendar as months
import datetime
import math

from ricer import metrics
from ricer.widgets.drawing import Widget, draw_rows
from ricer.widgets.style import Style

LABELS = {"day": "Day", "week": "Week", "month": "Month", "year": "Year"}


def progress(row: str, now: datetime.datetime) -> float:
    """Fraction of the current day, week, month or year that has passed."""
    day = (now.hour * 3600 + now.minute * 60 + now.second) / 86400
    if row == "day":
        return day
    if row == "week":
        return (now.weekday() + day) / 7
    if row == "month":
        return (now.day - 1 + day) / months.monthrange(now.year, now.month)[1]
    days = 366 if months.isleap(now.year) else 365
    return (now.timetuple().tm_yday - 1 + day) / days


class Progress(Widget):
    def __init__(self, style: Style, options: dict, now=datetime.datetime.now):
        super().__init__(style, options)
        self.now = now
        self.rows = list(options.get("rows", ("day", "year")))
        width, height = metrics.rows_card(len(self.rows), options.get("width"))
        self.width, self.height = math.ceil(style.px(width)), math.ceil(style.px(height))

    def tick(self, count: int) -> bool:
        return count % 30 == 0                               # the bars move slowly

    def draw(self, cr) -> None:
        now = self.now()
        self.draw_card(cr)
        rows = [(LABELS[row], progress(row, now), f"{math.floor(progress(row, now) * 100)}%", False)
                for row in self.rows]
        draw_rows(cr, self.style, rows, self.width, self.bare)


DESIGNS = {"bars": Progress}
