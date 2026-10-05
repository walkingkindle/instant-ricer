"""Choose the look to apply: generate several candidates, keep the best.

"Best" means well placed on its wallpaper and unlike the looks applied recently. The winner
is still just (dials, seed), so its printed seed reproduces it exactly.
"""
from __future__ import annotations

import random

from ricer import metrics, placement
from ricer.generator import SCREEN, Kept, generate, wallpaper_for
from ricer.look import Dials, Look
from ricer.placement import Box
from ricer.wallpapers import Wallpaper

CANDIDATES = 8
SCAN = 240                           # seeds looked through for ones that lead to a fresh wallpaper
FRESH_WALLPAPERS = 3                 # the wallpapers of this many recent looks are avoided
HISTORY = 6                          # how many recent looks are remembered
RECENCY = 0.6                        # each older look counts this much less
# Placement is a gate, not a contest: only a look whose widgets sit badly on the wallpaper
# is marked down. Ranking every candidate by cost would squeeze out the layouts that cost a
# little more by nature (the "stage" layout uses the middle of the screen) and with them variety.
QUALITY_GATE = 0.45
QUALITY_WEIGHT = 1.5
EMPTY_COST = 0.25                    # stand-in placement cost for a look with no widgets
# how much each feature contributes to two looks feeling different
FEATURE_WEIGHTS = {"wallpaper": 0.35, "widgets": 0.25, "zones": 0.2, "bar": 0.1, "layout": 0.05,
                   "voice": 0.05}


def fingerprint(look: Look) -> dict:
    """The features of a look that make it feel like itself. Stored in the history."""
    return {
        "wallpaper": look.wallpaper,
        "widgets": {widget.type: widget.design for widget in look.widgets},
        "zones": {widget.type: widget.anchor for widget in look.widgets},
        "bar": look.bar.style,
        "layout": f"{look.layout}{'-mirrored' if look.mirrored else ''}",
        "voice": look.style.voice,
    }


def _overlap(a: dict, b: dict) -> float:
    """Share of entries two dicts agree on, over all keys in either. Both empty counts as equal."""
    keys = set(a) | set(b)
    if not keys:
        return 1.0
    return sum(1 for key in keys if key in a and a.get(key) == b.get(key)) / len(keys)


def difference(a: dict, b: dict) -> float:
    """0 for the same look .. 1 for nothing in common."""
    total = 0.0
    for feature, weight in FEATURE_WEIGHTS.items():
        left, right = a.get(feature), b.get(feature)
        if isinstance(left, dict) or isinstance(right, dict):
            same = _overlap(left or {}, right or {})
        else:
            same = 1.0 if left == right else 0.0
        total += weight * (1 - same)
    return total


def novelty(print_: dict, history: list[dict]) -> float:
    """How unlike the recent looks this one is, the latest counting most. 1 with no history."""
    if not history:
        return 1.0
    weights = [RECENCY ** age for age in range(len(history))]
    return sum(w * difference(print_, past) for w, past in zip(weights, history)) / sum(weights)


def placement_cost(look: Look, wallpaper: Wallpaper, screen=SCREEN) -> float:
    """Mean cost per widget of where the look puts things; lower is better."""
    if not look.widgets:
        return EMPTY_COST
    boxes = [Box(w.type, *metrics.nominal(w.type, w.design, w.options, look.style.scale))
             for w in look.widgets]
    anchors = {i: w.anchor for i, w in enumerate(look.widgets)}
    total = placement.total_cost(boxes, anchors, wallpaper, screen, look.layout, look.mirrored,
                                 placement.dock_insets(look.dock))
    return total / len(boxes)


def candidate_seeds(dials: Dials, wallpapers: list[Wallpaper], history: list[dict], keep: Kept,
                    first: int, count: int = CANDIDATES) -> list[int]:
    """Seeds to try, favouring those whose wallpaper was not used in the last few looks.

    Which wallpaper a seed leads to is quick to work out, so a few hundred seeds are scanned.
    A seed is never altered, only preferred, so the look it gives stays reproducible. When the
    dials leave no real alternative (chaos 1 with one clear best match) the wallpaper repeats.
    """
    seeds = range(first, first + SCAN)
    recent = [past.get("wallpaper") for past in history[:FRESH_WALLPAPERS]]
    if keep.wallpaper or not recent or len(wallpapers) < 2:
        return list(seeds[:count])

    def staleness(seed: int) -> int:
        path = wallpaper_for(dials, wallpapers, seed).path
        return len(recent) - recent.index(path) if path in recent else 0

    stale = {seed: staleness(seed) for seed in seeds}
    freshest = min(stale.values())
    # only the freshest tier competes: a wallpaper seen two looks ago must not win on its
    # other merits while one not seen at all is on offer
    return [seed for seed in seeds if stale[seed] == freshest][:count]


def compose(dials: Dials, wallpapers: list[Wallpaper], history: list[dict] | None = None,
            seed: int | None = None, screen: tuple[int, int] = SCREEN, keep: Kept = Kept(),
            candidates: int = CANDIDATES, entropy: random.Random | None = None) -> Look:
    """The look for one run. With `seed` it is exactly that look; without, a fresh one."""
    if seed is not None:
        return generate(dials, wallpapers, seed, screen, keep)
    entropy = entropy or random.SystemRandom()
    history = history or []
    first = entropy.randrange(1, 2 ** 31 - SCAN)
    by_path = {wallpaper.path: wallpaper for wallpaper in wallpapers}
    best: tuple[float, Look] | None = None
    for candidate in candidate_seeds(dials, wallpapers, history, keep, first, candidates):
        look = generate(dials, wallpapers, candidate, screen, keep)
        excess = max(0.0, placement_cost(look, by_path[look.wallpaper], screen) - QUALITY_GATE)
        score = novelty(fingerprint(look), history) - QUALITY_WEIGHT * excess
        if best is None or score > best[0]:
            best = (score, look)
    return best[1]


def remember(history: list[dict], look: Look) -> list[dict]:
    """History with this look added at the front, trimmed to the last few."""
    return [fingerprint(look), *history][:HISTORY]
