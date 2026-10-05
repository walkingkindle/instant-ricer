"""The manual page is written by hand; these tests keep it in step with the command line."""
import argparse
import re
import shlex
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from ricer import __version__, cli, topup
from ricer.capabilities import RICER_UUID
from ricer.look import DIAL_NAMES, KEEP_PARTS

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "man" / "ricer.1"


@pytest.fixture(scope="module")
def page() -> str:
    """The page's text with roff escapes for hyphens, tildes and fonts removed."""
    text = PAGE.read_text()
    text = text.replace("\\-", "-").replace("\\(ti", "~")
    return re.sub(r"\\f[BIRP]", "", text)


def parsers(parser, prefix=("ricer",)):
    """Every (command words, parser) in the command tree."""
    yield prefix, parser
    for name, child in getattr(parser, "subcommands", {}).items():
        yield from parsers(child, (*prefix, name))


def test_the_title_line_carries_the_current_version(page):
    title = next(line for line in page.splitlines() if line.startswith(".TH"))
    assert title.startswith(".TH RICER 1 ") and f'"ricer {__version__}"' in title


def test_every_command_and_action_is_documented(page):
    for words, _parser in parsers(cli.build_parser()):
        if len(words) == 2:                                  # ricer instant, ricer default, ...
            assert f".B {' '.join(words)}" in page, words    # in the synopsis
            assert f".SS {' '.join(words)}" in page, words   # and with a section of its own
    assert ("list | add FILE... | fetch [--count N] [--query WORDS] | auto [on | off] [--cap N]"
            in page)                                         # wallpapers' actions
    for action in ("list", "set", "show", "clear"):
        assert f"\n.B {action}\n" in page, action             # each described in its own entry
    assert "\nadd FILE...\n" in page and "\nfetch [--count N] [--query WORDS]\n" in page
    assert "\nauto [on | off] [--cap N]\n" in page
    assert "[set | show | clear]" in page and "start | stop" in page and "start or stop the process" in page


def test_every_option_is_documented(page):
    seen = set()
    for _words, parser in parsers(cli.build_parser()):
        for action in parser._actions:
            for option in action.option_strings:
                if option not in ("-h", "--help"):
                    seen.add(option)
                    assert option in page, option
    assert {"--cool", "--ease", "--warmth", "--chaos", "--all", "--seed", "--keep", "--dry-run",
            "--json", "--count", "--query", "--cap", "--version"} == seen


def test_dials_keep_parts_and_defaults_match_the_code(page):
    for name in DIAL_NAMES:
        assert re.search(rf"^--{name} N$", page, re.M), name
    for part in KEEP_PARTS:
        assert re.search(rf"^\.BR? {part}\b", page, re.M), part
    assert f"({cli.DEFAULT_FETCH} if not given)" in page
    assert f"({topup.DEFAULT_CAP} if never set)" in page
    assert f"fetches {topup.TOPUP_COUNT} new images" in page
    assert "left out is 5" in page and cli.DEFAULT_DIAL == 5


def test_every_example_in_the_page_is_a_command_that_parses(page):
    parser = cli.build_parser()
    blocks = re.findall(r"^\.EX\n(.*?)^\.EE$", page, re.M | re.S)
    commands = [line for block in blocks for line in block.splitlines()]
    assert len(commands) >= 12
    for command in commands:
        words = shlex.split(command)
        assert words[0] == "ricer", command
        try:
            parser.parse_args(words[1:])
        except SystemExit:
            pytest.fail(f"the manual shows a command that does not parse: {command}")


def test_the_files_it_names_are_the_ones_ricer_uses(page, tmp_path):
    from ricer.paths import Paths
    paths = Paths.from_env({"HOME": "/home/someone"})
    for path in (paths.state_file, paths.default_file, paths.widgets_file, paths.shell_file,
                 paths.extensions_dir / RICER_UUID, paths.autostart_file,
                 paths.wallpapers, paths.shell_theme_file.parent.parent, paths.cache):
        shown = "~" + str(path)[len("/home/someone"):]
        assert shown in page, shown


def test_the_page_formats_without_warnings():
    groff = shutil.which("groff")
    if not groff:
        pytest.skip("groff is not installed")
    done = subprocess.run([groff, "-man", "-ww", "-Tutf8", "-z", str(PAGE)], capture_output=True, text=True)
    assert done.returncode == 0 and done.stderr == ""


def test_no_text_line_is_swallowed_as_a_roff_request():
    known = {".TH", ".SH", ".SS", ".PP", ".TP", ".B", ".I", ".BR", ".IR", ".br", ".RS", ".RE", ".EX", ".EE",
             '.\\"'}
    for number, line in enumerate(PAGE.read_text().splitlines(), 1):
        if line.startswith((".", "'")):
            assert line.split()[0] in known, f"line {number} would be read as a request: {line}"


def test_the_page_is_installed_with_the_package():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert project["tool"]["setuptools"]["data-files"] == {"share/man/man1": ["man/ricer.1"]}
    assert PAGE.is_file()
    assert isinstance(cli.build_parser(), argparse.ArgumentParser)
