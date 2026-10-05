import dataclasses
import json

import pytest

from ricer import engine
from ricer.backends import FakeBackend, gv
from ricer.engine import ApplyError, Engine, build_plan
from ricer.generator import generate
from ricer.look import Dials


class FakeDaemon:
    def __init__(self):
        self.syncs = 0

    def sync(self):
        self.syncs += 1


@pytest.fixture
def look(wallpaper_set):
    return generate(Dials(8, 4, 7), wallpaper_set)


@pytest.mark.parametrize("value, text", [(True, "true"), (False, "false"), (44, "44"), (0.3, "0.3"),
                                         ("Yaru", "'Yaru'"), ("it's", "'it\\'s'"),
                                         (["#fff", "#000"], "['#fff', '#000']")])
def test_gv(value, text):
    assert gv(value) == text


def test_plan_on_a_full_desktop_covers_everything(look, full_caps, paths):
    plan = build_plan(look, full_caps, paths)
    s = plan.settings
    assert s[engine.BACKGROUND + "picture-uri"] == gv("file://" + look.wallpaper)
    assert s[engine.INTERFACE + "color-scheme"] == "'prefer-dark'"
    assert s[engine.INTERFACE + "icon-theme"] == "'Papirus-Dark'"
    assert s[engine.INTERFACE + "cursor-theme"] == "'Bibata-Modern-Ice'"
    assert s[engine.DOCK + "dock-fixed"] == "false" and s[engine.DOCK + "extend-height"] == "false"
    assert s[engine.USER_THEME_NAME] == "'Ricer'"
    assert s[engine.BLUR + "panel/blur"] == "false" and s[engine.BLUR + "overview/blur"] == "true"
    profile = "/org/gnome/terminal/legacy/profiles:/:b1dcc9dd-5262-4d8d-a863-c897e6d979b9/"
    assert s[profile + "background-color"] == gv(look.terminal["background"])
    assert engine.INTERFACE + "accent-color" not in s
    assert "@import" in plan.files[paths.shell_theme_file]
    assert json.loads(plan.files[paths.widgets_file])["widgets"]
    assert "ricer.widgets.daemon" in plan.files[paths.autostart_file]
    assert plan.notices == []


def test_plan_picks_the_accent_matched_theme_and_falls_back(look, full_caps, paths):
    blue = dataclasses.replace(look, gtk_accent="blue")
    plan = build_plan(blue, full_caps, paths)
    assert plan.settings[engine.INTERFACE + "gtk-theme"] == "'Yaru-blue-dark'"
    assert "Yaru-blue-dark/gnome-shell.css" in plan.files[paths.shell_theme_file]

    olive = dataclasses.replace(look, gtk_accent="olive")          # not installed in full_caps
    plan = build_plan(olive, full_caps, paths)
    assert plan.settings[engine.INTERFACE + "gtk-theme"] == "'Yaru-dark'"
    assert "Yaru-dark/gnome-shell.css" in plan.files[paths.shell_theme_file]


def test_plan_on_a_bare_desktop_skips_and_says_why(look, bare_caps, paths):
    plan = build_plan(look, bare_caps, paths)
    s = plan.settings
    assert engine.BACKGROUND + "picture-uri" in s
    assert s[engine.INTERFACE + "accent-color"] in {gv(n) for n in ("orange", "pink", "purple", "blue",
                                                                    "red", "green", "teal")}
    for missing in ("gtk-theme", "icon-theme", "cursor-theme"):
        assert engine.INTERFACE + missing not in s
    assert not any(path.startswith((engine.DOCK, engine.BLUR, "/org/gnome/terminal")) for path in s)
    assert engine.USER_THEME_NAME not in s and paths.shell_theme_file not in plan.files
    assert json.loads(plan.files[paths.widgets_file])["widgets"] == []
    assert plan.files[paths.autostart_file] is None
    text = " ".join(plan.notices)
    for word in ("Dock", "Top bar", "blur", "X11"):
        assert word in text


def test_stock_bar_switches_the_user_theme_off(wallpaper_set, full_caps, paths):
    look = generate(Dials(1, 1, 5), wallpaper_set)
    plan = build_plan(look, full_caps, paths)
    assert plan.settings[engine.USER_THEME_NAME] == "''"
    assert paths.shell_theme_file not in plan.files
    assert plan.settings[engine.BLUR + "panel/blur"] == "false"


def test_apply_writes_settings_files_and_state(look, full_caps, paths, backend):
    daemon = FakeDaemon()
    result = Engine(backend, paths, daemon).apply(look, full_caps)
    plan = build_plan(look, full_caps, paths)
    assert backend.values == plan.settings
    assert result.changed == len(plan.settings) + len(plan.files)
    assert paths.shell_theme_file.read_text() == plan.files[paths.shell_theme_file]
    assert paths.autostart_file.is_file() and daemon.syncs == 1
    assert Engine(backend, paths).current_look() == look


def test_applying_the_same_look_twice_changes_nothing(look, full_caps, paths, backend):
    eng = Engine(backend, paths)
    eng.apply(look, full_caps)
    backend.writes.clear()
    assert eng.apply(look, full_caps).changed == 0
    assert backend.writes == []
    # the snapshot from the first apply is still there to revert
    assert eng.revert() > 0


def test_revert_restores_the_exact_prior_state(look, full_caps, paths):
    before = {engine.INTERFACE + "gtk-theme": "'Yaru'", engine.DOCK + "dock-position": "'LEFT'",
              "/org/unrelated/key": "'untouched'"}
    backend = FakeBackend(before)
    paths.widgets_file.parent.mkdir(parents=True)
    paths.widgets_file.write_text("old config")
    eng = Engine(backend, paths)
    eng.apply(look, full_caps)
    assert backend.values != before

    assert eng.revert() > 0
    assert backend.values == before                       # keys that were unset are unset again
    assert paths.widgets_file.read_text() == "old config"
    assert not paths.shell_theme_file.exists() and not paths.autostart_file.exists()
    assert eng.current_look() is None
    assert eng.revert() == 0


def test_revert_undoes_only_the_last_apply_and_all_undoes_everything(wallpaper_set, full_caps, paths):
    before = {engine.DOCK + "dash-max-icon-size": "48"}
    backend = FakeBackend(before)
    eng = Engine(backend, paths)
    first, second = generate(Dials(8, 2, 7), wallpaper_set), generate(Dials(8, 9, 7), wallpaper_set)
    eng.apply(first, full_caps)
    after_first = dict(backend.values)
    eng.apply(second, full_caps)

    eng.revert()
    assert backend.values == after_first
    assert eng.current_look() == first                    # the earlier look is current again
    eng.apply(second, full_caps)
    assert eng.revert(everything=True) > 0
    assert backend.values == before
    assert not paths.widgets_file.exists()
    assert eng.revert(everything=True) == 0


def test_a_failed_write_rolls_everything_back(look, full_caps, paths):
    before = {engine.INTERFACE + "gtk-theme": "'Yaru'"}
    backend = FakeBackend(before)
    backend.fail_on = {engine.DOCK + "background-opacity"}
    eng = Engine(backend, paths)
    with pytest.raises(ApplyError):
        eng.apply(look, full_caps)
    assert backend.values == before
    assert not paths.shell_theme_file.exists() and not paths.widgets_file.exists()
    assert eng.load_state() == {} and eng.revert() == 0


def test_restyling_the_bar_reloads_the_shell_theme(wallpaper_set, full_caps, paths, backend):
    eng = Engine(backend, paths)
    eng.apply(generate(Dials(8, 4, 2), wallpaper_set), full_caps)
    assert backend.reloads == 0                            # naming the theme loads it by itself
    eng.apply(generate(Dials(8, 4, 9), wallpaper_set), full_caps)
    assert backend.reloads == 1                            # same theme name, new stylesheet


def test_engine_only_touches_keys_it_owns(look, full_caps, paths, backend):
    Engine(backend, paths).apply(look, full_caps)
    owned = ("/org/gnome/desktop/background/", "/org/gnome/desktop/screensaver/picture-uri",
             "/org/gnome/desktop/interface/", engine.DOCK, engine.USER_THEME_NAME, engine.BLUR,
             "/org/gnome/terminal/legacy/profiles:/")
    assert all(path.startswith(owned) for path in backend.values)
