"""Generate a Look. Every stage draws from odds that the dials tilt.

Pure: the same dials, seed, wallpaper library and screen always give the same Look. Each
stage has its own random stream, so one stage can be pinned (--keep) without disturbing the
rest.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from ricer import metrics, placement
from ricer.chance import bump, chance, jitter, noisy_dial, pick, stream
from ricer.look import (DIAL_MIN, WIDGET_TYPES, Bar, Dials, Dock, Look, Palette, Style, WidgetSpec,
                        dial_fraction)
from ricer.palette import build_palette, nearest_gtk_accent, terminal_colors, terminal_transparency
from ricer.placement import Box
from ricer.wallpapers import Wallpaper, choose

SCREEN = (1920, 1080)
MAX_WIDGETS = 6
COLUMN_WIDTH = (280, 340)            # px before scaling: the range a stack of cards may share
PLACEMENT_KEYS = ("fill", "width", "align")              # options that placement decides


@dataclass(frozen=True)
class Kept:
    """Parts of an earlier look to carry over unchanged."""
    wallpaper: str | None = None
    style: tuple[Style, Palette] | None = None
    widgets: tuple[WidgetSpec, ...] | None = None
    layout: tuple[str, bool] | None = None
    bar: Bar | None = None
    dock: Dock | None = None


def kept_from(look: Look, parts) -> Kept:
    parts = set(parts)
    return Kept(
        wallpaper=look.wallpaper if "wallpaper" in parts else None,
        style=(look.style, look.palette) if "style" in parts else None,
        widgets=look.widgets if "widgets" in parts else None,
        layout=(look.layout, look.mirrored) if "layout" in parts else None,
        bar=look.bar if "bar" in parts else None,
        dock=look.dock if "dock" in parts else None,
    )


def _fractions(dials: Dials) -> tuple[float, float, float]:
    return dial_fraction(dials.cool), dial_fraction(dials.ease), dial_fraction(dials.warmth)


# -- stages ---------------------------------------------------------------------------------

def style_for(dials: Dials, rng) -> Style:
    cool, ease, warm = _fractions(dials)
    chaos = dials.chaos
    bare = chance(rng, 0.45 * (1 - ease) ** 1.5)             # looks-first desktops often go cardless
    return Style(
        radius=round(40 * jitter(rng, (4 + 2 * dials.warmth) / 40, chaos, scale=0.5)),
        fill=0.0 if bare else round(jitter(rng, 0.30 + 0.45 * ease, chaos, 0.25, 0.92, scale=0.6), 2),
        border=pick(rng, {"none": 0.5 + 0.5 * warm, "hairline": 1.0,
                          "accent": 0.3 + 1.2 * (1 - warm) + 0.3 * cool}, chaos),
        weight=round(jitter(rng, 0.25 + 0.4 * ease, chaos, scale=1.2), 2),
        voice=pick(rng, {"ui": 1.0,
                         "condensed": 0.25 + 0.6 * (1 - warm) + 0.3 * cool,
                         "mono": 0.15 + 0.9 * (1 - warm),
                         "serif": 0.15 + 0.9 * warm,
                         "geometric": 0.4 + 0.2 * cool}, chaos),
        caps=chance(rng, 0.35 + 0.3 * (1 - warm)),
        gradient=chance(rng, 0.1 + 0.9 * cool),
        scale=round(jitter(rng, 1.0 + 0.25 * ease, chaos, 0.9, 1.35, scale=0.25), 2),
    )


def bar_for(dials: Dials, rng) -> Bar:
    cool, ease, _ = _fractions(dials)
    chaos = dials.chaos
    style = pick(rng, {
        "stock": max(0.0, 0.9 - 3 * cool),
        "minimal": (0.1 + bump(cool, 0.3, 0.35)) * (0.3 if dials.ease >= 8 else 1.0),
        "island": 0.15 + bump(cool, 0.55, 0.4),
        "cards": 0.1 + bump(cool, 0.9, 0.45),
        "solid": 0.05 + 2.5 * max(0.0, ease - 0.6),
    }, chaos)

    stats: tuple[str, ...] = ()
    reading = noisy_dial(rng, dials.ease, chaos)
    if reading >= 4.5:
        stats = ("cpu", "ram", "temp")
        if reading >= 7.5:
            stats += ("net",)
        if reading >= 9:
            stats += ("battery",)
    stats_side = pick(rng, {"right": 0.6, "left": 0.4}, chaos)
    media = noisy_dial(rng, dials.ease, chaos) >= 6.5
    # the two groups read better on different sides of the bar
    media_side = pick(rng, {side: weight * (0.25 if side == stats_side and stats else 1.0)
                            for side, weight in (("left", 0.45), ("center", 0.2), ("right", 0.35))}, chaos)
    return Bar(style=style, stats=stats, stats_side=stats_side, media=media, media_side=media_side)


def dock_for(dials: Dials, rng) -> Dock:
    cool, ease, _ = _fractions(dials)
    chaos = dials.chaos
    floating = pick(rng, {True: 1.0 if dials.ease <= 7 else 0.25,
                          False: 0.15 + (1.0 if dials.ease >= 8 else 0.0)}, chaos)
    return Dock(
        position=pick(rng, {"BOTTOM": 1.0, "LEFT": 0.12 + 0.25 * ease, "RIGHT": 0.06}, chaos),
        autohide=dials.ease <= 6,                            # a promise, not a chance: ease 7+ never hides
        floating=floating,
        opacity=round(jitter(rng, 0.15 + 0.75 * ease, chaos, 0.1, 0.95, scale=0.3), 2),
        icon_size=max(32, min(64, 40 + 2 * round(8 * ease) + 2 * round(rng.gauss(0, 0.2 + 0.1 * chaos)))),
        indicator=pick(rng, {"DOTS": 1.0 - 0.6 * cool, "DASHES": 0.6, "SQUARES": 0.3,
                             "SEGMENTED": 0.2 + 0.6 * cool, "METRO": 0.1 + 0.5 * cool,
                             "CILIORA": 0.1 + 0.4 * cool, "SOLID": 0.15}, chaos),
        tint=chance(rng, 0.3 + 0.6 * cool),
    )


def widget_budget(dials: Dials, rng) -> int:
    """How many desktop widgets: about cool minus two, with chaos-sized wobble."""
    expected = max(0, min(MAX_WIDGETS, dials.cool - 2))
    count = round(rng.gauss(expected, 0.25 + 0.09 * (dials.chaos - DIAL_MIN)))
    if dials.cool <= 2:
        count = min(count, 1)                                # the calm end stays nearly empty
    return max(0, min(len(WIDGET_TYPES), count))


def _design(kind: str, dials: Dials, rng) -> str:
    cool, ease, warm = _fractions(dials)
    odds = {
        "clock": {"digital": 1.0 + 0.6 * (1 - warm), "stacked": 0.3 + 1.2 * max(0.0, cool - 0.4),
                  "analog": 0.3 + 1.0 * warm, "words": 0.35 + 0.3 * warm + 0.2 * cool},
        "greeting": {"plain": 1.0},
        "calendar": {"month": 0.4 + 1.2 * ease, "week": 0.8, "day": 0.6 + 0.6 * cool},
        "media": {"card": 0.5 + 0.9 * ease, "pill": 0.9 - 0.5 * ease,
                  "cover": 0.2 + 1.1 * max(0.0, cool - 0.4)},
        "system": {"bars": 0.5 + 0.8 * ease, "rings": 0.3 + 1.1 * cool, "line": 0.9 - 0.6 * ease},
        "progress": {"bars": 1.0},
        "ornament": {"orbits": 1.0, "sigil": 1.0, "skyline": 1.0},
    }[kind]
    return pick(rng, odds, dials.chaos)


def _options(kind: str, design: str, dials: Dials, chosen: set[str], seed: int, rng) -> dict:
    cool, ease, _ = _fractions(dials)
    chaos = dials.chaos
    if kind == "clock":
        return {
            "size": max(48, min(150, round(rng.gauss(60 + 80 * cool, 4 + 1.5 * chaos)))),
            "seconds": chance(rng, 0.3 + 0.6 * cool),
            # the greeting already carries the date
            "date": "greeting" not in chosen and chance(rng, 0.85),
        }
    if kind == "greeting":
        return {"size": max(18, min(34, round(rng.gauss(20 + 10 * cool, 1 + 0.2 * chaos))))}
    if kind == "system":
        rows = ["cpu", "ram", "temp"]
        reading = noisy_dial(rng, dials.ease, chaos)
        if reading >= 6.5:
            rows.append("gpu")
        if reading >= 8.5:
            rows.append("battery")
        return {"rows": rows}
    if kind == "progress":
        count = 2 + round(2 * ease)
        return {"rows": {2: ["day", "year"], 3: ["day", "month", "year"]}.get(
            count, ["day", "week", "month", "year"])}
    if kind == "ornament":
        return {"size": max(120, min(320, round(rng.gauss(140 + 140 * cool, 10 + 4 * chaos)))),
                "seed": seed}
    return {}


def widget_set(dials: Dials, bar: Bar, seed: int, rng) -> list[WidgetSpec]:
    """Which widgets, in which designs. Zones are decided later, by placement."""
    cool, ease, warm = _fractions(dials)
    weights = {
        "clock": 3.0,
        "greeting": 0.5 + 0.9 * warm + 0.3 * cool,
        "calendar": 0.8 + 0.4 * ease,
        # what the bar already shows is less needed on the desktop
        "media": (1.2 + 0.5 * cool) * (0.6 if bar.media else 1.0),
        "system": (1.0 + 0.8 * (1 - warm)) * (0.5 if bar.stats else 1.0),
        "progress": 0.5 + 0.3 * (1 - warm),
        "ornament": 0.1 + 1.2 * max(0.0, cool - 0.5),
    }
    chosen: set[str] = set()
    for _ in range(widget_budget(dials, rng)):
        chosen.add(pick(rng, {kind: weight for kind, weight in weights.items()
                              if kind not in chosen}, dials.chaos))
    specs = []
    for kind in WIDGET_TYPES:                                # a stable order, also the stacking order
        if kind in chosen:
            design = _design(kind, dials, rng)
            specs.append(WidgetSpec(kind, design, "center",
                                    _options(kind, design, dials, chosen, seed, rng)))
    return specs


def layout_for(dials: Dials, rng) -> tuple[str, bool]:
    cool, ease, _ = _fractions(dials)
    template = pick(rng, {
        "corners": 1.0,
        "column": 0.2 + 1.3 * max(0.0, ease - 0.5),
        "stage": 0.2 + 1.0 * max(0.0, cool - 0.5),
        "scatter": 0.12 + 0.05 * (dials.chaos - DIAL_MIN),
    }, dials.chaos)
    return template, chance(rng, 0.5)


def card_fill(spec: WidgetSpec, style: Style, stats: tuple[float, float, float]) -> float:
    """Opacity of the card behind one widget, given the wallpaper underneath it."""
    framed = spec.type in metrics.STRUCTURED
    if framed and not (spec.type == "system" and spec.design == "line"):
        if style.fill > 0:
            return max(style.fill, 0.6) if placement.needs_card(stats) else style.fill
        return 0.0 if placement.is_calm(stats) else 0.55     # a cardless look still has to be readable
    if spec.type == "system":                                # the one-line readout: small text
        if style.fill > 0:
            return style.fill
        return 0.5 if placement.needs_card(stats) else 0.0
    if spec.type == "clock" and spec.design == "digital" and spec.options.get("size", 100) <= 76:
        return style.fill                                    # a small clock sits in a card like the rest
    if spec.type == "greeting":                              # two lines of modest text
        return max(style.fill, 0.55) if placement.needs_card(stats) else 0.0
    if spec.type == "clock" and spec.design == "analog":
        # thin hands and marks are the first thing to get lost: only over a calm, dark
        # patch of wallpaper does the dial go without a face
        return 0.0 if placement.is_calm(stats) else max(style.fill, 0.5)
    return 0.45 if stats[1] > 0.68 else 0.0                  # big text needs help only on near-white


def _boxes(specs: list[WidgetSpec], scale: float) -> list[Box]:
    return [Box(spec.type, *metrics.nominal(spec.type, spec.design, spec.options, scale))
            for spec in specs]


def _match_widths(specs: list[WidgetSpec], style: Style, screen, insets) -> list[WidgetSpec]:
    """Give card widgets stacked in one zone a common width, where that still fits."""
    groups: dict[str, list[int]] = {}
    for index, spec in enumerate(specs):
        if (spec.type, spec.design) in metrics.WIDTH_AWARE:
            groups.setdefault(spec.anchor, []).append(index)
    for members in groups.values():
        if len(members) < 2:
            continue
        widest = max(metrics.nominal(specs[i].type, specs[i].design, specs[i].options, 1.0)[0]
                     for i in members)
        # not simply the widest: one wide card would blow a small calendar up to match it
        width = max(COLUMN_WIDTH[0], min(COLUMN_WIDTH[1], widest))
        trial = list(specs)
        for i in members:
            trial[i] = replace(specs[i], options={**specs[i].options, "width": width})
        boxes = _boxes(trial, style.scale)
        anchors = {i: spec.anchor for i, spec in enumerate(trial)}
        area = placement.planning_area(screen)
        if placement.fits(placement.rectangles(boxes, anchors, area, insets), area, insets):
            specs = trial
    return specs


def place(specs: list[WidgetSpec], style: Style, wallpaper: Wallpaper, dock: Dock, dials: Dials,
          template: str, mirrored: bool, rng, screen, fixed_zones: bool = False) -> tuple[WidgetSpec, ...]:
    """Give every widget its zone, alignment, width and card. Widgets that fit nowhere are dropped."""
    specs = [replace(spec, options={k: v for k, v in spec.options.items() if k not in PLACEMENT_KEYS})
             for spec in specs]
    insets = placement.dock_insets(dock)
    if not fixed_zones:
        anchors = placement.assign(_boxes(specs, style.scale), wallpaper, screen, template, mirrored,
                                   placement.dock_forbidden(dock), insets, rng, dials.chaos)
        specs = [replace(spec, anchor=anchors[i]) for i, spec in enumerate(specs) if anchors.get(i)]
    specs = _match_widths(specs, style, screen, insets)

    boxes = _boxes(specs, style.scale)
    rects = placement.rectangles(boxes, {i: spec.anchor for i, spec in enumerate(specs)},
                             placement.planning_area(screen), insets)
    fills = [card_fill(spec, style, placement.region(wallpaper, screen, rects[index]))
             for index, spec in enumerate(specs)]
    framed = [i for i, spec in enumerate(specs) if spec.type in metrics.STRUCTURED]
    if style.fill == 0 and any(fills[i] > 0 for i in framed):
        # in a cardless look, one framed widget needing a card means they all get one:
        # a desktop where only some widgets have cards looks like a mistake
        for i in framed:
            fills[i] = 0.55
    return tuple(replace(spec, options={**spec.options, "align": placement.side(spec.anchor),
                                        "fill": round(fills[index], 2)})
                 for index, spec in enumerate(specs))


# -- the whole look -------------------------------------------------------------------------

def wallpaper_for(dials: Dials, wallpapers: list[Wallpaper], seed: int) -> Wallpaper:
    """The wallpaper a seed leads to. Cheap, so many seeds can be scanned for a fresh one."""
    return choose(wallpapers, dials, stream(seed, "wallpaper"))


def generate(dials: Dials, wallpapers: list[Wallpaper], seed: int, screen: tuple[int, int] = SCREEN,
             keep: Kept = Kept()) -> Look:
    """Build the Look for these dials and this seed."""
    dials.validate()
    by_path = {wallpaper.path: wallpaper for wallpaper in wallpapers}
    wallpaper = by_path.get(keep.wallpaper) or wallpaper_for(dials, wallpapers, seed)

    if keep.style:
        style, palette = keep.style
    else:
        style = style_for(dials, stream(seed, "style"))
        palette = build_palette(list(wallpaper.colors), dials, stream(seed, "palette"))
    bar = keep.bar or bar_for(dials, stream(seed, "bar"))
    dock = keep.dock or dock_for(dials, stream(seed, "dock"))

    specs = list(keep.widgets) if keep.widgets is not None else widget_set(
        dials, bar, seed, stream(seed, "widgets"))
    template, mirrored = keep.layout or layout_for(dials, stream(seed, "layout"))
    widgets = place(specs, style, wallpaper, dock, dials, template, mirrored,
                    stream(seed, "placement"), screen,
                    fixed_zones=keep.layout is not None and keep.widgets is not None)

    extras = stream(seed, "extras")
    look = Look(
        dials=dials,
        seed=seed,
        wallpaper=wallpaper.path,
        palette=palette,
        style=style,
        gtk_accent=nearest_gtk_accent(palette.accent),
        icon_style="fancy" if noisy_dial(extras, dials.cool, dials.chaos) >= 4.5 else "stock",
        desktop_icons=not widgets,                           # icons and widgets would overlap
        bar=bar,
        blur=noisy_dial(extras, dials.cool, dials.chaos) >= 4.5,
        dock=dock,
        terminal={**terminal_colors(palette),
                  "transparency": terminal_transparency(style.fill, wallpaper.features.brightness)},
        layout=template,
        mirrored=mirrored,
        widgets=widgets,
    )
    look.validate()
    return look
