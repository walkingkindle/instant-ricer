import random

import pytest

from ricer import placement
from ricer.look import ANCHORS, Dock
from ricer.placement import (GAP, MARGIN, TOP_GAP, Box, arrange, assign, dock_forbidden, dock_insets,
                             mirror, planning_area, region, side, split)

SCREEN = (1920, 1080)
AREA = (100, 50, 1920, 1080)


@pytest.mark.parametrize("anchor, expected", [
    ("top-left", (140, 76)), ("top-center", (910, 76)), ("top-right", (1680, 76)),
    ("left", (140, 533)), ("center", (910, 533)), ("right", (1680, 533)),
    ("bottom-left", (140, 990)), ("bottom-center", (910, 990)), ("bottom-right", (1680, 990)),
])
def test_arrange_puts_one_widget_at_each_anchor(anchor, expected):
    assert arrange([(anchor, 300, 100)], AREA) == [expected]
    assert anchor in ANCHORS


def test_widgets_sharing_a_zone_stack_in_order_with_a_gap():
    top = arrange([("top-right", 300, 100), ("bottom-left", 50, 50), ("top-right", 200, 80)], AREA)
    assert top[0] == (1680, 76) and top[2] == (1780, 76 + 100 + GAP)      # right edges line up
    bottom = arrange([("bottom-left", 300, 100), ("bottom-left", 200, 80)], AREA)
    assert bottom[1][1] + 80 == 50 + 1080 - MARGIN                         # the stack ends at the margin
    assert bottom[0][1] + 100 + GAP == bottom[1][1] and bottom[0][0] == bottom[1][0] == 140
    middle = arrange([("center", 300, 100), ("center", 100, 100)], AREA)
    assert middle[0][0] == 910 and middle[1][0] == 1010                    # centred on one axis
    span = (middle[0][1] - (50 + TOP_GAP), (50 + 1080 - MARGIN) - (middle[1][1] + 100))
    assert abs(span[0] - span[1]) <= 1                                     # and centred vertically


def test_insets_leave_room_for_a_floating_dock():
    assert arrange([("left", 100, 100)], AREA, (80, 0, 0))[0][0] == 100 + MARGIN + 80
    assert arrange([("right", 100, 100)], AREA, (0, 80, 0))[0][0] == 100 + 1920 - MARGIN - 80 - 100
    assert arrange([("bottom-left", 100, 100)], AREA, (0, 0, 60))[0][1] == 50 + 1080 - MARGIN - 60 - 100


def test_a_stack_too_tall_for_its_zone_starts_at_the_top_rather_than_above_it():
    spots = arrange([("bottom-left", 100, 700), ("bottom-left", 100, 700)], AREA)
    assert spots[0][1] == 50 + TOP_GAP


def test_zone_helpers():
    assert split("top-left") == ("top", "left") and split("right") == ("middle", "right")
    assert split("center") == ("middle", "center")
    assert [mirror(a) for a in ("top-left", "right", "center", "bottom-center")] == [
        "top-right", "left", "center", "bottom-center"]
    assert sorted(mirror(a) for a in ANCHORS) == sorted(ANCHORS)
    assert side("bottom-right") == "right" and side("top-center") == "center" and side("left") == "left"


def test_a_floating_dock_claims_its_zone_and_a_fixed_one_does_not():
    floating_bottom = Dock(position="BOTTOM", autohide=True, icon_size=48)
    assert dock_forbidden(floating_bottom) == {"bottom-center"} and dock_insets(floating_bottom) == (0, 0, 0)
    floating_left = Dock(position="LEFT", autohide=True, icon_size=48)
    assert dock_forbidden(floating_left) == {"left"} and dock_insets(floating_left) == (84, 0, 0)
    assert dock_insets(Dock(position="RIGHT", autohide=True, icon_size=40)) == (0, 76, 0)
    fixed = Dock(position="LEFT", autohide=False)
    assert dock_forbidden(fixed) == set() and dock_insets(fixed) == (0, 0, 0)   # the work area covers it


def test_region_reads_the_part_of_the_wallpaper_a_widget_covers(lopsided):
    busy_side = region(lopsided, SCREEN, (100, 300, 400, 300))
    calm_side = region(lopsided, SCREEN, (1400, 300, 400, 300))
    assert busy_side[0] > 0.8 and calm_side[0] < 0.05
    assert placement.needs_card(busy_side) and not placement.needs_card(calm_side)
    assert placement.is_calm(calm_side) and not placement.is_calm(busy_side)
    assert placement.region_cost(busy_side) > placement.region_cost(calm_side) + 0.3


def test_region_allows_for_the_wallpaper_being_cropped_to_fill_the_screen(lopsided):
    # on a portrait screen only the middle of a landscape picture shows: the left edge of
    # the screen is then well inside the picture's busy half, the right edge inside the calm half
    portrait = (1080, 1920)
    assert region(lopsided, portrait, (0, 800, 200, 200))[0] > 0.8
    assert region(lopsided, portrait, (880, 800, 200, 200))[0] < 0.05
    no_grid = type(lopsided)(path="x", features=lopsided.features, colors=())
    assert region(no_grid, SCREEN, (0, 0, 10, 10)) == (0.0, 0.0, 0.0)


def boxes(*sizes):
    return [Box("system", w, h) for w, h in sizes]


def run(box_list, wallpaper, seed=1, chaos=1, template="scatter", mirrored=False, forbidden=(), insets=(0, 0, 0)):
    return assign(box_list, wallpaper, SCREEN, template, mirrored, set(forbidden), insets,
                  random.Random(seed), chaos)


def test_widgets_avoid_the_busy_side_of_the_wallpaper(lopsided):
    for seed in range(20):
        anchors = run(boxes((300, 150), (300, 150), (300, 150)), lopsided, seed)
        assert all(side(anchor) == "right" for anchor in anchors.values()), anchors


def test_chaos_never_puts_a_widget_somewhere_unreadable(lopsided):
    for seed in range(40):
        anchors = run(boxes((300, 150), (300, 150)), lopsided, seed, chaos=10)
        assert all(side(anchor) == "right" for anchor in anchors.values()), anchors


def test_chaos_loosens_the_choice_among_reasonable_zones(wallpaper_set):
    flat = wallpaper_set[2]                                  # grey: only the template has a say

    def top_centre_share(chaos):
        spots = [run([Box("clock", 500, 240)], flat, seed, chaos, template="corners")[0]
                 for seed in range(120)]
        return spots.count("top-center") / len(spots), set(spots)

    calm_share, calm_spots = top_centre_share(1)
    wild_share, wild_spots = top_centre_share(10)
    assert calm_share == 1.0 and calm_spots == {"top-center"}
    assert 0.3 < wild_share < 0.92 and len(wild_spots) >= 3
    # even so, zones the layout does not name at all stay out of it
    assert wild_spots <= {"top-center", "top-left", "top-right", "bottom-left", "bottom-right"}


def test_forbidden_zones_are_never_used(lopsided):
    banned = {"right", "top-right", "bottom-right"}
    for seed in range(20):
        anchors = run(boxes((300, 150), (300, 150)), lopsided, seed, chaos=10, forbidden=banned)
        assert not banned & set(anchors.values())


@pytest.mark.parametrize("template", sorted(placement.TEMPLATES))
@pytest.mark.parametrize("chaos", [1, 10])
def test_placed_widgets_never_overlap_and_stay_on_screen(wallpaper_set, template, chaos):
    sizes = ((560, 280), (420, 132), (260, 132), (274, 300), (300, 88), (240, 240))
    area = planning_area(SCREEN)
    for seed in range(12):
        box_list = [Box(kind, w, h) for kind, (w, h) in zip(
            ("clock", "media", "system", "calendar", "progress", "ornament"), sizes)]
        anchors = run(box_list, wallpaper_set[seed % len(wallpaper_set)], seed, chaos, template,
                      mirrored=bool(seed % 2))
        rects = placement.rectangles(box_list, anchors, area, (0, 0, 0))
        assert placement.fits(rects, area, (0, 0, 0))
        assert len(rects) == sum(1 for anchor in anchors.values() if anchor)


def test_what_cannot_fit_is_dropped_not_overlapped(wallpaper_set):
    huge = boxes(*[(900, 700)] * 5)
    anchors = run(huge, wallpaper_set[0], chaos=5)
    placed = [a for a in anchors.values() if a]
    assert 1 <= len(placed) < 5 and None in anchors.values()
    rects = placement.rectangles(huge, anchors, planning_area(SCREEN), (0, 0, 0))
    assert placement.fits(rects, planning_area(SCREEN), (0, 0, 0))


def test_the_column_layout_stacks_on_one_side_and_mirroring_flips_it(wallpaper_set):
    flat = wallpaper_set[2]                                  # grey: the wallpaper has no say
    cards = [Box("media", 320, 132), Box("system", 320, 132), Box("calendar", 320, 260)]
    assert set(run(cards, flat, template="column").values()) == {"right"}
    assert set(run(cards, flat, template="column", mirrored=True).values()) == {"left"}


def test_the_corners_layout_spreads_widgets_out(wallpaper_set):
    flat = wallpaper_set[2]
    cards = [Box("media", 320, 132), Box("system", 320, 132), Box("calendar", 320, 260),
             Box("progress", 260, 132)]
    anchors = run(cards, flat, template="corners")
    assert sorted(anchors.values()) == ["bottom-left", "bottom-right", "top-left", "top-right"]


def test_the_stage_layout_centres_the_clock_and_flanks_it(wallpaper_set):
    flat = wallpaper_set[2]
    anchors = run([Box("clock", 500, 260), Box("media", 232, 344), Box("system", 280, 116)], flat,
                  template="stage")
    assert anchors == {0: "top-center", 1: "left", 2: "right"}


def test_total_cost_counts_dropped_widgets_and_stacking(wallpaper_set):
    flat, pair = wallpaper_set[2], boxes((200, 100), (200, 100))
    spread = placement.total_cost(pair, {0: "top-left", 1: "top-right"}, flat, SCREEN, "corners", False)
    stacked = placement.total_cost(pair, {0: "top-left", 1: "top-left"}, flat, SCREEN, "corners", False)
    dropped = placement.total_cost(pair, {0: "top-left", 1: None}, flat, SCREEN, "corners", False)
    assert stacked == pytest.approx(spread + placement.STACK_COST["corners"])
    assert dropped == pytest.approx(spread + placement.DROPPED)
