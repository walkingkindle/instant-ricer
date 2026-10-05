import random

import pytest

from ricer import palette
from ricer.look import Dials

from conftest import noise, solid, two_tone


def test_hex_round_trip():
    assert palette.rgb_to_hex(palette.hex_to_rgb("#3fa9c4")) == "#3fa9c4"


def test_hue_warmth_poles():
    assert palette.hue_warmth(30) == pytest.approx(1)
    assert palette.hue_warmth(210) == pytest.approx(-1)


def test_shift_hue_takes_the_short_way_round():
    assert palette.shift_hue_toward(350, 10, 0.5) == pytest.approx(0)
    assert palette.shift_hue_toward(10, 350, 0.5) == pytest.approx(0)


def test_extract_colors_finds_both_halves_of_a_two_tone_image():
    colors = palette.extract_colors(two_tone((255, 0, 0), (0, 0, 255)))
    assert {c for c, _ in colors[:2]} == {"#ff0000", "#0000ff"}
    assert sum(w for _, w in colors) == pytest.approx(1)


def test_extract_colors_is_sorted_by_share():
    weights = [w for _, w in palette.extract_colors(noise())]
    assert weights == sorted(weights, reverse=True)


def test_grey_wallpaper_takes_its_accent_hue_from_the_warmth_dial():
    grey = palette.extract_colors(solid((90, 90, 90)))
    warmths = [palette.hue_warmth(palette.hue_of(
        palette.build_palette(grey, Dials(warmth=w)).accent)) for w in range(1, 11)]
    assert warmths == sorted(warmths)
    assert warmths[0] < -0.9 and warmths[-1] > 0.9


def test_warmth_dial_picks_the_matching_colour_from_a_mixed_wallpaper():
    mixed = palette.extract_colors(two_tone((230, 140, 40), (40, 110, 230)))
    warm = palette.build_palette(mixed, Dials(warmth=10)).accent
    cold = palette.build_palette(mixed, Dials(warmth=1)).accent
    assert palette.hue_warmth(palette.hue_of(warm)) > 0.5
    assert palette.hue_warmth(palette.hue_of(cold)) < -0.5


def test_cool_dial_never_lowers_accent_saturation():
    colors = palette.extract_colors(two_tone((230, 140, 40), (40, 110, 230)))
    saturation = [palette.saturation_of(palette.build_palette(colors, Dials(cool=c)).accent)
                  for c in range(1, 11)]
    assert all(b >= a - 0.01 for a, b in zip(saturation, saturation[1:]))
    assert saturation[-1] > saturation[0] + 0.4


def test_ease_dial_never_lowers_card_opacity():
    alphas = [palette.card_alpha(e) for e in range(1, 11)]
    assert alphas == sorted(alphas) and alphas[0] < alphas[-1]


@pytest.mark.parametrize("image", [solid((250, 250, 250)), solid((5, 5, 5)), noise(),
                                   two_tone((230, 140, 40), (40, 110, 230))])
def test_text_stays_readable_on_the_card(image):
    colors = palette.extract_colors(image)
    for dials in (Dials(1, 1, 1), Dials(10, 10, 10), Dials(5, 5, 5)):
        made = palette.build_palette(colors, dials)
        assert palette.contrast_ratio(made.text, made.card) >= 7
        assert palette.contrast_ratio(made.accent, made.card) >= 4.5


def test_two_accents_are_visibly_different():
    for image in (solid((90, 90, 90)), two_tone((230, 140, 40), (40, 110, 230))):
        made = palette.build_palette(palette.extract_colors(image), Dials(8, 5, 5))
        assert palette.hue_distance(palette.hue_of(made.accent), palette.hue_of(made.accent2)) >= 30


def test_palette_without_rng_is_deterministic_and_rng_can_change_it():
    colors = palette.extract_colors(two_tone((230, 140, 40), (200, 60, 160)))
    assert palette.build_palette(colors, Dials()) == palette.build_palette(colors, Dials())
    variants = {palette.build_palette(colors, Dials(), random.Random(s)).accent for s in range(1, 20)}
    assert len(variants) == 2


def test_terminal_scheme_has_sixteen_readable_colours():
    made = palette.build_palette(palette.extract_colors(noise()), Dials())
    scheme = palette.terminal_colors(made)
    assert len(scheme["palette"]) == 16
    assert palette.contrast_ratio(scheme["foreground"], scheme["background"]) >= 7


@pytest.mark.parametrize("color, name", [("#2f7fe0", "blue"), ("#e0407a", "red"),
                                         ("#e95420", "default"), ("#c060d0", "magenta")])
def test_nearest_gtk_accent(color, name):
    assert palette.nearest_gtk_accent(color) == name
    assert name in palette.GNOME_ACCENT_NAMES
