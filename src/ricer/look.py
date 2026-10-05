"""The Look: a complete, plain-data description of a desktop style.

The generator produces a Look, the engine applies one. Nothing in here touches the desktop.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

DIAL_MIN, DIAL_MAX = 1, 10
BAR_STYLES = ("cards", "solid", "stock")
DOCK_POSITIONS = ("BOTTOM", "LEFT", "RIGHT")
WIDGET_TYPES = ("clock", "media", "system")
ANCHORS = ("top-left", "top-center", "top-right", "bottom-left", "bottom-right")
SYSTEM_ROWS = ("cpu", "ram", "temp", "gpu", "battery")
_HEX = re.compile(r"^#[0-9a-f]{6}$")


class LookError(ValueError):
    """A Look (or a dial) holds a value that makes no sense."""


def dial_fraction(value: int) -> float:
    """Map a 1..10 dial to 0.0..1.0."""
    return (value - DIAL_MIN) / (DIAL_MAX - DIAL_MIN)


@dataclass(frozen=True)
class Dials:
    cool: int = 5
    ease: int = 5
    warmth: int = 5

    def validate(self) -> None:
        for name in ("cool", "ease", "warmth"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise LookError(f"{name} must be a whole number, got {value!r}")
            if not DIAL_MIN <= value <= DIAL_MAX:
                raise LookError(f"{name} must be between {DIAL_MIN} and {DIAL_MAX}, got {value}")


@dataclass(frozen=True)
class Palette:
    accent: str
    accent2: str
    text: str
    card: str
    card_alpha: float
    hot: str

    def validate(self) -> None:
        for name in ("accent", "accent2", "text", "card", "hot"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _HEX.match(value):
                raise LookError(f"palette.{name} must be a #rrggbb colour, got {value!r}")
        if not 0.0 <= self.card_alpha <= 1.0:
            raise LookError(f"palette.card_alpha must be within 0..1, got {self.card_alpha}")


@dataclass(frozen=True)
class Dock:
    position: str = "BOTTOM"
    autohide: bool = True
    floating: bool = True
    opacity: float = 0.3
    icon_size: int = 44

    def validate(self) -> None:
        if self.position not in DOCK_POSITIONS:
            raise LookError(f"dock.position must be one of {DOCK_POSITIONS}, got {self.position!r}")
        if not 0.0 <= self.opacity <= 1.0:
            raise LookError(f"dock.opacity must be within 0..1, got {self.opacity}")
        if not 16 <= self.icon_size <= 128:
            raise LookError(f"dock.icon_size must be within 16..128, got {self.icon_size}")


@dataclass(frozen=True)
class WidgetSpec:
    type: str
    anchor: str
    options: dict = field(default_factory=dict)

    def validate(self) -> None:
        if self.type not in WIDGET_TYPES:
            raise LookError(f"widget type must be one of {WIDGET_TYPES}, got {self.type!r}")
        if self.anchor not in ANCHORS:
            raise LookError(f"widget anchor must be one of {ANCHORS}, got {self.anchor!r}")
        if self.type == "system":
            rows = self.options.get("rows", [])
            unknown = [row for row in rows if row not in SYSTEM_ROWS]
            if not rows or unknown:
                raise LookError(f"system widget rows must be a non-empty subset of {SYSTEM_ROWS}")


@dataclass(frozen=True)
class Look:
    dials: Dials
    seed: int
    wallpaper: str
    palette: Palette
    gtk_accent: str
    bar_style: str
    gradient: bool
    blur: bool
    dock: Dock
    widget_scale: float
    terminal: dict
    widgets: tuple[WidgetSpec, ...] = ()

    def validate(self) -> None:
        self.dials.validate()
        self.palette.validate()
        self.dock.validate()
        if not self.wallpaper:
            raise LookError("look has no wallpaper")
        if self.bar_style not in BAR_STYLES:
            raise LookError(f"bar_style must be one of {BAR_STYLES}, got {self.bar_style!r}")
        if not 0.5 <= self.widget_scale <= 2.0:
            raise LookError(f"widget_scale must be within 0.5..2, got {self.widget_scale}")
        colours = [self.terminal.get("background"), self.terminal.get("foreground"),
                   *self.terminal.get("palette", [])]
        if len(colours) != 18 or not all(isinstance(c, str) and _HEX.match(c) for c in colours):
            raise LookError("terminal needs a background, a foreground and 16 palette colours")
        anchors = [widget.anchor for widget in self.widgets]
        if len(anchors) != len(set(anchors)):
            raise LookError("two widgets share the same anchor")
        for widget in self.widgets:
            widget.validate()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Look":
        return cls(
            dials=Dials(**data["dials"]),
            seed=data["seed"],
            wallpaper=data["wallpaper"],
            palette=Palette(**data["palette"]),
            gtk_accent=data["gtk_accent"],
            bar_style=data["bar_style"],
            gradient=data["gradient"],
            blur=data["blur"],
            dock=Dock(**data["dock"]),
            widget_scale=data["widget_scale"],
            terminal=data["terminal"],
            widgets=tuple(WidgetSpec(**widget) for widget in data["widgets"]),
        )
