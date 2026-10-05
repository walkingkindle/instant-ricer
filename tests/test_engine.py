import dataclasses
import json
import os
from pathlib import Path

import pytest

from ricer import engine, gtk_theme
from ricer.backends import FakeBackend, gv, gv_uint
from ricer.capabilities import MEDIA_CONTROLS_UUID, VITALS_UUID
from ricer.engine import ApplyError, Engine, build_plan, sibling_theme
from ricer.generator import generate
from ricer.look import Bar, Dials, Dock, WidgetSpec
from ricer.palette import hsl, terminal_transparency

from conftest import PROFILE

TERMINAL = f"/org/gnome/terminal/legacy/profiles:/:{PROFILE}/"
HOME_ICON = engine.DESKTOP_ICONS + "show-home"
DRIVE_ICONS = engine.DESKTOP_ICONS + "show-volumes"
BAR_EXTENSIONS = {VITALS_UUID: False, MEDIA_CONTROLS_UUID: False}


class FakeDaemon:
    def __init__(self):
        self.syncs = 0

    def sync(self):
        self.syncs += 1


@pytest.fixture
def look(wallpaper_set):
    """A look with widgets, a styled bar, and both bar extensions in use."""
    base = generate(Dials(8, 6, 7), wallpaper_set, 21)
    assert base.widgets
    return dataclasses.replace(
        base, icon_style="fancy", blur=True,
        bar=Bar(style="cards", stats=("cpu", "ram", "temp"), stats_side="right", media=True,
                media_side="left"),
        dock=Dock(position="BOTTOM", autohide=True, floating=True, opacity=0.4, icon_size=46,
                  indicator="DASHES", tint=True))


@pytest.fixture
def plain(look):
    """A look with nothing on the desktop, the stock bar and nothing in it."""
    return dataclasses.replace(look, widgets=(), desktop_icons=True, bar=Bar(style="stock"), blur=False,
                               icon_style="stock", dock=dataclasses.replace(look.dock, tint=False))


@pytest.fixture
def backend():
    return FakeBackend(extensions=dict(BAR_EXTENSIONS))


@pytest.mark.parametrize("value, text", [(True, "true"), (False, "false"), (44, "44"), (0.3, "0.3"),
                                         ("Yaru", "'Yaru'"), ("it's", "'it\\'s'"),
                                         (["#fff", "#000"], "['#fff', '#000']")])
def test_gv(value, text):
    assert gv(value) == text


def test_unsigned_settings_are_written_as_unsigned():
    assert gv_uint(200) == "uint32 200"
    with pytest.raises(TypeError):
        gv(object())


# -- the plan -----------------------------------------------------------------------------------

def test_plan_on_a_full_desktop_covers_everything(look, full_caps, paths):
    plan = build_plan(look, full_caps, paths)
    s = plan.settings
    assert s[engine.BACKGROUND + "picture-uri"] == gv("file://" + look.wallpaper)
    assert s[engine.SCREENSAVER + "picture-uri"] == s[engine.BACKGROUND + "picture-uri-dark"]
    assert s[engine.INTERFACE + "color-scheme"] == "'prefer-dark'"
    assert s[engine.USER_THEME_NAME] == "'Ricer'"
    assert "@import" in plan.files[paths.shell_theme_file]
    assert s[TERMINAL + "background-color"] == gv(look.terminal["background"])
    assert s[TERMINAL + "palette"] == gv(look.terminal["palette"])
    assert engine.INTERFACE + "accent-color" not in s        # this desktop has no such setting
    assert "ricer.widgets.daemon" in plan.files[paths.autostart_file]
    assert plan.notices == [] and plan.restore == []


def test_plan_dock_settings_follow_the_look(look, full_caps, paths):
    s = build_plan(look, full_caps, paths).settings
    dock = engine.DOCK
    assert (s[dock + "dock-position"], s[dock + "dash-max-icon-size"]) == ("'BOTTOM'", "46")
    assert s[dock + "dock-fixed"] == "false" and s[dock + "extend-height"] == "false"
    assert s[dock + "autohide"] == s[dock + "intellihide"] == "true"
    assert s[dock + "running-indicator-style"] == "'DASHES'" and s[dock + "background-opacity"] == "0.4"
    assert s[dock + "custom-background-color"] == "true"
    assert s[dock + "background-color"] == gv(look.palette.card)

    panel = dataclasses.replace(look, dock=Dock(position="LEFT", autohide=False, floating=False))
    s = build_plan(panel, full_caps, paths).settings
    assert (s[dock + "dock-position"], s[dock + "dock-fixed"], s[dock + "extend-height"]) == (
        "'LEFT'", "true", "true")
    assert s[dock + "custom-background-color"] == "false"


def test_plan_puts_widgets_in_the_bar_through_the_two_extensions(look, full_caps, paths):
    plan = build_plan(look, full_caps, paths)
    s = plan.settings
    assert plan.extensions == {VITALS_UUID: True, MEDIA_CONTROLS_UUID: True}
    assert s[engine.VITALS + "hot-sensors"] == "['_processor_usage_', '_memory_usage_', '__temperature_avg__']"
    assert s[engine.VITALS + "position-in-panel"] == "2" and s[engine.VITALS + "show-battery"] == "false"
    assert s[engine.MEDIA + "extension-position"] == "'Left'"
    assert s[engine.MEDIA + "extension-index"] == "uint32 1"         # after the workspace indicator
    assert s[engine.MEDIA + "label-width"] == f"uint32 {round(200 * look.style.scale)}"
    assert s[engine.MEDIA + "show-control-icons-seek-forward"] == "false"

    everything = dataclasses.replace(look, bar=Bar(stats=("cpu", "ram", "temp", "net", "battery"),
                                                   stats_side="left", media=True, media_side="center"))
    s = build_plan(everything, full_caps, paths).settings
    assert "'__network-rx_max__', '_battery_percentage_'" in s[engine.VITALS + "hot-sensors"]
    assert s[engine.VITALS + "position-in-panel"] == "0" and s[engine.VITALS + "show-battery"] == "true"
    assert s[engine.MEDIA + "extension-position"] == "'Center'"
    on_the_right = dataclasses.replace(look, bar=Bar(media=True, media_side="right"))
    assert build_plan(on_the_right, full_caps, paths).settings[engine.MEDIA + "extension-index"] == "uint32 0"


def test_a_look_with_an_empty_bar_switches_the_extensions_off(plain, full_caps, paths):
    plan = build_plan(plain, full_caps, paths)
    assert plan.extensions == {VITALS_UUID: False, MEDIA_CONTROLS_UUID: False}
    assert not any(path.startswith((engine.VITALS, engine.MEDIA)) for path in plan.settings)
    assert plan.settings[engine.USER_THEME_NAME] == "''" and paths.shell_theme_file not in plan.files


def test_plan_blur_leaves_floating_bars_and_tinted_docks_alone(look, plain, full_caps, paths):
    s = build_plan(look, full_caps, paths).settings
    assert s[engine.BLUR + "overview/blur"] == s[engine.BLUR + "dash-to-dock/blur"] == "true"
    assert s[engine.BLUR + "panel/blur"] == "false"                      # the bar floats in pieces
    assert s[engine.BLUR + "dash-to-dock/override-background"] == "false"  # the dock keeps its tint
    stock_blurred = dataclasses.replace(plain, blur=True)
    s = build_plan(stock_blurred, full_caps, paths).settings
    assert s[engine.BLUR + "panel/blur"] == "true" and s[engine.BLUR + "dash-to-dock/override-background"] == "true"
    assert build_plan(plain, full_caps, paths).settings[engine.BLUR + "panel/blur"] == "false"


def test_plan_picks_icons_and_cursor_by_icon_style(look, full_caps, paths):
    fancy = build_plan(look, full_caps, paths).settings
    assert fancy[engine.INTERFACE + "icon-theme"] == "'Papirus-Dark'"
    assert fancy[engine.INTERFACE + "cursor-theme"] == "'Bibata-Modern-Ice'"
    stock = build_plan(dataclasses.replace(look, icon_style="stock", gtk_accent="blue"), full_caps, paths).settings
    assert stock[engine.INTERFACE + "icon-theme"] == "'Yaru-blue-dark'"
    assert stock[engine.INTERFACE + "cursor-theme"] == "'Yaru'"
    no_fancy = dataclasses.replace(full_caps, icon_themes=frozenset({"Yaru-dark", "Adwaita"}))
    fallback = build_plan(look, no_fancy, paths).settings
    assert fallback[engine.INTERFACE + "icon-theme"] == "'Yaru-dark'"
    assert fallback[engine.INTERFACE + "cursor-theme"] == "'Adwaita'"


def test_plan_picks_the_accent_matched_theme_and_falls_back(look, full_caps, paths):
    blue = build_plan(dataclasses.replace(look, gtk_accent="blue"), full_caps, paths)
    assert blue.settings[engine.INTERFACE + "gtk-theme"] == "'Yaru-blue-dark'"
    assert "Yaru-blue-dark/gnome-shell.css" in blue.files[paths.shell_theme_file]
    olive = build_plan(dataclasses.replace(look, gtk_accent="olive"), full_caps, paths)   # not installed
    assert olive.settings[engine.INTERFACE + "gtk-theme"] == "'Yaru-dark'"
    assert "Yaru-dark/gnome-shell.css" in olive.files[paths.shell_theme_file]


def test_the_widget_file_carries_style_fonts_and_dock_clearance(look, full_caps, paths):
    side_dock = dataclasses.replace(look, dock=Dock(position="LEFT", autohide=True, icon_size=48),
                                    style=dataclasses.replace(look.style, voice="serif"))
    config = json.loads(build_plan(side_dock, full_caps, paths).files[paths.widgets_file])
    assert config["font"] == "Ubuntu Sans" and config["display_font"] == "Noto Serif Display"
    assert config["style"] == dataclasses.asdict(side_dock.style)
    assert config["palette"] == dataclasses.asdict(look.palette) and config["clock_24h"] is True
    assert config["insets"] == [84, 0, 0]
    assert [w["type"] for w in config["widgets"]] == [w.type for w in look.widgets]
    assert all({"type", "design", "anchor", "options"} <= set(w) for w in config["widgets"])


def test_desktop_icons_hide_under_widgets_and_come_back_as_they_were(look, plain, full_caps, paths):
    with_widgets = build_plan(look, full_caps, paths)
    assert with_widgets.settings[HOME_ICON] == with_widgets.settings[DRIVE_ICONS] == "false"
    without = build_plan(plain, full_caps, paths)
    assert HOME_ICON not in without.settings and without.restore == [HOME_ICON, DRIVE_ICONS]

    # the user had drive icons on (set) and the home icon at its default (unset)
    backend = FakeBackend({DRIVE_ICONS: "true", "/org/unrelated": "1"}, extensions=dict(BAR_EXTENSIONS))
    eng = Engine(backend, paths)
    eng.apply(plain, full_caps)
    assert backend.values[DRIVE_ICONS] == "true" and HOME_ICON not in backend.values   # never touched
    eng.apply(look, full_caps)
    assert backend.values[HOME_ICON] == backend.values[DRIVE_ICONS] == "false"
    eng.apply(plain, full_caps)
    assert backend.values[DRIVE_ICONS] == "true" and HOME_ICON not in backend.values   # as they were


def test_plan_on_a_bare_desktop_skips_and_says_why(look, bare_caps, paths):
    plan = build_plan(look, bare_caps, paths)
    s = plan.settings
    assert engine.BACKGROUND + "picture-uri" in s
    assert s[engine.INTERFACE + "accent-color"] in {gv(n) for n in ("orange", "pink", "purple", "blue",
                                                                    "red", "green", "teal")}
    assert engine.INTERFACE + "gtk-theme" not in s
    owned_elsewhere = (engine.DOCK, engine.BLUR, engine.VITALS, engine.MEDIA, engine.DESKTOP_ICONS,
                       "/org/gnome/terminal")
    assert not any(path.startswith(owned_elsewhere) for path in s)
    assert engine.USER_THEME_NAME not in s and paths.shell_theme_file not in plan.files
    assert plan.extensions == {} and plan.restore == []
    assert json.loads(plan.files[paths.widgets_file])["widgets"] == []
    assert plan.files[paths.autostart_file] is None
    text = " ".join(plan.notices)
    for word in ("Dock", "User Themes", "Vitals", "Media Controls", "Blur my Shell", "X11"):
        assert word in text


# -- apply and revert ---------------------------------------------------------------------------

def test_apply_writes_settings_files_extensions_and_state(look, full_caps, paths, backend):
    daemon = FakeDaemon()
    eng = Engine(backend, paths, daemon)
    result = eng.apply(look, full_caps)
    plan = build_plan(look, full_caps, paths)
    assert backend.values == plan.settings
    assert backend.extensions == {VITALS_UUID: True, MEDIA_CONTROLS_UUID: True}
    assert result.changed == (len(plan.settings) + len(plan.files) + len(plan.links)
                              + len(plan.blocks) + 2)
    assert paths.shell_theme_file.read_text() == plan.files[paths.shell_theme_file]
    assert paths.autostart_file.is_file() and daemon.syncs == 1
    assert eng.current_look() == look and len(eng.history()) == 1


def test_extensions_are_switched_on_only_after_they_are_configured(look, full_caps, paths, backend):
    Engine(backend, paths).apply(look, full_caps)
    order = backend.writes
    assert order.index(engine.VITALS + "hot-sensors") < order.index(VITALS_UUID)
    assert order.index(engine.MEDIA + "extension-position") < order.index(MEDIA_CONTROLS_UUID)


def test_vitals_is_restarted_when_its_sensor_list_changes_while_it_stays_on(look, full_caps, paths, backend):
    eng = Engine(backend, paths)
    eng.apply(look, full_caps)
    assert backend.writes.count(VITALS_UUID) == 1            # switched on once; no restart needed

    backend.writes.clear()
    more = dataclasses.replace(look, bar=dataclasses.replace(look.bar, stats=("cpu", "ram", "temp", "net")))
    eng.apply(more, full_caps)
    assert backend.writes.count(VITALS_UUID) == 2 and backend.extensions[VITALS_UUID] is True
    assert backend.writes.index(engine.VITALS + "hot-sensors") < backend.writes.index(VITALS_UUID)

    backend.writes.clear()                                   # a change it picks up by itself: no restart
    eng.apply(dataclasses.replace(more, bar=dataclasses.replace(more.bar, stats_side="left")), full_caps)
    assert VITALS_UUID not in backend.writes

    eng.apply(look, full_caps)                               # back to three sensors
    backend.writes.clear()
    eng.revert()                                             # undoing that restores four: restart again
    assert backend.writes.count(VITALS_UUID) == 2 and backend.extensions[VITALS_UUID] is True
    assert "'__network-rx_max__'" in backend.values[engine.VITALS + "hot-sensors"]


def test_applying_the_same_look_twice_changes_nothing(look, full_caps, paths, backend):
    eng = Engine(backend, paths)
    eng.apply(look, full_caps)
    backend.writes.clear()
    assert eng.apply(look, full_caps).changed == 0
    assert backend.writes == [] and len(eng.history()) == 1
    assert backend.terminal_nudges == 1 and backend.theme_reloads == []   # nobody is told twice
    assert eng.revert() > 0                                  # the first apply can still be undone


def test_revert_restores_the_exact_prior_state(look, full_caps, paths):
    before = {engine.INTERFACE + "gtk-theme": "'Yaru'", engine.DOCK + "dock-position": "'LEFT'",
              "/org/unrelated/key": "'untouched'"}
    backend = FakeBackend(before, extensions={VITALS_UUID: False, MEDIA_CONTROLS_UUID: True})
    paths.widgets_file.parent.mkdir(parents=True)
    paths.widgets_file.write_text("old config")
    eng = Engine(backend, paths)
    eng.apply(look, full_caps)
    assert backend.values != before and backend.extensions[VITALS_UUID] is True

    assert eng.revert() > 0
    assert backend.values == before                          # keys that were unset are unset again
    assert backend.extensions == {VITALS_UUID: False, MEDIA_CONTROLS_UUID: True}
    assert paths.widgets_file.read_text() == "old config"
    assert not paths.shell_theme_file.exists() and not paths.autostart_file.exists()
    assert list(paths.themes_dir.iterdir()) == [] and not paths.sheets_dir.parent.exists()
    assert not paths.gtk4_css_file.exists()
    assert eng.current_look() is None and eng.revert() == 0


def test_revert_undoes_one_look_and_all_undoes_everything(look, plain, full_caps, paths):
    before = {engine.DOCK + "dash-max-icon-size": "48"}
    backend = FakeBackend(before, extensions={VITALS_UUID: True, MEDIA_CONTROLS_UUID: False})
    eng = Engine(backend, paths)
    eng.apply(look, full_caps)
    after_first, extensions_first = dict(backend.values), dict(backend.extensions)
    eng.apply(plain, full_caps)
    assert backend.extensions == {VITALS_UUID: False, MEDIA_CONTROLS_UUID: False}

    eng.revert()
    assert backend.values == after_first and backend.extensions == extensions_first
    assert eng.current_look() == look                        # the earlier look is current again

    eng.apply(plain, full_caps)
    assert eng.revert(everything=True) > 0
    assert backend.values == before
    assert backend.extensions == {VITALS_UUID: True, MEDIA_CONTROLS_UUID: False}
    assert not paths.widgets_file.exists() and eng.history() == []
    assert eng.revert(everything=True) == 0


@pytest.mark.parametrize("failing", [engine.DOCK + "background-opacity", MEDIA_CONTROLS_UUID])
def test_a_failure_part_way_rolls_everything_back(look, full_caps, paths, failing):
    before = {engine.INTERFACE + "gtk-theme": "'Yaru'"}
    backend = FakeBackend(before, extensions=dict(BAR_EXTENSIONS))
    backend.fail_on = {failing}
    eng = Engine(backend, paths)
    with pytest.raises(ApplyError):
        eng.apply(look, full_caps)
    assert backend.values == before and backend.extensions == BAR_EXTENSIONS
    assert not paths.shell_theme_file.exists() and not paths.widgets_file.exists()
    assert list(paths.themes_dir.iterdir()) == [] and not paths.sheets_dir.parent.exists()
    assert not paths.gtk4_css_file.exists()
    assert eng.load_state() == {} and eng.revert() == 0


def test_restyling_the_bar_reloads_the_shell_theme(look, full_caps, paths, backend):
    eng = Engine(backend, paths)
    eng.apply(look, full_caps)
    assert backend.reloads == 0                              # naming the theme loads it by itself
    eng.apply(dataclasses.replace(look, bar=dataclasses.replace(look.bar, style="island")), full_caps)
    assert backend.reloads == 1                              # same theme name, new stylesheet


def test_engine_only_touches_keys_it_owns(look, full_caps, paths, backend):
    Engine(backend, paths).apply(look, full_caps)
    owned = ("/org/gnome/desktop/background/", "/org/gnome/desktop/screensaver/picture-uri",
             "/org/gnome/desktop/interface/", engine.DOCK, engine.USER_THEME_NAME, engine.BLUR,
             engine.VITALS, engine.MEDIA, engine.DESKTOP_ICONS, "/org/gnome/terminal/legacy/profiles:/")
    assert all(path.startswith(owned) for path in backend.values)


def test_history_remembers_recent_looks_newest_first(wallpaper_set, full_caps, paths, backend):
    eng = Engine(backend, paths)
    looks = [generate(Dials(7, 5, 5), wallpaper_set, seed) for seed in range(1, 10)]
    for one in looks:
        eng.apply(one, full_caps)
    history = eng.history()
    assert len(history) == 6 and history[0]["wallpaper"] == looks[-1].wallpaper
    assert set(history[0]) == {"wallpaper", "widgets", "zones", "bar", "layout", "voice"}


def test_state_saved_by_version_one_does_not_break_anything(look, full_caps, paths, backend):
    paths.state_file.parent.mkdir(parents=True)
    paths.state_file.write_text(json.dumps({
        "look": {"dials": {"cool": 5, "ease": 5, "warmth": 5}, "seed": 0, "bar_style": "cards"},
        "snapshot": {"settings": {engine.DOCK + "dock-position": "'LEFT'"}, "files": {}, "look": None},
        "original": {"settings": {engine.DOCK + "dock-position": "'LEFT'"}, "files": {}}}))
    eng = Engine(backend, paths)
    assert eng.current_look() is None and eng.history() == []
    eng.apply(look, full_caps)
    assert eng.current_look() == look
    eng.revert(everything=True)
    assert backend.values == {engine.DOCK + "dock-position": "'LEFT'"}   # the oldest record wins


def test_a_widget_that_cannot_show_on_wayland_leaves_icons_and_autostart_alone(look, full_caps, paths):
    wayland = dataclasses.replace(full_caps, session="wayland")
    plan = build_plan(look, wayland, paths)
    assert plan.files[paths.autostart_file] is None and HOME_ICON not in plan.settings
    assert any("X11" in notice for notice in plan.notices)
    assert plan.extensions == {VITALS_UUID: True, MEDIA_CONTROLS_UUID: True}   # bar widgets still work


def test_widget_specs_reach_the_file_unchanged(look, full_caps, paths):
    odd = dataclasses.replace(look, widgets=(
        WidgetSpec("ornament", "sigil", "bottom-left", {"size": 200, "seed": 7, "fill": 0.0, "align": "left"}),))
    config = json.loads(build_plan(odd, full_caps, paths).files[paths.widgets_file])
    assert config["widgets"] == [{"type": "ornament", "design": "sigil", "anchor": "bottom-left",
                                  "options": {"size": 200, "seed": 7, "fill": 0.0, "align": "left"}}]


def test_the_default_look_is_saved_whole_and_outlasts_other_looks(look, plain, full_caps, paths, backend):
    eng = Engine(backend, paths)
    assert eng.save_default() is None and eng.default_look() is None     # nothing applied yet
    eng.apply(look, full_caps)
    assert eng.save_default() == look and eng.default_look() == look
    assert json.loads(paths.default_file.read_text())["seed"] == look.seed
    eng.apply(plain, full_caps)
    assert eng.default_look() == look                        # later looks do not touch it
    eng.revert(everything=True)
    assert eng.default_look() == look                        # nor does undoing everything
    assert eng.clear_default() is True and eng.default_look() is None
    assert eng.clear_default() is False


def test_an_unreadable_default_counts_as_none(paths, backend):
    paths.default_file.parent.mkdir(parents=True)
    paths.default_file.write_text("{ not json")
    assert Engine(backend, paths).default_look() is None
    paths.default_file.write_text(json.dumps({"dials": {"cool": 5}, "bar_style": "cards"}))
    assert Engine(backend, paths).default_look() is None


# -- window colours -----------------------------------------------------------------------------

def recoloured(look, hue):
    """The same look with cards of another colour: new window colours, same app theme."""
    return dataclasses.replace(look, palette=dataclasses.replace(look.palette, card=hsl(hue, 0.4, 0.08)))


def shadow(paths, theme):
    """The stylesheets and links a recoloured theme occupies in the user's themes folder."""
    folder = paths.themes_dir / theme / "gtk-3.0"
    plain = paths.themes_dir / theme[:-len("-dark")] / "gtk-3.0"
    return ([folder / "gtk.css", folder / "gtk-dark.css", plain / "gtk-dark.css"],
            [folder / "gtk.gresource", plain / "gtk.gresource"])


def theme_of(plan):
    return plan.settings[engine.GTK_THEME].strip("'")


def imported(stub):
    """The generated stylesheet a theme file hands over to."""
    return Path(stub.read_text().split('url("file://')[1].split('"')[0])


def test_plan_recolours_the_app_theme_under_its_own_name(look, full_caps, paths, stock_themes):
    plan = build_plan(look, full_caps, paths)
    theme = theme_of(plan)
    stubs, links = shadow(paths, theme)
    (sheet, css), = plan.sheets.items()
    stock = gtk_theme.stock_sheet(Path(stock_themes[theme]))
    opacity = 1 - look.terminal["transparency"] / 100
    assert css == gtk_theme.render(stock, look, opacity) and f", {round(opacity, 2)});" in css
    assert sheet == paths.sheets_dir / gtk_theme.sheet_name(css)
    assert all(plan.files[stub] == gtk_theme.stub(sheet) for stub in stubs)
    # both folders borrow the pictures of the theme the stylesheet came from
    assert plan.links == {link: stock_themes[theme] + "/gtk.gresource" for link in links}
    assert plan.blocks == {paths.gtk4_css_file: gtk_theme.adwaita(look)}


def test_the_terminal_is_as_see_through_as_the_look_says(look, full_caps, paths):
    key = TERMINAL + "background-transparency-percent"
    assert build_plan(look, full_caps, paths).settings[key] == str(look.terminal["transparency"])

    colours_only = {name: value for name, value in look.terminal.items() if name != "transparency"}
    older = dataclasses.replace(look, terminal=colours_only)             # saved before 0.3
    assert build_plan(older, full_caps, paths).settings[key] == str(terminal_transparency(look.style.fill))

    opaque = build_plan(look, dataclasses.replace(full_caps, terminal_glass=False), paths)
    assert not any(path.startswith(TERMINAL) and "transparen" in path for path in opaque.settings)
    assert opaque.settings[TERMINAL + "background-color"] == gv(look.terminal["background"])
    assert "terminal-window" not in next(iter(opaque.sheets.values()))


def test_apply_installs_window_colours_and_tells_running_apps(look, full_caps, paths, backend, stock_themes):
    eng = Engine(backend, paths)
    eng.apply(look, full_caps)
    plan = build_plan(look, full_caps, paths)
    theme = theme_of(plan)
    stubs, links = shadow(paths, theme)
    (sheet, css), = plan.sheets.items()
    assert sheet.read_text() == css and [imported(stub) for stub in stubs] == [sheet] * 3
    assert all(os.readlink(link) == stock_themes[theme] + "/gtk.gresource" for link in links)
    assert paths.gtk4_css_file.read_text() == gtk_theme.adwaita(look)
    # the new theme name makes GTK 3 apps load it; only the terminal has to be told
    assert backend.theme_reloads == [] and backend.terminal_nudges == 1


def test_new_colours_under_the_same_theme_name_make_apps_reload(look, full_caps, paths, backend):
    eng = Engine(backend, paths)
    eng.apply(look, full_caps)
    stubs, _ = shadow(paths, theme_of(build_plan(look, full_caps, paths)))
    first = imported(stubs[0])

    eng.apply(recoloured(look, 120), full_caps)
    second = imported(stubs[0])
    assert backend.theme_reloads == [sibling_theme(backend.values[engine.GTK_THEME].strip("'"))]
    assert backend.terminal_nudges == 2
    assert second != first and first.exists()                # revert still needs the first

    eng.apply(recoloured(look, 300), full_caps)
    assert not first.exists() and second.exists() and imported(stubs[0]).exists()
    assert len(backend.theme_reloads) == 2


def test_a_look_with_another_accent_moves_the_recoloured_theme(look, full_caps, paths, backend):
    eng = Engine(backend, paths)
    eng.apply(dataclasses.replace(look, gtk_accent="blue"), full_caps)
    assert sorted(p.name for p in paths.themes_dir.iterdir()) == ["Ricer", "Yaru-blue", "Yaru-blue-dark"]
    eng.apply(dataclasses.replace(look, gtk_accent="purple"), full_caps)
    assert sorted(p.name for p in paths.themes_dir.iterdir()) == ["Ricer", "Yaru-purple", "Yaru-purple-dark"]
    assert backend.theme_reloads == [] and backend.terminal_nudges == 2     # the name change does it


def test_revert_brings_back_the_window_colours_that_were_there(look, full_caps, paths, backend):
    eng = Engine(backend, paths)
    eng.apply(look, full_caps)
    stubs, links = shadow(paths, theme_of(build_plan(look, full_caps, paths)))
    first = stubs[0].read_text()
    eng.apply(recoloured(look, 120), full_caps)
    assert stubs[0].read_text() != first

    eng.revert()
    assert [stub.read_text() for stub in stubs] == [first] * 3 and imported(stubs[0]).exists()
    assert len(list(paths.sheets_dir.iterdir())) == 1        # the undone look's stylesheet is gone
    assert backend.terminal_nudges == 3 and len(backend.theme_reloads) == 2

    eng.apply(recoloured(look, 120), full_caps)
    eng.revert(everything=True)
    assert not any(path.exists() or path.is_symlink() for path in stubs + links)
    assert list(paths.themes_dir.iterdir()) == [] and not paths.sheets_dir.parent.exists()
    assert not paths.gtk4_css_file.exists()


def test_the_users_own_gtk4_stylesheet_keeps_everything_but_ricers_block(look, full_caps, paths, backend):
    mine = "window { border-radius: 0; }\n"
    paths.gtk4_css_file.parent.mkdir(parents=True)
    paths.gtk4_css_file.write_text(mine)
    eng = Engine(backend, paths)
    eng.apply(look, full_caps)
    assert paths.gtk4_css_file.read_text() == gtk_theme.adwaita(look) + mine

    later = "button { margin: 0; }\n"                        # written between the look and its undoing
    paths.gtk4_css_file.write_text(paths.gtk4_css_file.read_text() + later)
    eng.apply(recoloured(look, 120), full_caps)
    assert paths.gtk4_css_file.read_text() == gtk_theme.adwaita(recoloured(look, 120)) + mine + later
    eng.revert()
    assert paths.gtk4_css_file.read_text() == gtk_theme.adwaita(look) + mine + later
    eng.revert(everything=True)
    assert paths.gtk4_css_file.read_text() == mine + later


@pytest.mark.parametrize("theirs", ["gtk.css", "gtk.gresource"])
def test_a_theme_copy_of_the_users_own_is_left_alone(look, full_caps, paths, backend, theirs):
    theme = theme_of(build_plan(look, full_caps, paths))
    own = paths.themes_dir / theme / "gtk-3.0" / theirs
    own.parent.mkdir(parents=True)
    own.write_text("headerbar { background: hotpink; }")
    result = Engine(backend, paths).apply(look, full_caps)
    assert any(theme in notice and "leaves alone" in notice for notice in result.notices)
    assert own.read_text() == "headerbar { background: hotpink; }"
    assert sorted(p.name for p in own.parent.iterdir()) == [theirs] and not paths.sheets_dir.exists()
    assert paths.gtk4_css_file.read_text() == gtk_theme.adwaita(look)    # libadwaita apps still follow


def test_without_a_stock_theme_to_recolour_old_window_colours_go(look, full_caps, bare_caps, paths, backend):
    eng = Engine(backend, paths)
    eng.apply(look, full_caps)
    stubs, links = shadow(paths, theme_of(build_plan(look, full_caps, paths)))
    result = eng.apply(look, dataclasses.replace(full_caps, gtk3_themes={}))
    assert any("Yaru" in notice for notice in result.notices)
    assert not any(path.exists() or path.is_symlink() for path in stubs + links)
    assert backend.theme_reloads and backend.terminal_nudges == 2        # running apps drop them too
    assert any("recolour" in notice for notice in build_plan(look, bare_caps, paths).notices)
    assert build_plan(look, bare_caps, paths).blocks                     # by name, they still can


@pytest.mark.parametrize("theme, sibling", [
    ("Yaru-dark", "Yaru-red-dark"), ("Yaru-red-dark", "Yaru-dark"), ("Yaru-purple-dark", "Yaru-blue-dark"),
    ("Yaru-viridian-dark", "Yaru-prussiangreen-dark"), ("Yaru-olive-dark", "Yaru-dark"),
    ("Adwaita-dark", None), ("Yaru", None), ("Yaru-bogus-dark", None), ("", None)])
def test_a_theme_is_reloaded_through_its_nearest_sibling(theme, sibling):
    assert sibling_theme(theme) == sibling
