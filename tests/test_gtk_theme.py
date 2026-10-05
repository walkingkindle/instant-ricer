import dataclasses
import re
from pathlib import Path

import pytest

from ricer import gtk_theme
from ricer.generator import generate
from ricer.gtk_theme import Recolour, Tone, recolour
from ricer.look import Dials
from ricer.palette import (contrast_ratio, hex_to_rgb, hsl, hue_distance, hue_of, luminance,
                           relative_luminance, saturation_of)

from conftest import STOCK_CSS

PURPLE = "#7764d8"                   # the stock accent the samples are built around
TONE = Tone(hue=200, strength=0.4, accent="#e6b87a")         # blue-grey surfaces, amber accent
GREYS = [(19, 19, 19), (34, 34, 34), (44, 44, 44), (61, 61, 61), (146, 146, 146), (247, 247, 247)]
YARU = Path("/usr/share/themes/Yaru-dark/gtk-3.0")


def as_hex(colour):
    return "#%02x%02x%02x" % tuple(colour)


def lum(colour):
    return luminance([channel / 255 for channel in colour])


@pytest.fixture
def look(wallpaper_set):
    return generate(Dials(7, 5, 5), wallpaper_set, 4)


# -- one colour -----------------------------------------------------------------------------------

@pytest.mark.parametrize("grey", GREYS)
def test_a_grey_takes_the_hue_and_keeps_its_luminance(grey):
    new = Recolour(TONE)(*grey)
    assert new is not None and new != grey
    # near white there are only a few steps of colour to choose from, so the hue is coarser
    assert hue_distance(hue_of(as_hex(new)), TONE.hue) < (6 if max(grey) < 200 else 25)
    assert abs(lum(new) - lum(grey)) < 0.006                 # within what 8-bit rounding allows


def test_dark_surfaces_take_more_of_the_tint_than_text_does():
    colour = Recolour(TONE)
    dark, light = colour(34, 34, 34), colour(247, 247, 247)
    assert saturation_of(as_hex(dark)) == pytest.approx(TONE.strength, abs=0.06)
    assert saturation_of(as_hex(light)) <= saturation_of(as_hex(dark)) * 0.5


def test_black_white_and_a_tone_without_strength_change_nothing():
    colour = Recolour(TONE)
    assert colour(0, 0, 0) is None and colour(255, 255, 255) is None
    assert colour.of(0, 0, 0) == (0, 0, 0)
    flat = Recolour(dataclasses.replace(TONE, strength=0.0))
    assert all(flat(*grey) is None for grey in GREYS)


def test_the_stock_accent_and_its_shades_turn_to_the_looks_accent():
    colour = Recolour(TONE, PURPLE)
    for shade in ((119, 100, 216), (83, 59, 206), (33, 23, 89), (213, 210, 245)):
        new = colour(*shade)
        assert hue_distance(hue_of(as_hex(new)), hue_of(TONE.accent)) < 8
        assert abs(lum(new) - lum(shade)) < 0.006         # white text on it reads as it did


def test_colours_that_mean_something_are_left_alone():
    colour = Recolour(TONE, PURPLE)
    for semantic in ((199, 22, 43), (249, 155, 17), (16, 155, 38), (51, 127, 220)):   # error .. link
        assert colour(*semantic) is None
    assert Recolour(TONE)(119, 100, 216) is None             # no known stock accent: nothing to swap


def test_accent_saturation_leans_toward_the_look_within_limits():
    def swapped(accent):
        return saturation_of(as_hex(Recolour(dataclasses.replace(TONE, accent=accent), PURPLE)(119, 100, 216)))

    stock = saturation_of(PURPLE)
    assert swapped(hsl(30, 0.2, 0.7)) == pytest.approx(stock * 0.6, abs=0.03)     # a pale look mutes it
    assert swapped(hsl(30, 0.99, 0.7)) == pytest.approx(stock * 1.2, abs=0.03)    # a vivid one lifts it
    assert swapped(hsl(30, 0.2, 0.7)) < swapped(hsl(30, 0.6, 0.7)) < swapped(hsl(30, 0.99, 0.7))


def test_text_is_as_readable_after_recolouring_as_before():
    colour = Recolour(TONE, PURPLE)
    pairs = [((247, 247, 247), (44, 44, 44)), ((146, 146, 146), (34, 34, 34)),
             ((255, 255, 255), (119, 100, 216)), ((247, 247, 247), (19, 19, 19))]
    for text, surface in pairs:
        before = contrast_ratio(as_hex(text), as_hex(surface))
        after = contrast_ratio(as_hex(colour.of(*text)), as_hex(colour.of(*surface)))
        assert after == pytest.approx(before, rel=0.06)


def test_window_tone_follows_the_cards(look):
    tone = gtk_theme.tone_for(look)
    assert tone.hue == pytest.approx(hue_of(look.palette.card)) and tone.accent == look.palette.accent
    low, high = gtk_theme.STRENGTH
    pale = dataclasses.replace(look, palette=dataclasses.replace(look.palette, card=hsl(40, 0.05, 0.08)))
    vivid = dataclasses.replace(look, palette=dataclasses.replace(look.palette, card=hsl(40, 0.9, 0.08)))
    assert gtk_theme.tone_for(pale).strength == low and gtk_theme.tone_for(vivid).strength == high
    assert low <= tone.strength <= high


# -- a whole stylesheet ---------------------------------------------------------------------------

def upper(red, green, blue):
    """A stand-in recolouring that is easy to spot: every colour becomes #010203."""
    return (1, 2, 3)


def test_only_colours_inside_declarations_are_touched():
    css = ('/* #fff stays in a comment */\n'
           'window#abc, #add-button, #fff > label { color: #fff; border-color: #AABBCC;'
           ' background: url("img#fff.png") rgba(10, 20, 30, 0.5); }\n'
           '.a::after { content: "#123456 rgb(1, 1, 1)"; color: rgb(9,9,9); }\n'
           '@define-color theme_bg_color #2c2c2c;\n'
           '#def { -gtk-icon-shadow: 0 1px alpha(#000, .2); }\n')
    assert recolour(css, upper) == (
        '/* #fff stays in a comment */\n'
        'window#abc, #add-button, #fff > label { color: #010203; border-color: #010203;'
        ' background: url("img#fff.png") rgba(1, 2, 3, 0.5); }\n'
        '.a::after { content: "#123456 rgb(1, 1, 1)"; color: rgb(1, 2, 3); }\n'
        '@define-color theme_bg_color #010203;\n'
        '#def { -gtk-icon-shadow: 0 1px alpha(#010203, .2); }\n')


def test_untouched_colours_leave_the_text_byte_for_byte():
    assert recolour(STOCK_CSS, lambda *rgb: None) == STOCK_CSS
    assert recolour("a { color: #FfF; b: rgb( 300 , 0 , 0 ); c: #12345; d: #abcd-ef; }", upper) == (
        "a { color: #010203; b: rgb( 300 , 0 , 0 ); c: #12345; d: #abcd-ef; }")


def test_nested_blocks_and_a_stray_brace_do_not_confuse_it():
    css = "@keyframes k { from { color: #111; } to { color: #222; } }\n#aaa { color: #333; } } #bbb { color: #444; }"
    assert recolour(css, upper) == ("@keyframes k { from { color: #010203; } to { color: #010203; } }\n"
                                    "#aaa { color: #010203; } } #bbb { color: #010203; }")


def test_stock_accent_is_read_from_the_stylesheet():
    assert gtk_theme.stock_accent(STOCK_CSS) == PURPLE
    assert gtk_theme.named_colour(STOCK_CSS, "theme_bg_color") == "#2c2c2c"
    assert gtk_theme.stock_accent("button { color: red; }") is None


# -- reading a stock theme ------------------------------------------------------------------------

def test_a_plain_theme_is_flattened_with_absolute_urls(tmp_path):
    folder = tmp_path / "themes/Plain/gtk-3.0"
    (folder / "parts").mkdir(parents=True)
    (folder / "gtk.css").write_text('@import url("parts/colors.css");\n@import "parts/more.css";\n'
                                    'a { background-image: url("assets/a.png"), url(/abs/b.png),'
                                    " url('data:image/png;base64,AAAA'); }\n")
    (folder / "parts/colors.css").write_text('@define-color bg #111;\nb { background: url("c.png"); }\n')
    (folder / "parts/more.css").write_text("c { color: #222; }\n")
    assert gtk_theme.stock_sheet(folder) == (
        f'@define-color bg #111;\nb {{ background: url("{folder.as_uri()}/parts/c.png"); }}\n\n'
        'c { color: #222; }\n\n'
        f'a {{ background-image: url("{folder.as_uri()}/assets/a.png"), url("file:///abs/b.png"),'
        ' url("data:image/png;base64,AAAA"); }\n')


def test_a_theme_kept_in_a_resource_bundle_is_read_from_it(tmp_path):
    folder = tmp_path / "themes/Bundled/gtk-3.0"
    folder.mkdir(parents=True)
    (folder / "gtk.css").write_text('@import url("resource:///com/example/Bundled/3.0/gtk.css");\n')
    asked = []

    def bundles(path):
        asked.append(path)
        return {"/com/example/Bundled/3.0/gtk.css": 'a { background: url("assets/a.png"); }\n'}.__getitem__

    assert gtk_theme.stock_sheet(folder, bundles) == (
        'a { background: url("resource:///com/example/Bundled/3.0/assets/a.png"); }\n\n')
    assert asked == [folder / "gtk.gresource"]               # opened once, and only when needed


def test_a_theme_that_cannot_be_read_gives_none(tmp_path):
    folder = tmp_path / "themes/Broken/gtk-3.0"
    assert gtk_theme.stock_sheet(folder) is None             # no such folder
    folder.mkdir(parents=True)
    (folder / "gtk.css").write_text('@import url("resource:///org/gtk/libgtk/theme/Adwaita/gtk.css");')
    assert gtk_theme.stock_sheet(folder) is None             # the bundle is inside GTK, not here
    (folder / "gtk.css").write_text('@import url("missing.css");')
    assert gtk_theme.stock_sheet(folder) is None
    assert gtk_theme.open_bundle(folder / "gtk.gresource") is None


def test_a_theme_that_imports_itself_ends(tmp_path):
    folder = tmp_path / "themes/Loop/gtk-3.0"
    folder.mkdir(parents=True)
    (folder / "gtk.css").write_text('@import url("gtk.css");\na { color: #111; }\n')
    sheet = gtk_theme.stock_sheet(folder)
    assert sheet.count("a { color: #111; }") == gtk_theme.MAX_IMPORTS + 1 and "@import" not in sheet


# -- what ricer writes ------------------------------------------------------------------------------

def test_render_recolours_the_stock_sheet_and_adds_the_looks_rules(look):
    css = gtk_theme.render(STOCK_CSS, look)
    colour = Recolour(gtk_theme.tone_for(look), PURPLE)
    assert f"background-color: {as_hex(colour.of(44, 44, 44))};" in css
    assert f"@define-color theme_selected_bg_color {as_hex(colour.of(119, 100, 216))};" in css
    assert "#f99b11" in css and 'url("assets/check.png")' in css          # the warning and the picture stay
    assert "window#abc headerbar" in css and "#2c2c2c is the window colour" in css
    assert "terminal-window" not in css                      # no see-through terminal was asked for


@pytest.mark.parametrize("border, outline", [("none", None), ("hairline", "rgba(255, 255, 255, 0.12)"),
                                             ("accent", "0.85)")])
def test_windows_are_outlined_the_way_cards_are(look, border, outline):
    styled = dataclasses.replace(look, style=dataclasses.replace(look.style, border=border))
    added = gtk_theme.render("", styled)
    if outline is None:
        assert "decoration" not in added
    else:
        focused, backdrop = [line for line in added.splitlines() if line.startswith("decoration")]
        assert focused.endswith(f"0 0 0 1px {outline}; }}") if border == "hairline" else outline in focused
        assert "decoration:backdrop" in backdrop
    accent = ", ".join(str(round(channel * 255)) for channel in hex_to_rgb(look.palette.accent))
    assert (f"rgba({accent}, 0.85)" in added) == (border == "accent")


def test_a_see_through_terminal_gets_a_frame_to_match(look):
    css = gtk_theme.render(STOCK_CSS, look, glass=0.8)
    surface = ", ".join(map(str, Recolour(gtk_theme.tone_for(look), PURPLE).of(44, 44, 44)))
    assert f"terminal-window headerbar, terminal-window headerbar:backdrop {{ background: rgba({surface}, 0.8);" in css
    assert f"terminal-window.background:backdrop {{ background-color: rgba({surface}, 0.8); }}" in css
    assert "terminal-window notebook > header:backdrop { background-color: transparent;" in css


def test_a_stylesheet_is_named_after_its_content(look):
    css = gtk_theme.render(STOCK_CSS, look)
    name = gtk_theme.sheet_name(css)
    assert re.fullmatch(r"[0-9a-f]{16}\.css", name) and name == gtk_theme.sheet_name(gtk_theme.render(STOCK_CSS, look))
    other = dataclasses.replace(look, palette=dataclasses.replace(look.palette, card=hsl(120, 0.4, 0.08)))
    assert gtk_theme.sheet_name(gtk_theme.render(STOCK_CSS, other)) != name


def test_the_theme_file_hands_over_to_the_stylesheet(tmp_path):
    sheet = tmp_path / "with space/abc.css"
    text = gtk_theme.stub(sheet)
    assert gtk_theme.is_ours(text) and f'@import url("{sheet.as_uri()}");' in text and "%20" in text
    assert not gtk_theme.is_ours('@import url("resource:///com/ubuntu/themes/Yaru/3.0/gtk.css");')


# -- libadwaita ---------------------------------------------------------------------------------------

def defined(block):
    return dict(re.findall(r"@define-color (\w+) (#[0-9a-f]{6});", block))


def test_libadwaita_gets_the_same_colours_by_name(look):
    colours = defined(gtk_theme.adwaita(look))
    tone = gtk_theme.tone_for(look)
    assert set(gtk_theme.ADWAITA_SURFACES) | {"accent_color", "accent_bg_color", "accent_fg_color"} == set(colours)
    for name, stock in gtk_theme.ADWAITA_SURFACES.items():
        assert hue_distance(hue_of(colours[name]), tone.hue) < 8
        assert relative_luminance(colours[name]) == pytest.approx(relative_luminance(stock), abs=0.006)
    for name in ("accent_color", "accent_bg_color"):
        assert hue_distance(hue_of(colours[name]), hue_of(tone.accent)) < 6
    assert colours["accent_fg_color"] == "#ffffff"
    # white on the accent, and the accent on a window, read as well as in stock libadwaita
    assert contrast_ratio("#ffffff", colours["accent_bg_color"]) == pytest.approx(
        contrast_ratio("#ffffff", gtk_theme.ADWAITA_ACCENT_BG), rel=0.05)
    assert contrast_ratio(colours["accent_color"], colours["window_bg_color"]) > 4.5


def test_the_block_lives_in_the_users_file_without_disturbing_it(look):
    block = gtk_theme.adwaita(look)
    mine = "window { border-radius: 0; }\n"
    assert gtk_theme.block_in(None) is None and gtk_theme.block_in(mine) is None
    merged = gtk_theme.with_block(mine, block)
    assert merged == block + mine and gtk_theme.block_in(merged) == block
    assert gtk_theme.with_block(None, block) == block

    other = gtk_theme.adwaita(dataclasses.replace(look, palette=dataclasses.replace(
        look.palette, card=hsl(120, 0.4, 0.08))))
    replaced = gtk_theme.with_block(merged, other)
    assert replaced == other + mine and replaced.count(gtk_theme.BLOCK_START) == 1
    assert gtk_theme.without_block(replaced) == mine
    assert gtk_theme.without_block("a {}\n" + block + mine) == "a {}\n" + mine      # wherever it sits
    assert gtk_theme.without_block(mine) == mine


# -- against the real thing -----------------------------------------------------------------------

def skeleton(css):
    """A stylesheet with its declarations and colour definitions emptied: what must not change."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)           # the real theme has braces in comments
    css = re.sub(r"@define-color[^;]*;", "", css)
    for _ in range(3):
        css = re.sub(r"\{[^{}]*\}", "{}", css)
    return css


@pytest.mark.skipif(not (YARU / "gtk.gresource").is_file(), reason="needs the Yaru theme")
def test_the_real_yaru_theme_survives_recolouring(look):
    stock = gtk_theme.stock_sheet(YARU)
    assert stock and "@import" not in stock and gtk_theme.stock_accent(stock)
    assert all(re.match(r"[a-z]+:", url) for _, url in re.findall(r'url\(\s*(["\']?)(.*?)\1\s*\)', stock))
    css = gtk_theme.render(stock, look, glass=0.8)
    assert skeleton(css[:css.index("/* ricer:")]).rstrip() == skeleton(stock).rstrip()
    assert css.count("#2c2c2c") == 0 and stock.count("#2c2c2c") > 50
    comments = re.findall(r"/\*.*?\*/", stock, flags=re.S)
    assert len(comments) > 100 and all(comment in css for comment in comments)   # untouched, colours and all

    gi = pytest.importorskip("gi")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
    errors = []
    provider = Gtk.CssProvider()
    provider.connect("parsing-error", lambda _provider, section, error: errors.append(
        (section.get_start_line(), error.message)))
    provider.load_from_data(css.encode())
    assert errors == []
