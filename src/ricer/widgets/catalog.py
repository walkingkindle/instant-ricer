"""Every widget type and design the daemon can draw."""
from __future__ import annotations

from ricer.widgets import calendars, clock, greeting, media, ornament, progress, system
from ricer.widgets.style import Style

CATALOG = {
    "clock": clock.DESIGNS,
    "greeting": greeting.DESIGNS,
    "calendar": calendars.DESIGNS,
    "media": media.DESIGNS,
    "system": system.DESIGNS,
    "progress": progress.DESIGNS,
    "ornament": ornament.DESIGNS,
}


def build(style: Style, spec: dict):
    """The widget object for one entry of widgets.json."""
    return CATALOG[spec["type"]][spec["design"]](style, spec.get("options", {}))
