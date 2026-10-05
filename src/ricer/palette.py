"""Colour maths: pulling colours out of a wallpaper and tuning them to the dials.

Colours are '#rrggbb' strings at the edges and (r, g, b) floats in 0..1 inside.
"""
from __future__ import annotations

import colorsys
import math
import random

from ricer.chance import pick
from ricer.look import DIAL_MIN, Dials, Palette, dial_fraction

COLD_HUE = 210.0                     # degrees: where warmth=1 lands when the wallpaper is grey
HUE_SPAN = 180.0                     # warmth=10 lands at COLD_HUE + HUE_SPAN (amber, 30 degrees)
WARM_HUE = (COLD_HUE + HUE_SPAN) % 360
ACCENT_LIGHTNESS = 0.70
TEXT = "#f2f7ff"
HOT = "#ff6b6b"

# Yaru accent variants and the hue each one sits at. "default" is Ubuntu orange.
YARU_ACCENT_HUES = {
    "default": 16, "olive": 86, "viridian": 160, "prussiangreen": 178,
    "blue": 210, "purple": 250, "magenta": 300, "red": 350,
}
# GNOME 47+ has its own accent-color setting with a different vocabulary.
GNOME_ACCENT_NAMES = {
    "default": "orange", "olive": "green", "viridian": "green", "prussiangreen": "teal",
    "blue": "blue", "purple": "purple", "magenta": "pink", "red": "red",
}


def hex_to_rgb(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))


def rgb_to_hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(round(max(0.0, min(1.0, c)) * 255) for c in rgb)


def hsl(hue: float, saturation: float, lightness: float) -> str:
    """Build a colour from a hue in degrees plus saturation and lightness in 0..1."""
    return rgb_to_hex(colorsys.hls_to_rgb((hue % 360) / 360, lightness, saturation))


def hue_of(value: str) -> float:
    return colorsys.rgb_to_hls(*hex_to_rgb(value))[0] * 360


def lightness_of(value: str) -> float:
    return colorsys.rgb_to_hls(*hex_to_rgb(value))[1]


def saturation_of(value: str) -> float:
    return colorsys.rgb_to_hls(*hex_to_rgb(value))[2]


def hue_warmth(hue: float) -> float:
    """+1 for amber (30 degrees), -1 for the opposite blue (210 degrees)."""
    return math.cos(math.radians(hue - WARM_HUE))


def hue_distance(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def shift_hue_toward(hue: float, target: float, amount: float) -> float:
    """Move `hue` a fraction `amount` of the way to `target` along the shorter arc."""
    delta = (target - hue + 180) % 360 - 180
    return (hue + delta * amount) % 360


def dial_hue(warmth: int) -> float:
    """Hue the warmth dial asks for: blue at 1, through violet and pink, amber at 10."""
    return (COLD_HUE + HUE_SPAN * dial_fraction(warmth)) % 360


def accent_saturation(cool: int) -> float:
    return 0.35 + 0.60 * dial_fraction(cool)


def relative_luminance(value: str) -> float:
    def channel(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in hex_to_rgb(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    la, lb = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def extract_colors(image, count: int = 8) -> list[tuple[str, float]]:
    """Dominant colours of a PIL image as (hex, share of pixels), biggest share first."""
    small = image.convert("RGB").resize((64, 64))
    quantized = small.quantize(colors=count)
    raw = quantized.getpalette()
    total = 64 * 64
    found = [
        (rgb_to_hex([c / 255 for c in raw[index * 3:index * 3 + 3]]), n / total)
        for n, index in quantized.getcolors()
    ]
    return sorted(found, key=lambda item: (-item[1], item[0]))


def _fit(color: str, weight: float, warm_bias: float) -> float:
    """How good an accent a wallpaper colour makes: common, saturated, and on-mood."""
    return math.sqrt(weight) * saturation_of(color) * (1 + 0.8 * warm_bias * hue_warmth(hue_of(color)))


def build_palette(colors: list[tuple[str, float]], dials: Dials,
                  rng: random.Random | None = None) -> Palette:
    """Derive the UI palette from a wallpaper's dominant colours and the dials.

    Without `rng` this is the single best palette for the inputs. With it, the accents are
    drawn from the wallpaper's good candidates with chaos-tempered odds.
    """
    warm_bias = 2 * dial_fraction(dials.warmth) - 1          # -1 cold .. +1 warm
    vivid = [(c, w) for c, w in colors
             if saturation_of(c) >= 0.18 and 0.12 <= lightness_of(c) <= 0.90]
    ranked = sorted(vivid, key=lambda item: (-_fit(item[0], item[1], warm_bias), item[0]))
    fits = {color: _fit(color, weight, warm_bias) for color, weight in ranked}
    steps = dials.chaos - DIAL_MIN

    if ranked:
        chosen = ranked[0][0] if rng is None else pick(
            rng, {color: fits[color] for color, _ in ranked[:4]}, dials.chaos)
        # lean the wallpaper's own colour toward the mood the dial asks for
        accent_hue = shift_hue_toward(hue_of(chosen), dial_hue(dials.warmth), 0.25 * abs(warm_bias))
    else:
        accent_hue = dial_hue(dials.warmth)
        if rng is not None:
            accent_hue = (accent_hue + rng.gauss(0, 3 + 2.5 * steps)) % 360

    others = [c for c, _ in ranked if hue_distance(hue_of(c), accent_hue) >= 35]
    if others:
        second = others[0] if rng is None else pick(
            rng, {color: fits[color] for color in others[:3]}, dials.chaos)
        accent2_hue = hue_of(second)
    else:
        # amber pairs with pink, blue pairs with violet
        accent2_hue = accent_hue + (-55 if hue_warmth(accent_hue) > 0 else 55)

    saturation = accent_saturation(dials.cool)
    card_saturation, card_lightness = 0.35, 0.08
    if rng is not None:
        saturation = max(0.25, min(0.98, rng.gauss(saturation, 0.02 + 0.006 * steps)))
        card_saturation, card_lightness = rng.uniform(0.22, 0.45), rng.uniform(0.065, 0.105)
    card_hue = hue_of(colors[0][0]) if colors else accent_hue
    return Palette(
        accent=hsl(accent_hue, saturation, ACCENT_LIGHTNESS),
        accent2=hsl(accent2_hue, saturation, ACCENT_LIGHTNESS + 0.02),
        text=TEXT,
        card=hsl(card_hue, card_saturation, card_lightness),
        hot=HOT,
    )


def terminal_colors(palette: Palette) -> dict:
    """A 16-colour terminal scheme that sits on the card colour and shares the accent's punch."""
    base_hue = hue_of(palette.card)
    saturation = max(0.45, saturation_of(palette.accent) * 0.85)
    hues = (0, 110, 45, 220, 290, 185)                       # red green yellow blue magenta cyan
    normal = [hsl(h, saturation, 0.68) for h in hues]
    bright = [hsl(h, saturation, 0.76) for h in hues]
    return {
        "background": hsl(base_hue, 0.25, 0.11),
        "foreground": hsl(base_hue, 0.35, 0.86),
        "palette": [hsl(base_hue, 0.25, 0.09), *normal, hsl(base_hue, 0.20, 0.72),
                    hsl(base_hue, 0.20, 0.34), *bright, hsl(base_hue, 0.35, 0.90)],
    }


def nearest_gtk_accent(color: str) -> str:
    """Name of the Yaru accent variant closest in hue to `color`."""
    hue = hue_of(color)
    return min(YARU_ACCENT_HUES, key=lambda name: (hue_distance(hue, YARU_ACCENT_HUES[name]), name))
