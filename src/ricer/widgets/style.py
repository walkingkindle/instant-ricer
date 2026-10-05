"""Colours, fonts and scale shared by every widget. No GTK in here."""
from __future__ import annotations

from dataclasses import dataclass

from ricer.palette import hex_to_rgb


@dataclass(frozen=True)
class Style:
    accent: tuple
    accent2: tuple
    text: tuple
    hot: tuple
    card: tuple                      # r, g, b, a
    scale: float = 1.0
    gradient: bool = True
    font: str = "Sans"
    clock_24h: bool = True

    @classmethod
    def from_config(cls, config: dict) -> "Style":
        palette = config["palette"]
        return cls(
            accent=hex_to_rgb(palette["accent"]),
            accent2=hex_to_rgb(palette["accent2"]),
            text=hex_to_rgb(palette["text"]),
            hot=hex_to_rgb(palette["hot"]),
            card=(*hex_to_rgb(palette["card"]), palette["card_alpha"]),
            scale=config.get("scale", 1.0),
            gradient=config.get("gradient", True),
            font=config.get("font", "Sans"),
            clock_24h=config.get("clock_24h", True),
        )

    def px(self, value: float) -> float:
        """Scale a length or font size."""
        return value * self.scale

    def font_desc(self, size: float, weight: str = "") -> str:
        """Pango font string for a scaled size, e.g. 'Ubuntu Sans Medium 14.3'."""
        return " ".join(part for part in (self.font, weight, f"{self.px(size):g}") if part)
