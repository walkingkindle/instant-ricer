"""How a look's style reaches the widgets: colours, fonts, scale. No GTK in here."""
from __future__ import annotations

from dataclasses import dataclass

from ricer.palette import hex_to_rgb

# style.weight 0..1 mapped onto Pango weight names; "" is regular
WEIGHTS = ((0.15, "Thin"), (0.35, "Light"), (0.55, ""), (0.72, "Medium"), (0.88, "Semi-Bold"),
           (2.0, "Bold"))


@dataclass(frozen=True)
class Style:
    accent: tuple
    accent2: tuple
    text: tuple
    hot: tuple
    card: tuple                      # r, g, b
    fill: float = 0.58               # the look's card opacity; each widget may override it
    border: str = "hairline"
    radius: float = 16
    weight: float = 0.3
    font: str = "Sans"               # family for small text
    display: str = "Sans"            # family for big display text
    caps: bool = True
    gradient: bool = True
    scale: float = 1.0
    clock_24h: bool = True

    @classmethod
    def from_config(cls, config: dict) -> "Style":
        palette, style = config["palette"], config["style"]
        return cls(
            accent=hex_to_rgb(palette["accent"]),
            accent2=hex_to_rgb(palette["accent2"]),
            text=hex_to_rgb(palette["text"]),
            hot=hex_to_rgb(palette["hot"]),
            card=hex_to_rgb(palette["card"]),
            fill=style["fill"],
            border=style["border"],
            radius=style["radius"],
            weight=style["weight"],
            font=config.get("font", "Sans"),
            display=config.get("display_font") or config.get("font", "Sans"),
            caps=style["caps"],
            gradient=style["gradient"],
            scale=style["scale"],
            clock_24h=config.get("clock_24h", True),
        )

    def px(self, value: float) -> float:
        """Scale a length or font size by the look's scale."""
        return value * self.scale

    def weight_name(self, shift: float = 0.0) -> str:
        """Pango weight word for the look's weight, optionally nudged lighter or heavier."""
        level = self.weight + shift
        return next(name for limit, name in WEIGHTS if level < limit)

    def ui(self, size: float, weight: str = "") -> str:
        """Font string for small text, scaled: 'Ubuntu Sans Medium 14.3'."""
        return " ".join(part for part in (self.font, weight, f"{self.px(size):g}") if part)

    def show(self, size: float, shift: float = 0.0) -> str:
        """Font string for display text at an absolute size, in the look's typeface and weight."""
        return " ".join(part for part in (self.display, self.weight_name(shift), f"{size:g}") if part)

    def label(self, text: str) -> str:
        return text.upper() if self.caps else text

    @property
    def label_spacing(self) -> float:
        return self.px(2) if self.caps else 0
