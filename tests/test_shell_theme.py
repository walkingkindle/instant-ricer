import dataclasses

import pytest

from ricer import shell_theme
from ricer.generator import generate
from ricer.look import Dials

BASE = 'url("/usr/share/gnome-shell/theme/Yaru-dark/gnome-shell.css")'


def test_cards_bar_has_floating_boxes_and_the_palette(wallpaper_set):
    look = generate(Dials(8, 4, 5), wallpaper_set)
    assert look.bar_style == "cards" and look.gradient
    css = shell_theme.render(look, BASE)
    assert css.count("@import") == 1 and f"@import {BASE};" in css
    assert "#panelLeft, #panelCenter, #panelRight" in css
    assert f"color: {look.palette.accent};" in css
    assert f"background-gradient-end: {look.palette.accent2};" in css
    assert "$" not in css


def test_solid_bar_is_one_strip(wallpaper_set):
    look = generate(Dials(5, 9, 5), wallpaper_set)
    assert look.bar_style == "solid"
    css = shell_theme.render(look, BASE)
    assert "#panelLeft" not in css
    assert f"{look.palette.card_alpha});" in css and "$" not in css


def test_without_gradient_both_ends_use_the_accent(wallpaper_set):
    look = dataclasses.replace(generate(Dials(8, 4, 5), wallpaper_set), gradient=False)
    css = shell_theme.render(look, BASE)
    assert look.palette.accent2 not in css
    assert f"background-gradient-end: {look.palette.accent};" in css


def test_bar_text_grows_with_the_scale(wallpaper_set):
    small = shell_theme.render(generate(Dials(5, 1, 5), wallpaper_set), BASE)
    large = shell_theme.render(generate(Dials(5, 7, 5), wallpaper_set), BASE)
    assert "font-size: 11.0pt" in small and "height: 44px" in small
    assert "font-size: 12.9pt" in large and "height: 51px" in large


def test_stock_bar_has_no_stylesheet(wallpaper_set):
    look = generate(Dials(1, 1, 5), wallpaper_set)
    assert look.bar_style == "stock"
    with pytest.raises(ValueError):
        shell_theme.render(look, BASE)
