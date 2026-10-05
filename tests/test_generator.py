import itertools

import pytest

from ricer.generator import generate
from ricer.look import Dials, LookError
from ricer.palette import hue_of, hue_warmth, saturation_of
from ricer.wallpapers import NoWallpapersError

from conftest import as_wallpaper, solid

DIAL_VALUES = range(1, 11)


def test_same_dials_give_the_identical_look(wallpaper_set):
    assert generate(Dials(7, 3, 9), wallpaper_set) == generate(Dials(7, 3, 9), wallpaper_set)


def test_wallpaper_order_does_not_matter(wallpaper_set):
    assert (generate(Dials(4, 6, 2), wallpaper_set)
            == generate(Dials(4, 6, 2), list(reversed(wallpaper_set))))


def test_every_dial_combination_gives_a_valid_look(wallpaper_set):
    for cool, ease, warmth in itertools.product(DIAL_VALUES, repeat=3):
        look = generate(Dials(cool, ease, warmth), wallpaper_set)
        look.validate()
        assert look.widgets[0].type == "clock"


def test_seeds_reproduce_and_differ(wallpaper_set):
    dials = Dials(6, 5, 5)
    assert generate(dials, wallpaper_set, seed=42) == generate(dials, wallpaper_set, seed=42)
    looks = {str(generate(dials, wallpaper_set, seed=s).to_dict()) for s in range(1, 30)}
    assert len(looks) > 3
    for seed in range(1, 30):
        generate(dials, wallpaper_set, seed=seed).validate()


@pytest.mark.parametrize("bad", [Dials(0, 5, 5), Dials(5, 11, 5), Dials(5, 5, -1)])
def test_out_of_range_dials_are_rejected(wallpaper_set, bad):
    with pytest.raises(LookError):
        generate(bad, wallpaper_set)


def test_empty_library_is_reported(wallpaper_set):
    with pytest.raises(NoWallpapersError):
        generate(Dials(), [])


def by_dial(name, wallpapers, **fixed):
    """The looks you get sweeping one dial from 1 to 10 with the others held."""
    return [generate(Dials(**{**fixed, name: value}), wallpapers) for value in DIAL_VALUES]


@pytest.mark.parametrize("cool, warmth", [(1, 1), (5, 5), (10, 10), (3, 8)])
def test_raising_ease_never_hides_the_dock_or_thins_the_cards(wallpaper_set, cool, warmth):
    looks = by_dial("ease", wallpaper_set, cool=cool, warmth=warmth)
    for lower, higher in zip(looks, looks[1:]):
        assert higher.palette.card_alpha >= lower.palette.card_alpha
        assert higher.dock.opacity >= lower.dock.opacity
        assert higher.dock.icon_size >= lower.dock.icon_size
        assert higher.widget_scale >= lower.widget_scale
        assert not (higher.dock.autohide and not lower.dock.autohide)
        assert len(higher.widgets) >= len(lower.widgets)
    assert looks[0].dock.autohide and not looks[-1].dock.autohide


@pytest.mark.parametrize("ease, warmth", [(1, 1), (5, 5), (10, 10), (8, 2)])
def test_raising_cool_never_removes_widgets_or_shrinks_the_clock(wallpaper_set, ease, warmth):
    looks = by_dial("cool", wallpaper_set, ease=ease, warmth=warmth)
    for lower, higher in zip(looks, looks[1:]):
        assert len(higher.widgets) >= len(lower.widgets)
        assert higher.widgets[0].options["size"] >= lower.widgets[0].options["size"]
        assert higher.blur >= lower.blur and higher.gradient >= lower.gradient


def test_raising_cool_never_lowers_saturation_on_a_fixed_wallpaper():
    one = [as_wallpaper("only", solid((60, 120, 200)))]
    saturation = [saturation_of(look.palette.accent) for look in by_dial("cool", one, ease=5, warmth=5)]
    assert all(b >= a - 0.01 for a, b in zip(saturation, saturation[1:]))


def test_warmth_dial_moves_wallpaper_and_accent_the_right_way(wallpaper_set):
    cold, warm = generate(Dials(8, 5, 1), wallpaper_set), generate(Dials(8, 5, 10), wallpaper_set)
    assert cold.wallpaper.endswith("cold.png") and warm.wallpaper.endswith("warm.png")
    assert hue_warmth(hue_of(cold.palette.accent)) < 0 < hue_warmth(hue_of(warm.palette.accent))


def test_the_extremes_look_like_the_plan_says(wallpaper_set):
    minimal = generate(Dials(1, 1, 5), wallpaper_set)
    assert [w.type for w in minimal.widgets] == ["clock"]
    assert minimal.bar_style == "stock" and not minimal.blur and not minimal.gradient

    practical = generate(Dials(5, 10, 5), wallpaper_set)
    assert practical.bar_style == "solid" and not practical.dock.floating
    system = next(w for w in practical.widgets if w.type == "system")
    assert system.options["rows"] == ["cpu", "ram", "temp", "gpu", "battery"]

    flashy = generate(Dials(10, 3, 5), wallpaper_set)
    assert flashy.bar_style == "cards" and flashy.blur and flashy.gradient
    assert {w.type for w in flashy.widgets} == {"clock", "media", "system"}
    assert flashy.widgets[0].options["thin"]
