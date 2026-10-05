import dataclasses
import itertools
import statistics

import pytest

from ricer import generator, metrics
from ricer.chance import stream
from ricer.generator import (Kept, bar_for, dock_for, generate, kept_from, layout_for, style_for,
                             widget_budget, widget_set)
from ricer.look import ANCHORS, Bar, Dials, LookError
from ricer.palette import hue_of, hue_warmth
from ricer.wallpapers import NoWallpapersError

SEEDS = range(1, 301)


def over_seeds(stage, dials, name):
    """Run one stage of the generator for many seeds."""
    return [stage(dials, stream(seed, name)) for seed in SEEDS]


def share(values, wanted):
    return sum(1 for value in values if value == wanted) / len(values)


# -- the whole look ---------------------------------------------------------------------------

def test_the_same_seed_gives_the_identical_look(wallpaper_set):
    assert generate(Dials(7, 3, 9, 6), wallpaper_set, 42) == generate(Dials(7, 3, 9, 6), wallpaper_set, 42)
    assert (generate(Dials(4, 6, 2), wallpaper_set, 5)
            == generate(Dials(4, 6, 2), list(reversed(wallpaper_set)), 5))


def test_different_seeds_give_different_looks(wallpaper_set):
    looks = {str(generate(Dials(7, 5, 5), wallpaper_set, seed).to_dict()) for seed in range(1, 31)}
    assert len(looks) == 30


def test_random_looks_across_the_dial_space_are_all_valid(wallpaper_set):
    combos = list(itertools.product((1, 4, 7, 10), repeat=4))
    for index, (cool, ease, warmth, chaos) in enumerate(combos):
        look = generate(Dials(cool, ease, warmth, chaos), wallpaper_set, 1000 + index)
        look.validate()
        assert len(look.widgets) <= generator.MAX_WIDGETS + 1
        assert look.desktop_icons == (not look.widgets)
        for widget in look.widgets:
            assert widget.anchor in ANCHORS and 0 <= widget.options["fill"] <= 1
            assert widget.options["align"] in ("left", "center", "right")


@pytest.mark.parametrize("bad", [Dials(0, 5, 5), Dials(5, 11, 5), Dials(5, 5, -1), Dials(chaos=0)])
def test_out_of_range_dials_are_rejected(wallpaper_set, bad):
    with pytest.raises(LookError):
        generate(bad, wallpaper_set, 1)


def test_an_empty_library_is_reported():
    with pytest.raises(NoWallpapersError):
        generate(Dials(), [], 1)


def test_warmth_moves_wallpaper_and_accent_on_average(wallpaper_set):
    def lean(warmth):
        looks = [generate(Dials(6, 5, warmth, 4), wallpaper_set, seed) for seed in range(1, 61)]
        return (statistics.mean(hue_warmth(hue_of(look.palette.accent)) for look in looks),
                share([look.wallpaper for look in looks], "/walls/warm.png"))

    (cold_hue, cold_wall), (warm_hue, warm_wall) = lean(1), lean(10)
    assert cold_hue < -0.3 < 0.3 < warm_hue
    assert warm_wall > 0.5 > cold_wall


# -- fixed rules that randomness may not break ------------------------------------------------

def test_the_calm_end_stays_nearly_empty_and_the_loud_end_is_full():
    for chaos in (1, 5, 10):
        for cool in (1, 2):
            counts = over_seeds(widget_budget, Dials(cool=cool, chaos=chaos), "widgets")
            assert max(counts) <= 1
    assert statistics.mean(over_seeds(widget_budget, Dials(cool=10), "widgets")) > 5.3
    assert max(over_seeds(widget_budget, Dials(cool=10, chaos=10), "widgets")) <= 7


def test_the_dock_never_hides_from_ease_seven_up():
    for ease in range(1, 11):
        for chaos in (1, 10):
            docks = over_seeds(dock_for, Dials(ease=ease, chaos=chaos), "dock")
            assert {dock.autohide for dock in docks} == {ease <= 6}
            assert all(32 <= dock.icon_size <= 64 and dock.icon_size % 2 == 0 for dock in docks)


def test_widgets_keep_clear_of_a_floating_dock(wallpaper_set):
    for seed in range(1, 80):
        look = generate(Dials(9, 4, 5, 8), wallpaper_set, seed)
        zones = {widget.anchor for widget in look.widgets}
        blocked = {"BOTTOM": "bottom-center", "LEFT": "left", "RIGHT": "right"}[look.dock.position]
        assert look.dock.autohide and blocked not in zones


def test_a_cardless_look_frames_all_its_cards_or_none(wallpaper_set):
    by_name = {w.path: w for w in wallpaper_set}
    # dark and flat: cards can be left off.  Noise: every card is needed.
    for name, expected in (("/walls/dusk.png", 0.0), ("/walls/noisy.png", 0.55)):
        checked = 0
        for seed in range(1, 120):
            look = generate(Dials(8, 2, 5, 6), [by_name[name]], seed)
            framed = [w.options["fill"] for w in look.widgets
                      if w.type in metrics.STRUCTURED and not (w.type == "system" and w.design == "line")]
            if look.style.fill == 0 and framed:
                assert set(framed) == {expected}
                checked += 1
        assert checked > 10


def test_cards_get_more_opaque_over_a_busy_wallpaper(wallpaper_set, lopsided):
    from ricer.generator import card_fill
    from ricer.look import Style, WidgetSpec
    busy, calm = (0.9, 0.5, 0.2), (0.05, 0.1, 0.0)
    card = WidgetSpec("media", "card", "left")
    assert card_fill(card, Style(fill=0.4), busy) == 0.6 and card_fill(card, Style(fill=0.4), calm) == 0.4
    assert card_fill(card, Style(fill=0.8), busy) == 0.8
    assert card_fill(card, Style(fill=0.0), busy) == 0.55 and card_fill(card, Style(fill=0.0), calm) == 0.0
    big_clock = WidgetSpec("clock", "digital", "top-center", {"size": 120})
    small_clock = WidgetSpec("clock", "digital", "top-center", {"size": 64})
    assert card_fill(big_clock, Style(fill=0.6), busy) == 0.0          # big text carries itself
    assert card_fill(big_clock, Style(fill=0.6), (0.1, 0.8, 0.0)) == 0.45   # except on near-white
    assert card_fill(small_clock, Style(fill=0.6), calm) == 0.6
    dial = WidgetSpec("clock", "analog", "top-right", {"size": 110})
    assert card_fill(dial, Style(fill=0.6), calm) == 0.0 and card_fill(dial, Style(fill=0.0), busy) == 0.5
    assert card_fill(dial, Style(fill=0.8), (0.25, 0.3, 0.0)) == 0.8          # merely not calm is enough
    greeting = WidgetSpec("greeting", "plain", "top-left")
    assert card_fill(greeting, Style(fill=0.3), calm) == 0.0           # free-standing where it can be
    assert card_fill(greeting, Style(fill=0.3), busy) == 0.55 and card_fill(greeting, Style(fill=0.7), busy) == 0.7
    line = WidgetSpec("system", "line", "left")
    assert card_fill(line, Style(fill=0.0), busy) == 0.5 and card_fill(line, Style(fill=0.0), calm) == 0.0


def test_cards_stacked_in_one_zone_share_a_width(wallpaper_set):
    matched = 0
    for seed in range(1, 150):
        look = generate(Dials(9, 9, 5, 5), wallpaper_set, seed)
        zones = {}
        for widget in look.widgets:
            if (widget.type, widget.design) in metrics.WIDTH_AWARE:
                zones.setdefault(widget.anchor, []).append(widget.options.get("width"))
        for widths in zones.values():
            if len(widths) > 1 and widths[0] is not None:
                assert len(set(widths)) == 1
                matched += 1
    assert matched > 20


def test_the_clock_leaves_the_date_to_the_greeting():
    for seed in SEEDS:
        specs = {spec.type: spec for spec in widget_set(Dials(9, 5, 9, 5), Bar(), seed, stream(seed, "widgets"))}
        if "clock" in specs and "greeting" in specs:
            assert specs["clock"].options["date"] is False


# -- the dials tilt the odds ------------------------------------------------------------------

def test_cool_raises_the_number_of_desktop_widgets():
    means = [statistics.mean(over_seeds(widget_budget, Dials(cool=cool), "widgets")) for cool in range(1, 11)]
    assert all(later >= earlier - 0.05 for earlier, later in zip(means, means[1:]))
    assert means[0] < 0.2 and 2.6 < means[4] < 3.4 and means[9] > 5.3


def test_chaos_widens_the_spread_of_the_budget():
    calm = statistics.pstdev(over_seeds(widget_budget, Dials(cool=6, chaos=1), "widgets"))
    wild = statistics.pstdev(over_seeds(widget_budget, Dials(cool=6, chaos=10), "widgets"))
    assert wild > 2 * calm


def test_ease_puts_more_into_the_bar():
    def bar_stats(ease):
        bars = over_seeds(bar_for, Dials(ease=ease), "bar")
        return (share([bool(bar.stats) for bar in bars], True), share([bar.media for bar in bars], True),
                statistics.mean(len(bar.stats) for bar in bars))

    low, mid, high = bar_stats(2), bar_stats(5), bar_stats(9)
    assert low[0] < 0.05 and low[1] < 0.02
    assert 0.5 < mid[0] < 0.95 and mid[1] < 0.2
    assert high[0] > 0.99 and high[1] > 0.95 and high[2] > 4
    assert low[2] < mid[2] < high[2]


def test_bar_groups_prefer_opposite_sides():
    bars = [bar for bar in over_seeds(bar_for, Dials(ease=9), "bar") if bar.stats and bar.media]
    assert share([bar.stats_side == bar.media_side for bar in bars], True) < 0.3
    assert {bar.stats_side for bar in bars} == {"left", "right"}


def test_cool_and_ease_pick_the_bar_style():
    def styles(**dials):
        return [bar.style for bar in over_seeds(bar_for, Dials(**dials), "bar")]

    assert share(styles(cool=1), "stock") > 0.45
    assert share(styles(cool=5), "stock") == 0 and share(styles(cool=10), "stock") == 0
    assert share(styles(cool=6), "island") > 0.4
    assert share(styles(cool=10), "cards") > 0.6
    assert share(styles(cool=6, ease=10), "solid") > 0.3 > 0.1 > share(styles(cool=6, ease=5), "solid")
    assert len(set(styles(cool=5, chaos=10))) == 4           # everything but stock gets a turn


def test_warmth_shapes_the_style():
    cold, warm = over_seeds(style_for, Dials(warmth=1), "style"), over_seeds(style_for, Dials(warmth=10), "style")
    assert statistics.mean(s.radius for s in cold) + 10 < statistics.mean(s.radius for s in warm)
    assert share([s.voice for s in warm], "serif") > 3 * share([s.voice for s in cold], "serif")
    assert share([s.voice for s in cold], "mono") > 3 * share([s.voice for s in warm], "mono")
    assert share([s.border for s in cold], "accent") > share([s.border for s in warm], "accent") + 0.2
    assert all(0 <= s.radius <= 40 for s in cold + warm)


def test_ease_makes_cards_more_solid_and_text_bigger():
    looks_first, usable = over_seeds(style_for, Dials(ease=1), "style"), over_seeds(style_for, Dials(ease=10), "style")
    assert share([s.fill == 0 for s in looks_first], True) > 0.3
    assert share([s.fill == 0 for s in usable], True) == 0
    assert statistics.mean(s.fill for s in usable) > 0.65
    assert statistics.mean(s.scale for s in usable) > statistics.mean(s.scale for s in looks_first) + 0.2
    assert all(s.fill == 0 or s.fill >= 0.25 for s in looks_first + usable)


def test_cool_brings_gradients():
    assert share([s.gradient for s in over_seeds(style_for, Dials(cool=1), "style")], True) < 0.2
    assert share([s.gradient for s in over_seeds(style_for, Dials(cool=10), "style")], True) == 1.0


def design_shares(kind, **dials):
    designs = []
    for seed in SEEDS:
        designs += [spec.design for spec in widget_set(Dials(**dials), Bar(), seed, stream(seed, "widgets"))
                    if spec.type == kind]
    return {design: share(designs, design) for design in set(designs)}


def test_the_dials_tilt_which_designs_appear():
    assert design_shares("clock", cool=7, warmth=10).get("analog", 0) > 2 * design_shares(
        "clock", cool=7, warmth=1).get("analog", 0)
    assert design_shares("clock", cool=10).get("stacked", 0) > 2 * design_shares("clock", cool=4).get("stacked", 0)
    assert design_shares("calendar", cool=8, ease=10)["month"] > design_shares("calendar", cool=8, ease=1)["month"] + 0.2
    assert design_shares("system", cool=10)["rings"] > design_shares("system", cool=5)["rings"] + 0.15
    assert design_shares("media", cool=8, ease=1)["pill"] > design_shares("media", cool=8, ease=10).get("pill", 0) + 0.2
    assert set(design_shares("clock", cool=8, chaos=10)) == {"digital", "stacked", "analog", "words"}


def test_what_the_bar_already_shows_appears_less_on_the_desktop():
    def system_share(bar):
        sets = [{spec.type for spec in widget_set(Dials(cool=5), bar, seed, stream(seed, "widgets"))} for seed in SEEDS]
        return share(["system" in types for types in sets], True)

    assert system_share(Bar(stats=("cpu", "ram", "temp"))) < system_share(Bar()) - 0.1


def test_ornaments_belong_to_the_loud_end():
    def ornament_share(cool):
        sets = [{spec.type for spec in widget_set(Dials(cool=cool), Bar(), seed, stream(seed, "widgets"))} for seed in SEEDS]
        return share(["ornament" in types for types in sets], True)

    assert ornament_share(4) < 0.1 < 0.4 < ornament_share(10)


def test_layouts_follow_ease_and_cool():
    def layouts(**dials):
        return [template for template, _ in over_seeds(layout_for, Dials(**dials), "layout")]

    assert share(layouts(ease=10), "column") > share(layouts(ease=3), "column") + 0.2
    assert share(layouts(cool=10), "stage") > share(layouts(cool=3), "stage") + 0.15
    assert share(layouts(chaos=10), "scatter") > share(layouts(chaos=1), "scatter")
    mirrored = [flip for _, flip in over_seeds(layout_for, Dials(), "layout")]
    assert 0.4 < share(mirrored, True) < 0.6


# -- keeping parts of a look ------------------------------------------------------------------

@pytest.fixture
def current(wallpaper_set):
    return generate(Dials(8, 6, 5, 6), wallpaper_set, 77)


def rerolled(wallpaper_set, current, *parts):
    return [generate(Dials(8, 6, 5, 6), wallpaper_set, seed, keep=kept_from(current, parts))
            for seed in range(200, 225)]


def test_keeping_nothing_changes_everything(wallpaper_set, current):
    looks = rerolled(wallpaper_set, current)
    assert len({look.wallpaper for look in looks}) > 1
    assert kept_from(current, []) == Kept()


def test_keep_wallpaper(wallpaper_set, current):
    looks = rerolled(wallpaper_set, current, "wallpaper")
    assert {look.wallpaper for look in looks} == {current.wallpaper}
    assert len({look.style for look in looks}) > 5 and len({look.bar for look in looks}) > 2


def test_keep_style_carries_colours_and_everything_derived_from_them(wallpaper_set, current):
    for look in rerolled(wallpaper_set, current, "style"):
        assert (look.style, look.palette, look.terminal, look.gtk_accent) == (
            current.style, current.palette, current.terminal, current.gtk_accent)


def test_keep_widgets_keeps_the_set_and_designs_but_places_them_anew(wallpaper_set, current):
    def core(look):
        return [(w.type, w.design, {k: v for k, v in w.options.items() if k not in generator.PLACEMENT_KEYS})
                for w in look.widgets]

    looks = rerolled(wallpaper_set, current, "widgets")
    assert all(core(look) == core(current) for look in looks)
    assert len({tuple(w.anchor for w in look.widgets) for look in looks}) > 1


def test_keep_widgets_and_layout_freezes_the_zones(wallpaper_set, current):
    for look in rerolled(wallpaper_set, current, "widgets", "layout"):
        assert [(w.type, w.anchor) for w in look.widgets] == [(w.type, w.anchor) for w in current.widgets]
        assert (look.layout, look.mirrored) == (current.layout, current.mirrored)


def test_keep_layout_alone_keeps_the_template(wallpaper_set, current):
    looks = rerolled(wallpaper_set, current, "layout")
    assert {(look.layout, look.mirrored) for look in looks} == {(current.layout, current.mirrored)}


def test_keep_bar_and_dock(wallpaper_set, current):
    looks = rerolled(wallpaper_set, current, "bar", "dock")
    assert {look.bar for look in looks} == {current.bar} and {look.dock for look in looks} == {current.dock}


def test_a_kept_wallpaper_that_is_gone_is_simply_rerolled(wallpaper_set, current):
    gone = dataclasses.replace(current, wallpaper="/walls/deleted.png")
    look = generate(Dials(), wallpaper_set, 5, keep=kept_from(gone, ["wallpaper"]))
    assert look.wallpaper in {w.path for w in wallpaper_set}
