"""Where widgets go.

The screen has nine zones. Widgets that share a zone stack neatly. Which zone a widget gets
is decided by cost: how busy the wallpaper is underneath, whether it would cover the
picture's subject, and how well the zone suits the layout template. Chaos decides how
strictly the cheapest zone wins. No GTK in here.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from ricer.chance import draw, softmin_weights, temperature
from ricer.look import ANCHORS, Dock
from ricer.wallpapers import Wallpaper

MARGIN = 40                          # px between a widget and the screen edge
TOP_GAP = 26                         # px below the top bar
GAP = 16                             # px between widgets stacked in one zone
BAR_HEIGHT = 48                      # assumed bar height when planning without a display
OFF_TEMPLATE = 0.6                   # cost of a zone the layout template does not mention
DROPPED = 3.0                        # cost of a widget that fits nowhere
# cost of each pair of widgets sharing a zone: spread-out layouts dislike stacking,
# the column layout is built on it
STACK_COST = {"corners": 0.14, "column": 0.0, "stage": 0.04, "scatter": 0.14}
# above these, plain text over the wallpaper is hard to read and gets a card behind it
BUSY_LIMIT, BRIGHT_LIMIT = 0.34, 0.56
CALM_BUSY, CALM_BRIGHT = 0.20, 0.42  # below both, even a calendar can go without a card

# layout templates: widget type -> zone -> extra cost. "*" covers types not listed.
TEMPLATES = {
    "corners": {
        "clock": {"top-center": 0.0, "top-left": 0.08, "top-right": 0.08,
                  "bottom-left": 0.25, "bottom-right": 0.25},
        "*": {"top-left": 0.0, "top-right": 0.0, "bottom-left": 0.0, "bottom-right": 0.0},
    },
    "column": {                       # one tidy column down the right-hand side
        "clock": {"top-left": 0.0, "top-center": 0.05, "right": 0.2},
        "greeting": {"top-left": 0.0, "top-center": 0.15, "bottom-left": 0.15},
        "ornament": {"bottom-left": 0.0, "left": 0.1, "top-left": 0.2},
        "*": {"right": 0.0},
    },
    "stage": {                        # the clock takes centre stage, the rest flank it
        "clock": {"top-center": 0.0, "center": 0.3},
        "greeting": {"top-center": 0.0, "bottom-center": 0.25},
        "media": {"left": 0.0, "bottom-left": 0.2},
        "ornament": {"bottom-center": 0.1, "bottom-right": 0.1, "bottom-left": 0.2},
        "*": {"right": 0.0, "left": 0.12},
    },
    # wherever the wallpaper is calm; the very middle is where pictures keep their subject,
    # so it has to be clearly the best spot before anything goes there
    "scatter": {"*": {anchor: (0.25 if anchor == "center" else 0.0) for anchor in ANCHORS}},
}


@dataclass(frozen=True)
class Box:
    """A widget to place: its type and planned size."""
    type: str
    width: int
    height: int


def split(anchor: str) -> tuple[str, str]:
    """('top' | 'middle' | 'bottom', 'left' | 'center' | 'right') for a zone name."""
    vertical, _, horizontal = anchor.rpartition("-")
    if not vertical:
        return "middle", anchor
    return vertical, horizontal


def mirror(anchor: str) -> str:
    if anchor.endswith("left"):
        return anchor[:-4] + "right"
    if anchor.endswith("right"):
        return anchor[:-5] + "left"
    return anchor


def side(anchor: str) -> str:
    """Which way text in this zone should be aligned."""
    return split(anchor)[1]


def dock_insets(dock: Dock) -> tuple[int, int, int]:
    """Extra (left, right, bottom) clearance for a dock that floats over the desktop.

    An always-visible dock already shrinks the work area; an auto-hiding one does not, yet it
    is on show whenever the desktop is, so widgets must leave it room.
    """
    if not dock.autohide:
        return 0, 0, 0
    room = dock.icon_size + 36
    return (room if dock.position == "LEFT" else 0, room if dock.position == "RIGHT" else 0, 0)


def dock_forbidden(dock: Dock) -> set[str]:
    """Zones a floating dock sits in."""
    if not dock.autohide:
        return set()
    return {"BOTTOM": {"bottom-center"}, "LEFT": {"left"}, "RIGHT": {"right"}}[dock.position]


def arrange(items: list[tuple[str, int, int]], area: tuple[int, int, int, int],
            insets: tuple[int, int, int] = (0, 0, 0)) -> list[tuple[int, int]]:
    """Top-left corner for each (anchor, width, height), stacking those that share a zone."""
    ax, ay, aw, ah = area
    left, right, bottom = insets
    groups: dict[str, list[int]] = {}
    for index, (anchor, _, _) in enumerate(items):
        groups.setdefault(anchor, []).append(index)
    placed: list[tuple[int, int]] = [(0, 0)] * len(items)
    for anchor, members in groups.items():
        vertical, horizontal = split(anchor)
        total = sum(items[i][2] for i in members) + GAP * (len(members) - 1)
        top = ay + TOP_GAP
        if vertical == "top":
            y = top
        elif vertical == "bottom":
            y = ay + ah - MARGIN - bottom - total
        else:
            y = top + (ah - TOP_GAP - MARGIN - bottom - total) // 2
        y = max(top, y)
        for i in members:
            _, width, height = items[i]
            if horizontal == "left":
                x = ax + MARGIN + left
            elif horizontal == "right":
                x = ax + aw - MARGIN - right - width
            else:
                x = ax + (aw - width) // 2
            placed[i] = (x, y)
            y += height + GAP
    return placed


def planning_area(screen: tuple[int, int]) -> tuple[int, int, int, int]:
    return 0, BAR_HEIGHT, screen[0], screen[1] - BAR_HEIGHT


def region(wallpaper: Wallpaper, screen: tuple[int, int],
           rect: tuple[int, int, int, int]) -> tuple[float, float, float]:
    """(busy, bright, subject) of the wallpaper under a screen rectangle.

    Accounts for the wallpaper being zoomed to fill the screen and cropped at the centre.
    """
    if wallpaper.grid is None:
        return 0.0, 0.0, 0.0
    (iw, ih), (sw, sh) = wallpaper.size, screen
    zoom = max(sw / iw, sh / ih)
    vw, vh = sw / zoom / iw, sh / zoom / ih
    ox, oy = (1 - vw) / 2, (1 - vh) / 2
    x, y, w, h = rect
    return wallpaper.grid.region(ox + x / sw * vw, oy + y / sh * vh,
                                 ox + (x + w) / sw * vw, oy + (y + h) / sh * vh)


def region_cost(stats: tuple[float, float, float]) -> float:
    busy, bright, subject = stats
    return 0.5 * busy + 0.9 * subject + 0.15 * max(0.0, bright - 0.5)


def needs_card(stats: tuple[float, float, float]) -> bool:
    return stats[0] > BUSY_LIMIT or stats[1] > BRIGHT_LIMIT


def is_calm(stats: tuple[float, float, float]) -> bool:
    return stats[0] < CALM_BUSY and stats[1] < CALM_BRIGHT


def rectangles(boxes, anchors, area, insets) -> dict[int, tuple[int, int, int, int]]:
    """(x, y, width, height) of every box that has a zone, keyed by its index."""
    order = [i for i in range(len(boxes)) if anchors.get(i)]
    spots = arrange([(anchors[i], boxes[i].width, boxes[i].height) for i in order], area, insets)
    return {i: (x, y, boxes[i].width, boxes[i].height) for i, (x, y) in zip(order, spots)}


def fits(rects: dict, area, insets) -> bool:
    """True if every rectangle is on screen and none touch."""
    ax, ay, aw, ah = area
    left, right, bottom = insets
    values = list(rects.values())
    for x, y, w, h in values:
        if x < ax + left or x + w > ax + aw - right or y < ay or y + h > ay + ah - MARGIN // 2 - bottom:
            return False
    for index, (x, y, w, h) in enumerate(values):
        for ox, oy, ow, oh in values[index + 1:]:
            if x < ox + ow + GAP and ox < x + w + GAP and y < oy + oh + GAP and oy < y + h + GAP:
                return False
    return True


def template_costs(template: str, mirrored: bool) -> dict:
    table = TEMPLATES[template]
    if not mirrored:
        return table
    return {kind: {mirror(anchor): cost for anchor, cost in zones.items()}
            for kind, zones in table.items()}


def total_cost(boxes: list[Box], anchors: dict, wallpaper: Wallpaper, screen, template: str,
               mirrored: bool, insets=(0, 0, 0)) -> float:
    """How good a finished placement is; lower is better."""
    table = template_costs(template, mirrored)
    rects = rectangles(boxes, anchors, planning_area(screen), insets)
    cost = DROPPED * sum(1 for i in range(len(boxes)) if not anchors.get(i))
    sharing: dict[str, int] = {}
    for i, rect in rects.items():
        zones = table.get(boxes[i].type, table["*"])
        cost += region_cost(region(wallpaper, screen, rect)) + zones.get(anchors[i], OFF_TEMPLATE)
        cost += STACK_COST[template] * sharing.get(anchors[i], 0)
        sharing[anchors[i]] = sharing.get(anchors[i], 0) + 1
    return cost


def assign(boxes: list[Box], wallpaper: Wallpaper, screen: tuple[int, int], template: str,
           mirrored: bool, forbidden: set[str], insets: tuple[int, int, int],
           rng: random.Random, chaos: int) -> dict[int, str | None]:
    """Choose a zone for each box. A box that fits nowhere gets None."""
    area = planning_area(screen)
    table = template_costs(template, mirrored)
    sharpness = 14 / temperature(chaos)
    best: tuple[float, dict] | None = None
    for _ in range(max(2, 14 - chaos)):
        order = sorted(range(len(boxes)),
                       key=lambda i: -boxes[i].width * boxes[i].height * rng.uniform(0.7, 1.3))
        chosen: dict[int, str | None] = {}
        for i in order:
            zones = table.get(boxes[i].type, table["*"])
            costs = {}
            for anchor in ANCHORS:
                if anchor in forbidden:
                    continue
                rects = rectangles(boxes, {**chosen, i: anchor}, area, insets)
                if fits(rects, area, insets):
                    costs[anchor] = (region_cost(region(wallpaper, screen, rects[i]))
                                     + zones.get(anchor, OFF_TEMPLATE)
                                     + STACK_COST[template] * list(chosen.values()).count(anchor))
            chosen[i] = draw(rng, softmin_weights(costs, sharpness)) if costs else None
        cost = total_cost(boxes, chosen, wallpaper, screen, template, mirrored, insets)
        if best is None or cost < best[0]:
            best = (cost, chosen)
    return best[1] if best else {}
