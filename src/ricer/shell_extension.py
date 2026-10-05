"""Ricer's own GNOME Shell extension: installing it, and telling it what a look wants.

The extension ships inside the package. It decides nothing: it draws what `config()` writes
for it, which is the bar's clock and the cards in the menu that opens from the clock.
"""
from __future__ import annotations

from importlib import resources

from ricer.capabilities import RICER_UUID, Capabilities
from ricer.look import Look
from ricer.paths import Paths

FILES = ("metadata.json", "extension.js", "stylesheet.css")
# What each clock is in GLib's date format; "full" and "glyph" show no text of ricer's.
FORMATS = {"date": "%a %-d %b", "weekday": "%A"}
TIME_24H, TIME_12H = "%H:%M", "%-l:%M %p"


def bundled() -> dict[str, str]:
    """The extension's files as shipped: name -> content."""
    folder = resources.files("ricer").joinpath("data", "extension")
    return {name: folder.joinpath(name).read_text() for name in FILES}


def install(paths: Paths) -> bool:
    """Put the extension where GNOME Shell looks for it. True if any file was written."""
    folder, changed = paths.extensions_dir / RICER_UUID, False
    for name, content in bundled().items():
        target = folder / name
        if not target.is_file() or target.read_text() != content:
            folder.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            changed = True
    return changed


def clock_format(form: str, clock_24h: bool) -> str | None:
    if form == "time":
        return TIME_24H if clock_24h else TIME_12H
    return FORMATS.get(form)


def config(look: Look, caps: Capabilities) -> dict:
    """What the extension reads."""
    palette = look.palette
    return {
        "clock": {"form": look.bar.clock, "format": clock_format(look.bar.clock, caps.clock_24h)},
        "menu": list(look.bar.menu),
        "layout": look.bar.menu_layout,
        "time_format": clock_format("time", caps.clock_24h),
        "caps": look.style.caps,
        "palette": [palette.accent, palette.accent2, palette.text, palette.card, palette.hot],
        "seed": look.seed,
    }
