import io
import shlex

import pytest

from ricer import __version__, cli
from ricer.look import DIAL_NAMES


def run(*argv):
    out = io.StringIO()
    code = cli.main(list(argv), out=out)                     # no app: help must not need a desktop
    return code, out.getvalue()


@pytest.fixture(autouse=True)
def no_desktop(monkeypatch):
    def unreachable():
        raise AssertionError("help tried to reach the desktop")
    monkeypatch.setattr(cli, "default_app", unreachable)


def test_help_shows_examples_dials_and_every_command():
    code, text = run("help")
    assert code == 0 and text.startswith(f"ricer {__version__}:")
    for name in cli.COMMAND_HELP:
        assert f"\n  {name} " in text
    for name in DIAL_NAMES:
        assert f"  --{name} " in text
    assert "--all N" in text and "--seed N" in text
    assert "ricer help COMMAND" in text and "man ricer" in text


def test_ricer_with_no_command_shows_the_same():
    assert run() == run("help")


def test_every_example_is_a_command_that_parses():
    parser = cli.build_parser()
    assert len(cli.EXAMPLES) >= 8
    for command, what in cli.EXAMPLES:
        words = shlex.split(command)
        assert words[0] == "ricer" and what
        args = parser.parse_args(words[1:])
        assert args.command in cli.COMMAND_HELP
        assert f"  {command} " in cli.overview()


def test_the_command_list_is_the_parsers_own():
    parser = cli.build_parser()
    assert list(cli.COMMAND_HELP) == list(parser.subcommands)
    assert set(cli.COMMANDS) | {"help"} == set(cli.COMMAND_HELP)
    assert set(cli.DIAL_HELP) == set(DIAL_NAMES)


def test_help_for_one_command_shows_its_options():
    code, text = run("help", "instant")
    assert code == 0 and text.startswith("usage: ricer instant")
    for option in ("--cool", "--ease", "--warmth", "--chaos", "--all", "--seed", "--keep", "--dry-run"):
        assert option in text
    assert "usage: ricer default [-h] [{set,show,clear}]" in run("help", "default")[1]
    assert "COMMAND" in run("help", "help")[1]


def test_help_reaches_the_actions_of_wallpapers():
    listing = run("help", "wallpapers")[1]
    assert "list" in listing and "add" in listing and "fetch" in listing
    code, text = run("help", "wallpapers", "fetch")
    assert code == 0 and "--count N" in text and "--query WORDS" in text


@pytest.mark.parametrize("topic", [["nonsense"], ["wallpapers", "burn"], ["instant", "extra"]])
def test_help_for_something_that_is_not_a_command(topic, capsys):
    code, text = run("help", *topic)
    assert code == 2 and text == ""
    message = capsys.readouterr().err
    assert f"no command '{' '.join(topic)}'" in message and "instant, reroll" in message


def test_plain_dash_help_points_at_the_examples_and_the_manual(capsys):
    with pytest.raises(SystemExit) as stop:
        cli.main(["--help"])
    assert stop.value.code == 0
    text = capsys.readouterr().out
    assert "ricer help" in text and "man ricer" in text
    for name, summary in cli.COMMAND_HELP.items():
        assert name in text and summary.split()[0] in text
