import dataclasses
import json

import pytest

from ricer import engine
from ricer.backends import FakeBackend, gv, gv_uint
from ricer.capabilities import MEDIA_CONTROLS_UUID, VITALS_UUID
from ricer.engine import ApplyError, Engine, build_plan
from ricer.generator import generate
from ricer.look import Bar, Dials, Dock, WidgetSpec

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
    assert s[engine.MEDIA + "extension-index"] == "uint32 0"
    assert s[engine.MEDIA + "label-width"] == f"uint32 {round(200 * look.style.scale)}"
    assert s[engine.MEDIA + "show-control-icons-seek-forward"] == "false"

    everything = dataclasses.replace(look, bar=Bar(stats=("cpu", "ram", "temp", "net", "battery"),
                                                   stats_side="left", media=True, media_side="center"))
    s = build_plan(everything, full_caps, paths).settings
    assert "'__network-rx_max__', '_battery_percentage_'" in s[engine.VITALS + "hot-sensors"]
    assert s[engine.VITALS + "position-in-panel"] == "0" and s[engine.VITALS + "show-battery"] == "true"
    assert s[engine.MEDIA + "extension-position"] == "'Center'"


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
    assert result.changed == len(plan.settings) + len(plan.files) + 2
    assert paths.shell_theme_file.read_text() == plan.files[paths.shell_theme_file]
    assert paths.autostart_file.is_file() and daemon.syncs == 1
    assert eng.current_look() == look and len(eng.history()) == 1


def test_extensions_are_switched_on_only_after_they_are_configured(look, full_caps, paths, backend):
    Engine(backend, paths).apply(look, full_caps)
    order = backend.writes
    assert order.index(engine.VITALS + "hot-sensors") < order.index(VITALS_UUID)
    assert order.index(engine.MEDIA + "extension-position") < order.index(MEDIA_CONTROLS_UUID)


def test_applying_the_same_look_twice_changes_nothing(look, full_caps, paths, backend):
    eng = Engine(backend, paths)
    eng.apply(look, full_caps)
    backend.writes.clear()
    assert eng.apply(look, full_caps).changed == 0
    assert backend.writes == [] and len(eng.history()) == 1
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
