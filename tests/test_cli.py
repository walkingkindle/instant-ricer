import io
import json

import pytest

from ricer import cli, wallpapers
from ricer.backends import FakeBackend
from ricer.capabilities import DOCK_SCHEMA, USER_THEME_UUID
from ricer.look import Dials

from conftest import solid, two_tone

GNOME_X11 = {"XDG_CURRENT_DESKTOP": "ubuntu:GNOME", "XDG_SESSION_TYPE": "x11"}


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
    backend = FakeBackend(
        schemas={DOCK_SCHEMA},
        effective={("org.gnome.shell", "enabled-extensions"): [USER_THEME_UUID]})
    return cli.App(paths=paths, backend=backend, daemon=FakeDaemon(), env=GNOME_X11)


def run(app, *argv):
    out = io.StringIO()
    code = cli.main(list(argv), app=app, out=out)
    return code, out.getvalue()


def parse(*argv):
    return cli.build_parser().parse_args(["instant", *argv])


def test_dials_default_to_five():
    assert cli.dials_from(parse()) == Dials(5, 5, 5)


def test_all_sets_every_dial_and_single_flags_override():
    assert cli.dials_from(parse("--all", "8")) == Dials(8, 8, 8)
    assert cli.dials_from(parse("--all", "8", "--ease", "2")) == Dials(8, 2, 8)
    assert cli.dials_from(parse("--warmth", "9")) == Dials(5, 5, 9)


@pytest.mark.parametrize("argv", [["--cool", "0"], ["--ease", "11"], ["--warmth", "x"],
                                  ["--all", "12"], ["--shuffle", "--seed", "3"]])
def test_bad_arguments_are_refused(argv, capsys):
    with pytest.raises(SystemExit) as exit_info:
        parse(*argv)
    assert exit_info.value.code == 2


def test_instant_applies_and_reports(app):
    code, text = run(app, "instant", "--cool", "8", "--warmth", "10")
    assert code == 0 and "Applied." in text
    assert "warm.png" in text and "cool 8 · ease 5 · warmth 10" in text
    assert "file://" + str(app.paths.wallpapers / "warm.png") in app.backend.values[
        "/org/gnome/desktop/background/picture-uri"]
    assert app.daemon.calls == ["sync"]


def test_instant_twice_reports_no_changes(app):
    run(app, "instant", "--all", "6")
    code, text = run(app, "instant", "--all", "6")
    assert code == 0 and "No changes" in text


def test_dry_run_changes_nothing(app):
    code, text = run(app, "instant", "--all", "9", "--dry-run")
    assert code == 0 and "Dry run" in text
    assert app.backend.values == {} and app.backend.writes == []
    assert not app.paths.state_file.exists() and not app.paths.widgets_file.exists()
    assert app.daemon.calls == []
    assert "Blur my Shell" in text                       # the skip notice still shows


def test_json_output_is_the_look(app):
    code, text = run(app, "instant", "--all", "4", "--dry-run", "--json")
    look = json.loads(text[:text.rindex("}") + 1])
    assert look["dials"] == {"cool": 4, "ease": 4, "warmth": 4} and look["seed"] == 0


def test_seed_is_reproducible_and_shuffle_prints_one(app):
    _, first = run(app, "instant", "--seed", "77", "--dry-run", "--json")
    _, again = run(app, "instant", "--seed", "77", "--dry-run", "--json")
    assert first == again and '"seed": 77' in first
    code, text = run(app, "instant", "--shuffle")
    assert code == 0 and "--seed " in text


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


def test_revert_and_status(app):
    assert "Nothing to revert" in run(app, "revert")[1]
    assert "No look applied" in run(app, "status")[1]
    run(app, "instant", "--all", "7")
    status = run(app, "status")[1]
    assert "cool 7" in status and "Wallpapers: 2" in status and "Blur my Shell" in status
    code, text = run(app, "revert")
    assert code == 0 and "Reverted" in text and app.backend.values == {}
    run(app, "instant", "--all", "7")
    run(app, "instant", "--all", "3")
    assert "Reverted" in run(app, "revert", "--all")[1] and app.backend.values == {}


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
