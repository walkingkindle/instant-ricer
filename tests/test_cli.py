import io
import json
import random

import pytest
from PIL import Image

from ricer import cli, wallpapers
from ricer.backends import FakeBackend
from ricer.capabilities import (BLUR_UUID, DOCK_SCHEMA, MEDIA_CONTROLS_UUID, OPTIONAL_EXTENSIONS,
                                USER_THEME_UUID, VITALS_UUID)
from ricer.look import Dials

from conftest import solid, two_tone

GNOME_X11 = {"XDG_CURRENT_DESKTOP": "ubuntu:GNOME", "XDG_SESSION_TYPE": "x11"}
SHELL = "org.gnome.shell"


class FakeDaemon:
    def __init__(self):
        self.calls = []

    def sync(self):
        self.calls.append("sync")

    def start(self):
        self.calls.append("start")
        return True

    def stop(self):
        self.calls.append("stop")
        return False


@pytest.fixture
def app(paths):
    paths.wallpapers.mkdir(parents=True)
    two_tone((230, 140, 40), (200, 80, 60)).save(paths.wallpapers / "warm.png")
    two_tone((30, 80, 200), (40, 160, 210)).save(paths.wallpapers / "cold.png")
    two_tone((60, 40, 120), (30, 30, 60)).save(paths.wallpapers / "dusk.png")
    backend = FakeBackend(
        schemas={DOCK_SCHEMA},
        effective={(SHELL, "enabled-extensions"): [USER_THEME_UUID]},
        extensions={USER_THEME_UUID: True})
    return cli.App(paths=paths, backend=backend, daemon=FakeDaemon(), env=GNOME_X11,
                   fonts=frozenset(), screen=(1920, 1080))


def run(app, *argv):
    out = io.StringIO()
    code = cli.main(list(argv), app=app, out=out)
    return code, out.getvalue()


def parse(*argv, command="instant"):
    return cli.build_parser().parse_args([command, *argv])


def seed_of(text):
    return int(text.split("--seed ")[1].split()[0])


# -- arguments --------------------------------------------------------------------------------

def test_dials_default_to_five():
    assert cli.dials_from(parse()) == Dials(5, 5, 5, 5)


def test_all_sets_the_three_style_dials_but_not_chaos():
    assert cli.dials_from(parse("--all", "8")) == Dials(8, 8, 8, 5)
    assert cli.dials_from(parse("--all", "8", "--ease", "2", "--chaos", "9")) == Dials(8, 2, 8, 9)
    assert cli.dials_from(parse("--warmth", "9")) == Dials(5, 5, 9, 5)


def test_reroll_starts_from_the_current_dials():
    current = Dials(8, 3, 9, 7)
    assert cli.dials_from(parse(command="reroll"), current) == current
    assert cli.dials_from(parse("--chaos", "2", command="reroll"), current) == Dials(8, 3, 9, 2)
    assert cli.dials_from(parse("--all", "4", command="reroll"), current) == Dials(4, 4, 4, 7)


@pytest.mark.parametrize("argv", [["--cool", "0"], ["--ease", "11"], ["--warmth", "x"], ["--chaos", "0"],
                                  ["--all", "12"], ["--keep", "sofa"], ["--keep", ""], ["--seed", "abc"]])
def test_bad_arguments_are_refused(argv, capsys):
    with pytest.raises(SystemExit) as exit_info:
        parse(*argv)
    assert exit_info.value.code == 2


def test_keep_takes_a_comma_separated_list():
    assert parse("--keep", "wallpaper, style").keep == ["wallpaper", "style"]
    assert parse().keep == []


# -- instant ----------------------------------------------------------------------------------

def test_instant_applies_and_says_how_to_get_the_look_back(app):
    code, text = run(app, "instant", "--cool", "8", "--warmth", "10", "--chaos", "1")
    assert code == 0 and "Applied." in text
    assert "cool 8 · ease 5 · warmth 10 · chaos 1 · seed " in text and "wallpaper  warm.png" in text
    assert f"This look again: ricer instant --cool 8 --ease 5 --warmth 10 --chaos 1 --seed {seed_of(text)}" in text
    assert "file://" + str(app.paths.wallpapers / "warm.png") in app.backend.values[
        "/org/gnome/desktop/background/picture-uri"]
    assert app.daemon.calls == ["sync"]


def test_every_run_is_a_different_look(app):
    texts = [run(app, "instant", "--all", "7")[1] for _ in range(4)]
    assert len({seed_of(text) for text in texts}) == 4
    assert all("Applied." in text for text in texts)
    walls = [text.split("wallpaper  ")[1].split()[0] for text in texts]
    assert all(a != b for a, b in zip(walls, walls[1:]))     # never the same wallpaper twice running


def test_a_seed_brings_the_same_look_back(app):
    _, first = run(app, "instant", "--all", "6", "--seed", "4242", "--dry-run", "--json")
    _, again = run(app, "instant", "--all", "6", "--seed", "4242", "--dry-run", "--json")
    assert first == again and '"seed": 4242' in first
    assert "Applied." in run(app, "instant", "--all", "6", "--seed", "4242")[1]
    assert "No changes: this look is already applied." in run(app, "instant", "--all", "6", "--seed", "4242")[1]


def test_dry_run_changes_nothing(app):
    code, text = run(app, "instant", "--all", "9", "--dry-run")
    assert code == 0 and "Dry run: nothing was changed." in text
    assert app.backend.values == {} and app.backend.writes == []
    assert not app.paths.state_file.exists() and not app.paths.widgets_file.exists()
    assert app.daemon.calls == []
    assert "Blur my Shell" in text                           # skip notices still show


def test_json_output_is_the_look(app):
    _, text = run(app, "instant", "--all", "4", "--chaos", "8", "--seed", "5", "--dry-run", "--json")
    look = json.loads(text[:text.rindex("}") + 1])
    assert look["dials"] == {"cool": 4, "ease": 4, "warmth": 4, "chaos": 8} and look["seed"] == 5


def test_the_description_lists_what_a_look_is_made_of(app):
    _, text = run(app, "instant", "--cool", "9", "--ease", "9", "--seed", "11", "--dry-run")
    for label in ("wallpaper", "style", "top bar", "dock", "desktop"):
        assert f"  {label}" in text
    assert "layout" in text and "clock" in text


def test_empty_library_is_a_clear_error(app, capsys):
    for image in app.paths.wallpapers.iterdir():
        image.unlink()
    code, _ = run(app, "instant")
    assert code == 1 and app.backend.values == {}
    assert "ricer wallpapers fetch" in capsys.readouterr().err


def test_other_desktops_are_refused_but_can_dry_run(app, capsys):
    app.env = {"XDG_CURRENT_DESKTOP": "KDE", "XDG_SESSION_TYPE": "wayland"}
    code, _ = run(app, "instant")
    assert code == 2 and app.backend.values == {}
    assert "GNOME" in capsys.readouterr().err
    assert run(app, "instant", "--dry-run")[0] == 0


# -- keep and reroll --------------------------------------------------------------------------

def test_keep_and_reroll_need_a_current_look(app, capsys):
    assert run(app, "instant", "--keep", "wallpaper")[0] == 1
    assert "--keep needs a current look" in capsys.readouterr().err
    assert run(app, "reroll")[0] == 1
    assert "no current look to reroll" in capsys.readouterr().err
    assert app.backend.values == {}


def test_keep_carries_parts_of_the_current_look_over(app):
    _, first = run(app, "instant", "--all", "8", "--json")
    before = json.loads(first[:first.rindex("}") + 1])
    for _ in range(4):
        _, text = run(app, "instant", "--all", "8", "--keep", "wallpaper,style", "--json")
        after = json.loads(text[:text.rindex("}") + 1])
        assert after["wallpaper"] == before["wallpaper"] and after["style"] == before["style"]
        assert after["palette"] == before["palette"] and after["seed"] != before["seed"]
        assert "plus what was kept: wallpaper, style" in text


def test_reroll_keeps_the_dials_and_changes_the_look(app):
    _, first = run(app, "instant", "--cool", "8", "--ease", "3", "--warmth", "6", "--chaos", "7")
    code, text = run(app, "reroll")
    assert code == 0 and "cool 8 · ease 3 · warmth 6 · chaos 7 · seed " in text
    assert seed_of(text) != seed_of(first) and "Applied." in text
    assert "cool 8 · ease 9 · warmth 6 · chaos 7" in run(app, "reroll", "--ease", "9")[1]


# -- revert and status ------------------------------------------------------------------------

def test_revert_and_status(app):
    assert "Nothing to revert" in run(app, "revert")[1]
    status = run(app, "status")[1]
    assert "No look applied" in status and "Wallpapers: 3" in status
    assert "no   Stats in the top bar (install the 'Vitals' extension: ricer setup)" in status

    run(app, "instant", "--all", "7", "--seed", "9")
    assert "cool 7 · ease 7 · warmth 7 · chaos 5 · seed 9" in run(app, "status")[1]
    code, text = run(app, "revert")
    assert code == 0 and "Reverted" in text and app.backend.values == {}
    assert "No look applied" in run(app, "status")[1]

    run(app, "instant", "--all", "7")
    run(app, "instant", "--all", "3")
    assert "Reverted" in run(app, "revert", "--all")[1] and app.backend.values == {}


# -- the default look -------------------------------------------------------------------------

def test_default_needs_a_look_first(app, capsys):
    assert run(app, "default")[0] == 1
    assert "No default look saved yet" in capsys.readouterr().err
    assert run(app, "default", "set")[0] == 1
    assert "no look to save yet" in capsys.readouterr().err
    assert run(app, "default", "show")[0] == 1
    assert run(app, "default", "clear") == (0, "There was no default look.\n")
    assert app.backend.values == {}


def test_a_look_can_be_saved_as_the_default_and_returned_to(app):
    run(app, "instant", "--all", "7", "--seed", "9")
    code, text = run(app, "default", "set")
    assert code == 0 and "Saved as your default look:" in text and "seed 9" in text
    assert "ricer default" in text and "Default look: this one" in run(app, "status")[1]
    liked = dict(app.backend.values)

    run(app, "instant", "--all", "3", "--seed", "4")
    assert app.backend.values != liked
    status = run(app, "status")[1]
    assert "Default look: " in status and "seed 9" in status and "'ricer default' returns to it" in status

    code, text = run(app, "default")
    assert code == 0 and "Applied your default look." in text and "seed 9" in text
    assert app.backend.values == liked
    assert "No changes: your default look is already applied." in run(app, "default")[1]
    assert run(app, "default", "show")[1].startswith("cool 7 · ease 7 · warmth 7 · chaos 5 · seed 9")

    assert run(app, "default", "clear") == (0, "Default look forgotten.\n")
    assert "none saved" in run(app, "status")[1] and run(app, "default")[0] == 1


def test_the_default_does_not_depend_on_the_wallpaper_folder_staying_the_same(app, capsys):
    run(app, "instant", "--cool", "8", "--warmth", "10", "--chaos", "1", "--seed", "3")
    run(app, "default", "set")
    liked = dict(app.backend.values)
    assert "warm.png" in liked["/org/gnome/desktop/background/picture-uri"]

    # a new, better-matching image arrives (as warm, and with the detail these dials favour):
    # the same dials and seed now lead somewhere else...
    rng = random.Random(1)
    textured = Image.new("RGB", (192, 108))
    textured.putdata([(rng.randrange(170, 256), rng.randrange(70, 170), rng.randrange(10, 60))
                      for _ in range(192 * 108)])
    textured.save(app.paths.wallpapers / "warmer.png")
    _, text = run(app, "instant", "--cool", "8", "--warmth", "10", "--chaos", "1", "--seed", "3")
    assert "wallpaper  warmer.png" in text
    # ...but the default is the look itself, not a recipe for it
    assert run(app, "default")[0] == 0 and app.backend.values == liked

    run(app, "instant", "--all", "2", "--seed", "8")
    elsewhere = dict(app.backend.values)
    (app.paths.wallpapers / "warm.png").unlink()
    assert run(app, "default")[0] == 1 and app.backend.values == elsewhere
    assert "no longer there" in capsys.readouterr().err


def test_a_default_saved_by_another_version_is_reported_not_crashed_on(app, capsys):
    app.paths.default_file.parent.mkdir(parents=True, exist_ok=True)
    app.paths.default_file.write_text(json.dumps({"dials": {"cool": 5}, "bar_style": "cards"}))
    assert run(app, "default")[0] == 1
    assert "cannot be read by this version" in capsys.readouterr().err
    assert "none saved" in run(app, "status")[1]


# -- setup ------------------------------------------------------------------------------------

def test_setup_installs_what_is_missing_and_reapplies_the_look(app):
    run(app, "instant", "--cool", "6", "--ease", "9", "--seed", "3")      # ease 9: the bar wants widgets
    app.backend.installable = {VITALS_UUID, MEDIA_CONTROLS_UUID}          # the user accepts these two
    for uuid in (VITALS_UUID, MEDIA_CONTROLS_UUID):                       # ...which GNOME then installs
        (app.paths.data / "gnome-shell/extensions" / uuid).mkdir(parents=True)

    code, text = run(app, "setup")
    assert code == 0
    assert "have       User Themes" in text and "installed  Vitals" in text
    assert "skipped    Blur my Shell" in text and "1 extension(s) not installed" in text
    assert app.backend.install_requests == [BLUR_UUID, VITALS_UUID, MEDIA_CONTROLS_UUID]
    assert "Re-applied the current look" in text
    assert app.backend.extensions[VITALS_UUID] is True                    # ease 9 puts stats in the bar
    assert "/org/gnome/shell/extensions/vitals/hot-sensors" in app.backend.values


def test_setup_switches_user_extensions_back_on_and_enables_what_ricer_relies_on(app):
    app.backend.effective_values[(SHELL, "disable-user-extensions")] = True
    app.backend.extensions = {uuid: False for uuid in OPTIONAL_EXTENSIONS}
    code, text = run(app, "setup")
    assert code == 0 and "switching them back on" in text and "Setup complete." in text
    assert app.backend.effective_values[(SHELL, "disable-user-extensions")] is False
    assert app.backend.extensions[USER_THEME_UUID] and app.backend.extensions[BLUR_UUID]
    assert app.backend.extensions[VITALS_UUID] is False      # left for each look to decide
    assert app.backend.install_requests == []


# -- wallpapers and widgets -------------------------------------------------------------------

def test_wallpapers_list_and_add(app, tmp_path, capsys):
    listing = run(app, "wallpapers", "list")[1]
    assert "cold.png" in listing and "warmth" in listing
    new = tmp_path / "extra.png"
    solid((9, 9, 9)).save(new)
    code, text = run(app, "wallpapers", "add", str(new), str(tmp_path / "nope.png"))
    assert code == 1 and "added" in text and (app.paths.wallpapers / "extra.png").is_file()
    assert "nope.png" in capsys.readouterr().err


def test_wallpapers_fetch_uses_the_library_folder(app, monkeypatch, capsys):
    seen = {}

    def fake_fetch(directory, count, query):
        seen.update(directory=directory, count=count, query=query)
        return [directory / "wallhaven-x.jpg"]

    monkeypatch.setattr(wallpapers, "fetch", fake_fetch)
    code, text = run(app, "wallpapers", "fetch", "--count", "3")
    assert code == 0 and "1 new wallpaper in" in text
    assert seen == {"directory": app.paths.wallpapers, "count": 3, "query": "anime scenery"}

    def offline(*_args):
        raise OSError("no network")

    monkeypatch.setattr(wallpapers, "fetch", offline)
    assert run(app, "wallpapers", "fetch")[0] == 1
    assert "no network" in capsys.readouterr().err


def test_widgets_start_and_stop(app, capsys):
    assert run(app, "widgets", "start") == (0, "Started.\n")
    assert run(app, "widgets", "stop") == (0, "Not running.\n")
    app.env = {"XDG_CURRENT_DESKTOP": "GNOME", "XDG_SESSION_TYPE": "wayland"}
    assert run(app, "widgets", "start")[0] == 1
    assert "X11" in capsys.readouterr().err
