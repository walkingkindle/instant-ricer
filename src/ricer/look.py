"""The Look: a complete, plain-data description of one desktop style.

This is the contract of the whole tool. The generator writes a Look, the engine applies one,
and anything else that can produce this structure (a GUI, an AI art director) can drive the
desktop the same way. Nothing in here touches the desktop.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

DIAL_MIN, DIAL_MAX = 1, 10
DIAL_NAMES = ("cool", "ease", "warmth", "chaos")

BAR_STYLES = ("stock", "minimal", "island", "cards", "solid")
BAR_SIDES = ("left", "center", "right")
BAR_STATS = ("cpu", "ram", "temp", "net", "battery")
# what the bar shows where the clock is: "full" is GNOME's own date and time, "glyph" an icon
BAR_CLOCKS = ("full", "time", "date", "weekday", "glyph")
# cards ricer can add to the menu that opens from the clock
MENU_SECTIONS = ("clock", "profile", "system", "network", "processes", "progress", "fetch", "palette",
                 "power")
# where those cards go: beside GNOME's calendar, in the calendar's place, under the calendar
# in place of its events and world clocks, or ahead of the notifications
MENU_LAYOUTS = ("beside", "replace", "under", "first")
DOCK_POSITIONS = ("BOTTOM", "LEFT", "RIGHT")
DOCK_INDICATORS = ("DOTS", "SQUARES", "DASHES", "SEGMENTED", "SOLID", "CILIORA", "METRO")
BORDERS = ("none", "hairline", "accent")
VOICES = ("ui", "condensed", "mono", "serif", "geometric")
ICON_STYLES = ("stock", "fancy")
LAYOUTS = ("corners", "column", "stage", "scatter")
ANCHORS = ("top-left", "top-center", "top-right", "left", "center", "right",
           "bottom-left", "bottom-center", "bottom-right")
# every desktop widget type and the designs it can be drawn in
DESIGNS = {
    "clock": ("digital", "stacked", "analog", "words"),
    "greeting": ("plain",),
    "calendar": ("month", "week", "day"),
    "media": ("card", "pill", "cover"),
    "system": ("bars", "rings", "line"),
    "progress": ("bars",),
    "ornament": ("orbits", "sigil", "skyline"),
}
WIDGET_TYPES = tuple(DESIGNS)
SYSTEM_ROWS = ("cpu", "ram", "temp", "gpu", "battery")
PROGRESS_ROWS = ("day", "week", "month", "year")
KEEP_PARTS = ("wallpaper", "style", "widgets", "layout", "bar", "dock")
_HEX = re.compile(r"^#[0-9a-f]{6}$")


class LookError(ValueError):
    """A Look (or a dial) holds a value that makes no sense."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LookError(message)


def _one_of(name: str, value, allowed) -> None:
    _require(value in allowed, f"{name} must be one of {tuple(allowed)}, got {value!r}")


def _within(name: str, value, low: float, high: float) -> None:
    _require(isinstance(value, (int, float)) and not isinstance(value, bool)
             and low <= value <= high, f"{name} must be within {low}..{high}, got {value!r}")


def dial_fraction(value: int) -> float:
    """Map a 1..10 dial to 0.0..1.0."""
    return (value - DIAL_MIN) / (DIAL_MAX - DIAL_MIN)


@dataclass(frozen=True)
class Dials:
    cool: int = 5                    # flashiness: calm and minimal .. loud and flashy
    ease: int = 5                    # practicality: looks first .. usability first
    warmth: int = 5                  # mood: cold blues .. warm ambers
    chaos: int = 5                   # how far a run may stray from what the others suggest

    def validate(self) -> None:
        for name in DIAL_NAMES:
            value = getattr(self, name)
            _require(isinstance(value, int) and not isinstance(value, bool),
                     f"{name} must be a whole number, got {value!r}")
            _require(DIAL_MIN <= value <= DIAL_MAX,
                     f"{name} must be between {DIAL_MIN} and {DIAL_MAX}, got {value}")


@dataclass(frozen=True)
class Palette:
    accent: str
    accent2: str
    text: str
    card: str
    hot: str

    def validate(self) -> None:
        for name in ("accent", "accent2", "text", "card", "hot"):
            value = getattr(self, name)
            _require(isinstance(value, str) and bool(_HEX.match(value)),
                     f"palette.{name} must be a #rrggbb colour, got {value!r}")


@dataclass(frozen=True)
class Style:
    """Traits shared by every part of a look, so the desktop matches itself."""
    radius: int = 16                 # px: corners of cards, bar pieces and menus
    fill: float = 0.58               # opacity of the card behind widgets; 0 means no card
    border: str = "hairline"
    weight: float = 0.3              # display text: 0 thin .. 1 heavy
    voice: str = "ui"                # typeface role for display text
    caps: bool = True                # small labels in spaced capitals
    gradient: bool = True            # accents run from accent to accent2
    scale: float = 1.0               # size multiplier for text and widgets

    def validate(self) -> None:
        _within("style.radius", self.radius, 0, 40)
        _within("style.fill", self.fill, 0.0, 1.0)
        _one_of("style.border", self.border, BORDERS)
        _within("style.weight", self.weight, 0.0, 1.0)
        _one_of("style.voice", self.voice, VOICES)
        _within("style.scale", self.scale, 0.5, 2.0)


@dataclass(frozen=True)
class Bar:
    style: str = "cards"
    stats: tuple[str, ...] = ()      # sensors shown in the bar; empty means none
    stats_side: str = "right"
    media: bool = False              # now playing, with controls, in the bar
    media_side: str = "left"
    clock: str = "full"              # what stands where the clock is
    menu: tuple[str, ...] = ()       # cards added to the menu that opens from the clock
    menu_layout: str = "beside"      # where they go, and what of GNOME's they displace

    def validate(self) -> None:
        _one_of("bar.style", self.style, BAR_STYLES)
        _one_of("bar.clock", self.clock, BAR_CLOCKS)
        _one_of("bar.menu_layout", self.menu_layout, MENU_LAYOUTS)
        _require(all(s in MENU_SECTIONS for s in self.menu) and len(set(self.menu)) == len(self.menu),
                 f"bar.menu must be distinct members of {MENU_SECTIONS}, got {self.menu!r}")
        _require(all(s in BAR_STATS for s in self.stats) and len(set(self.stats)) == len(self.stats),
                 f"bar.stats must be distinct members of {BAR_STATS}, got {self.stats!r}")
        _one_of("bar.stats_side", self.stats_side, BAR_SIDES)
        _one_of("bar.media_side", self.media_side, BAR_SIDES)


@dataclass(frozen=True)
class Dock:
    position: str = "BOTTOM"
    autohide: bool = True
    floating: bool = True
    opacity: float = 0.3
    icon_size: int = 44
    indicator: str = "DOTS"
    tint: bool = False               # colour the dock like the cards

    def validate(self) -> None:
        _one_of("dock.position", self.position, DOCK_POSITIONS)
        _within("dock.opacity", self.opacity, 0.0, 1.0)
        _within("dock.icon_size", self.icon_size, 16, 128)
        _one_of("dock.indicator", self.indicator, DOCK_INDICATORS)


@dataclass(frozen=True)
class WidgetSpec:
    type: str
    design: str
    anchor: str
    options: dict = field(default_factory=dict)

    def validate(self) -> None:
        _one_of("widget type", self.type, WIDGET_TYPES)
        _one_of(f"{self.type} design", self.design, DESIGNS[self.type])
        _one_of("widget anchor", self.anchor, ANCHORS)
        rows, allowed = self.options.get("rows"), None
        if self.type == "system":
            allowed = SYSTEM_ROWS
        elif self.type == "progress":
            allowed = PROGRESS_ROWS
        if allowed:
            _require(bool(rows) and all(row in allowed for row in rows),
                     f"{self.type} widget rows must be a non-empty subset of {allowed}")


@dataclass(frozen=True)
class Look:
    dials: Dials
    seed: int
    wallpaper: str
    palette: Palette
    style: Style
    gtk_accent: str
    icon_style: str
    desktop_icons: bool
    bar: Bar
    blur: bool
    dock: Dock
    terminal: dict
    layout: str                      # the template the placement was biased by
    mirrored: bool                   # template flipped left to right
    widgets: tuple[WidgetSpec, ...] = ()

    def validate(self) -> None:
        self.dials.validate()
        self.palette.validate()
        self.style.validate()
        self.bar.validate()
        self.dock.validate()
        _require(bool(self.wallpaper), "look has no wallpaper")
        _one_of("icon_style", self.icon_style, ICON_STYLES)
        _one_of("layout", self.layout, LAYOUTS)
        colours = [self.terminal.get("background"), self.terminal.get("foreground"),
                   *self.terminal.get("palette", [])]
        _require(len(colours) == 18 and all(isinstance(c, str) and _HEX.match(c) for c in colours),
                 "terminal needs a background, a foreground and 16 palette colours")
        if "transparency" in self.terminal:                  # percent; looks from 0.2 have none
            _within("terminal.transparency", self.terminal["transparency"], 0, 50)
        for widget in self.widgets:
            widget.validate()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Look":
        """Rebuild a Look from `to_dict()` output. Raises LookError for other shapes."""
        try:
            bar = dict(data["bar"])
            bar["stats"] = tuple(bar.get("stats", ()))
            bar["menu"] = tuple(bar.get("menu", ()))         # looks from before 0.5 have none
            return cls(
                dials=Dials(**data["dials"]),
                seed=data["seed"],
                wallpaper=data["wallpaper"],
                palette=Palette(**data["palette"]),
                style=Style(**data["style"]),
                gtk_accent=data["gtk_accent"],
                icon_style=data["icon_style"],
                desktop_icons=data["desktop_icons"],
                bar=Bar(**bar),
                blur=data["blur"],
                dock=Dock(**data["dock"]),
                terminal=data["terminal"],
                layout=data["layout"],
                mirrored=data["mirrored"],
                widgets=tuple(WidgetSpec(**widget) for widget in data["widgets"]),
            )
        except (KeyError, TypeError) as error:
            raise LookError(f"not a look this version understands: {error}") from error
