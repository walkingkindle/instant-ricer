import dataclasses

import pytest

from ricer import shell_theme
from ricer.generator import generate
from ricer.look import BAR_STYLES, Bar, Dials, Style

BASE = 'url("/usr/share/gnome-shell/theme/Yaru-dark/gnome-shell.css")'


@pytest.fixture
def look(wallpaper_set):
    return generate(Dials(8, 4, 5), wallpaper_set, 3)


def render(look, bar="cards", **style):
    return shell_theme.render(dataclasses.replace(
        look, bar=Bar(style=bar), style=dataclasses.replace(look.style, **style)), BASE)


def test_every_bar_style_but_stock_has_a_stylesheet(look):
    assert set(shell_theme.STYLED) == set(BAR_STYLES) - {"stock"}
    for bar in shell_theme.STYLED:
        css = render(look, bar)
        assert css.count("@import") == 1 and f"@import {BASE};" in css
        assert "$" not in css and css.count("{") == css.count("}")
        assert f"color: {look.palette.accent};" in css      # the clock takes the accent everywhere
    with pytest.raises(ValueError):
        render(look, "stock")


def test_each_bar_style_is_built_the_way_it_is_named(look):
    cards, island = render(look, "cards"), render(look, "island")
    minimal, solid = render(look, "minimal"), render(look, "solid")
    assert "#panelLeft, #panelCenter, #panelRight" in cards and "#panelLeft" not in island
    assert "margin: 7px 12px 3px 12px" in island             # one piece, clear of the edges
    assert "text-shadow" in minimal and "icon-shadow" in minimal
    assert "#panelLeft" not in solid and "margin" not in solid


def test_gradient_look_uses_both_accents_and_a_flat_one_only_the_first(look):
    assert f"background-gradient-end: {look.palette.accent2};" in render(look, gradient=True)
    flat = render(look, gradient=False)
    assert f"background-gradient-end: {look.palette.accent};" in flat
    assert look.palette.accent2 not in flat


def test_corners_follow_the_style_up_to_a_full_pill(look):
    assert "border-radius: 6px;" in render(look, "cards", radius=6, scale=1.0)
    assert "border-radius: 17px;" in render(look, "cards", radius=40, scale=1.0)     # (44 - 10) / 2
    assert "border-radius: 8px;" in render(look, "island", radius=6, scale=1.0)      # menus: radius + 2
    assert "border-radius: 24px;" in render(look, "island", radius=40, scale=1.0)    # menus cap at 24


def test_border_follows_the_style(look):
    assert "border: 1px solid transparent;" in render(look, border="none")
    assert "border: 1px solid rgba(255, 255, 255, 0.10);" in render(look, border="hairline")
    accent = shell_theme._rgb_triplet(look.palette.accent)
    assert f"border: 1px solid rgba({accent}, 0.85);" in render(look, border="accent")


def test_the_bar_is_never_too_see_through_to_read(look):
    assert ", 0.5);" in render(look, "cards", fill=0.0)      # a cardless look still backs its bar
    assert ", 0.8);" in render(look, "cards", fill=0.8)
    assert ", 0.85);" in render(look, "solid", fill=0.3)


def test_text_and_bar_grow_with_the_scale(look):
    small, large = render(look, scale=1.0), render(look, scale=1.25)
    assert "font-size: 11.0pt" in small and "height: 44px" in small
    assert "font-size: 13.8pt" in large and "height: 55px" in large
    assert "height: 34px" in render(look, "solid", scale=1.0)
    assert "height: 34px" in render(look, "island", scale=1.0)   # 44 less its own margins


def test_the_menu_under_the_clock_takes_the_look(look):
    css = render(look, "island", radius=16, border="hairline")
    text = shell_theme._rgb_triplet(look.palette.text)
    accent = shell_theme._rgb_triplet(look.palette.accent)
    cards = css.split(".message, .events-button, .world-clocks-button, .weather-button {")[1].split("}")[0]
    assert f"background-color: rgba({text}, 0.06);" in cards and "border-radius: 12px;" in cards
    assert "border: 1px solid rgba(255, 255, 255, 0.10);" in cards
    assert f".datemenu-today-button .day-label {{ color: {look.palette.accent}; }}" in css
    assert f"box-shadow: inset 0 0 0 2px {look.palette.accent} !important;" in css   # not the stock orange
    assert f".calendar .calendar-day.calendar-weekend {{ color: rgba({text}, 0.6); }}" in css
    assert f".message-list {{ border-color: rgba({text}, 0.12); }}" in css
    assert f"background-color: rgba({accent}, 0.14);" in css
    for bar in shell_theme.STYLED:                           # every styled bar, not just this one
        assert ".message-list .message-list-placeholder" in render(look, bar)


def test_cards_in_a_menu_are_a_step_tighter_than_the_menu(look):
    assert "border-radius: 3px;" in render(look, radius=0)
    assert "border-radius: 16px;" in render(look, radius=40)


def test_ricers_own_cards_are_coloured_by_rules_that_outrank_the_extensions(look):
    css = render(look, gradient=True)
    fill = css.split("#calendarArea .ricer-fill {")[1].split("}")[0]
    assert f"background-gradient-start: {look.palette.accent};" in fill
    assert f"background-gradient-end: {look.palette.accent2};" in fill
    assert "#calendarArea .ricer-card {" in css and "#calendarArea .ricer-avatar {" in css
    assert f"#panel .clock-display .ricer-clock-glyph {{ color: {look.palette.accent}; }}" in css
    # every class the theme colours is one the extension really uses
    import re
    from ricer import shell_extension
    script = shell_extension.bundled()["extension.js"]
    for name in set(re.findall(r"\.(ricer-[a-z-]+)", css)):
        assert name in script, name
