import dataclasses
import json
import re

import pytest

from ricer import shell_extension
from ricer.capabilities import RICER_UUID
from ricer.generator import generate
from ricer.look import BAR_CLOCKS, MENU_SECTIONS, Bar, Dials


@pytest.fixture
def look(wallpaper_set):
    return generate(Dials(8, 4, 5), wallpaper_set, 3)


def test_the_extension_ships_with_the_package_under_its_own_name():
    files = shell_extension.bundled()
    assert set(files) == {"metadata.json", "extension.js", "stylesheet.css"}
    meta = json.loads(files["metadata.json"])
    assert meta["uuid"] == RICER_UUID and meta["shell-version"]
    assert "export default class" in files["extension.js"]
    assert files["stylesheet.css"].count("{") == files["stylesheet.css"].count("}")


def test_the_extension_knows_every_card_and_clock_a_look_can_ask_for():
    script = shell_extension.bundled()["extension.js"]
    cards = re.search(r"const CARDS = \{(.*?)\};", script, re.S).group(1)
    assert set(re.findall(r"(\w+):", cards)) == set(MENU_SECTIONS)
    assert "'full'" in script and "'glyph'" in script       # the two it handles by name
    for form in BAR_CLOCKS:                                  # the others arrive as a format
        assert (shell_extension.clock_format(form, True) is None) == (form in ("full", "glyph"))
    # it reads the file ricer writes
    assert "'ricer', 'shell.json'" in script


def test_install_copies_the_files_once_and_again_only_when_they_differ(paths):
    folder = paths.extensions_dir / RICER_UUID
    assert shell_extension.install(paths) is True
    assert {path.name for path in folder.iterdir()} == set(shell_extension.FILES)
    assert shell_extension.install(paths) is False
    (folder / "extension.js").write_text("// an older version")
    assert shell_extension.install(paths) is True
    assert (folder / "extension.js").read_text() == shell_extension.bundled()["extension.js"]


def test_config_says_what_the_look_wants(look, full_caps):
    bar = Bar(style="island", clock="date", menu=("profile", "system"))
    config = shell_extension.config(dataclasses.replace(look, bar=bar), full_caps)
    assert config["clock"] == {"form": "date", "format": "%a %-d %b"}
    assert config["menu"] == ["profile", "system"]
    assert config["palette"][0] == look.palette.accent and len(config["palette"]) == 5
    assert config["seed"] == look.seed and config["caps"] == look.style.caps
    json.dumps(config)


def test_the_time_follows_the_desktops_twelve_or_twenty_four_hours(look, full_caps):
    timed = dataclasses.replace(look, bar=Bar(clock="time"))
    assert shell_extension.config(timed, full_caps)["clock"]["format"] == "%H:%M"
    twelve = dataclasses.replace(full_caps, clock_24h=False)
    assert shell_extension.config(timed, twelve)["clock"]["format"] == "%-l:%M %p"
    stock = shell_extension.config(dataclasses.replace(look, bar=Bar()), full_caps)
    assert stock["clock"] == {"form": "full", "format": None} and stock["menu"] == []
