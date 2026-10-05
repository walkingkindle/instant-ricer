"""Command line: ricer instant | reroll | default | revert | status | setup | wallpapers | widgets | help."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from ricer import __version__, wallpapers
from ricer.capabilities import (BLUR_UUID, OPTIONAL_EXTENSIONS, USER_THEME_UUID, Capabilities, detect)
from ricer.compose import compose
from ricer.daemonctl import DaemonControl
from ricer.engine import ApplyError, Engine, build_plan
from ricer.generator import Kept, kept_from
from ricer.look import DIAL_MAX, DIAL_MIN, DIAL_NAMES, KEEP_PARTS, Dials, Look
from ricer.paths import Paths
from ricer.wallpapers import Library, NoWallpapersError

DEFAULT_DIAL = 5
DEFAULT_FETCH = 12
ALWAYS_ON = (USER_THEME_UUID, BLUR_UUID)                     # extensions ricer expects to stay enabled

# One line per command, in the order they are listed. Used for --help and for 'ricer help'.
COMMAND_HELP = {
    "instant": "generate a new look from the dials and apply it",
    "reroll": "another look with the current look's dials",
    "default": "return to the look you saved as your default",
    "revert": "undo the last look",
    "status": "show the current look and what this desktop supports",
    "setup": "install the optional GNOME extensions ricer can use",
    "wallpapers": "manage the wallpaper library",
    "widgets": "start or stop the desktop widgets",
    "help": "show examples to try, or the help for one command",
}
# What each dial runs from and to.
DIAL_HELP = {
    "cool": ("flashiness", "calm and minimal", "loud and flashy"),
    "ease": ("practicality", "looks first", "usability first"),
    "warmth": ("mood", "cold blues", "warm ambers"),
    "chaos": ("surprise", "close to what the other dials suggest", "anything goes"),
}
# Commands worth trying first, each with what it does. Every line here is checked to parse.
EXAMPLES = (
    ("ricer instant", "a new look, all dials at 5"),
    ("ricer instant --cool 9 --warmth 2", "loud and cold"),
    ("ricer instant --all 3", "calm"),
    ("ricer instant --all 8 --chaos 10", "anything goes"),
    ("ricer instant --dry-run", "show a look without applying it"),
    ("ricer reroll", "same dials, another look"),
    ("ricer reroll --keep wallpaper,style", "keep those parts, change the rest"),
    ("ricer default set", "save the look you have now"),
    ("ricer default", "go back to it"),
    ("ricer revert", "undo the last look"),
    ("ricer status", "what is applied, and what this desktop supports"),
)


@dataclass
class App:
    """Everything a command needs. Tests build one around fakes."""
    paths: Paths
    backend: object
    daemon: object
    env: dict | None = None
    fonts: frozenset | None = None                           # None: ask the system
    screen: tuple | None = None

    @property
    def library(self) -> Library:
        return Library(self.paths.wallpapers, self.paths.wallpaper_cache)

    @property
    def engine(self) -> Engine:
        return Engine(self.backend, self.paths, self.daemon)

    def capabilities(self) -> Capabilities:
        return detect(self.backend, self.paths, self.env, fonts=self.fonts, screen=self.screen)


def default_app() -> App:
    from ricer.backends import GnomeBackend
    paths = Paths.from_env()
    return App(paths=paths, backend=GnomeBackend(), daemon=DaemonControl(paths))


def dial(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if not DIAL_MIN <= value <= DIAL_MAX:
        raise argparse.ArgumentTypeError(f"must be between {DIAL_MIN} and {DIAL_MAX}")
    return value


def keep_parts(text: str) -> list[str]:
    parts = [part.strip() for part in text.split(",") if part.strip()]
    unknown = [part for part in parts if part not in KEEP_PARTS]
    if unknown or not parts:
        raise argparse.ArgumentTypeError(
            f"choose from {', '.join(KEEP_PARTS)} (comma-separated); got {text!r}")
    return parts


def _look_options(parser: argparse.ArgumentParser, all_help: str) -> None:
    for name, (what, low, high) in DIAL_HELP.items():
        parser.add_argument(f"--{name}", type=dial, metavar="N", help=f"{what}: 1 {low}, 10 {high}")
    parser.add_argument("--all", type=dial, metavar="N", dest="all_dials", help=all_help)
    parser.add_argument("--seed", type=int, metavar="N",
                        help="get an earlier look back: every run prints its seed")
    parser.add_argument("--keep", type=keep_parts, metavar="PARTS", default=[],
                        help=f"parts of the current look to carry over: {', '.join(KEEP_PARTS)}")
    parser.add_argument("--dry-run", action="store_true",
                        help="show the look without changing anything")
    parser.add_argument("--json", action="store_true", help="print the look as JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ricer", description="A desktop ricing engine for GNOME: four dials, a new look every run.",
        epilog="Run 'ricer help' for examples to try, and 'man ricer' for the manual.")
    parser.add_argument("--version", action="version", version=f"ricer {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="command")
    parser.subcommands = commands.choices                    # name -> parser, for 'ricer help NAME'

    def command(name: str, **options) -> argparse.ArgumentParser:
        return commands.add_parser(name, help=COMMAND_HELP[name], **options)

    instant = command(
        "instant",
        description="Each dial goes from 1 to 10; dials you leave out are 5. Every run is "
                    "different. The dials tilt the odds, and --seed brings a look back.")
    _look_options(instant, "set cool, ease and warmth at once (single dials still override)")

    reroll = command(
        "reroll",
        description="Like 'instant', but dials you leave out stay as they are in the current look.")
    _look_options(reroll, "set cool, ease and warmth at once (single dials still override)")

    default = command(
        "default",
        description="With no action, applies your default look. 'set' saves the look that is "
                    "applied now as the default; 'show' prints it; 'clear' forgets it.")
    default.add_argument("action", nargs="?", choices=("set", "show", "clear"))

    revert = command("revert")
    revert.add_argument("--all", action="store_true", dest="everything",
                        help="undo everything ricer ever changed")

    command("status")
    command("setup", description="Asks GNOME to install each optional extension that is missing. "
                                 "GNOME shows its own dialog for each one; nothing is installed "
                                 "without your confirmation there.")

    walls = command("wallpapers")
    wall_commands = walls.add_subparsers(dest="wallpaper_command", required=True, metavar="action")
    walls.subcommands = wall_commands.choices
    wall_commands.add_parser("list", help="list wallpapers with their measured mood")
    add = wall_commands.add_parser("add", help="copy images into the library")
    add.add_argument("files", nargs="+", metavar="FILE")
    fetch = wall_commands.add_parser("fetch", help="download SFW wallpapers from Wallhaven")
    fetch.add_argument("--count", type=int, default=DEFAULT_FETCH, metavar="N",
                       help=f"how many new images to get (default {DEFAULT_FETCH})")
    fetch.add_argument("--query", default=wallpapers.DEFAULT_QUERY, metavar="WORDS",
                       help=f"search words (default: {wallpapers.DEFAULT_QUERY!r})")

    widgets = command("widgets")
    widgets.add_argument("action", choices=("start", "stop"))

    helper = command("help", description="With no command, shows examples to try and the list "
                                         "of commands. With one, shows that command's options.")
    helper.add_argument("topic", nargs="*", metavar="COMMAND")
    return parser


def overview() -> str:
    """What 'ricer help' prints: commands to try, the dials, and every command in one line."""
    width = max(len(command) for command, _ in EXAMPLES) + 3
    lines = [f"ricer {__version__}: a different desktop look on every run", "", "Try:"]
    lines += [f"  {command:<{width}}{what}" for command, what in EXAMPLES]
    lines += ["", f"Dials, each from {DIAL_MIN} to {DIAL_MAX} ({DEFAULT_DIAL} if left out):"]
    lines += [f"  --{name:<8} {low} .. {high}" for name, (_, low, high) in DIAL_HELP.items()]
    lines += ["  --all N    sets cool, ease and warmth together",
              "", "Every run prints a seed, and --seed N brings that look back.", "", "Commands:"]
    lines += [f"  {name:<12} {text}" for name, text in COMMAND_HELP.items()]
    lines += ["", "More:  ricer help COMMAND   |   man ricer"]
    return "\n".join(lines)


def show_help(parser: argparse.ArgumentParser, topic: list[str], out) -> int:
    """'ricer help' and 'ricer help COMMAND [ACTION]'. Needs no desktop."""
    if not topic:
        print(overview(), file=out)
        return 0
    found = parser
    for word in topic:
        found = getattr(found, "subcommands", {}).get(word)
        if found is None:
            print(f"ricer help: there is no command '{' '.join(topic)}'. "
                  f"Commands: {', '.join(COMMAND_HELP)}.", file=sys.stderr)
            return 2
    print(found.format_help(), end="", file=out)
    return 0


def dials_from(args, base: Dials | None = None) -> Dials:
    """The dials for a run. Without `base`, unset dials are 5; with it, they keep its values."""
    values = {}
    for name in DIAL_NAMES:
        value = getattr(args, name)
        if value is None and name != "chaos" and args.all_dials is not None:
            value = args.all_dials                           # --all leaves chaos alone
        if value is None:
            value = getattr(base, name) if base else DEFAULT_DIAL
        values[name] = value
    return Dials(**values)


def _style_line(look: Look) -> str:
    style = look.style
    edge = {"none": "plain", "hairline": "hairline", "accent": "outlined"}[style.border]
    cards = "no cards" if style.fill == 0 else f"{edge} cards at {round(style.fill * 100)}%"
    weight = "thin" if style.weight < 0.25 else "light" if style.weight < 0.45 else \
        "regular" if style.weight < 0.65 else "heavy"
    return (f"{cards}, radius {style.radius}, {weight} {style.voice} type, "
            f"{look.palette.accent}{' to ' + look.palette.accent2 if style.gradient else ''}")


def _bar_line(look: Look) -> str:
    bar, parts = look.bar, [look.bar.style]
    if bar.stats:
        parts.append(f"{' '.join(bar.stats)} on the {bar.stats_side}")
    if bar.media:
        parts.append(f"player {'in the' if bar.media_side == 'center' else 'on the'} {bar.media_side}")
    return ", ".join(parts)


def describe(look: Look) -> str:
    dials, dock = look.dials, look.dock
    lines = [
        f"cool {dials.cool} · ease {dials.ease} · warmth {dials.warmth} · chaos {dials.chaos}"
        f" · seed {look.seed}",
        f"  wallpaper  {Path(look.wallpaper).name}",
        f"  style      {_style_line(look)}",
        f"  top bar    {_bar_line(look)}{'; blur on' if look.blur else ''}",
        f"  dock       {dock.position.lower()}, {'auto-hide' if dock.autohide else 'always visible'}, "
        f"{'floating' if dock.floating else 'edge to edge'}, {dock.icon_size}px icons"
        f"{', tinted' if dock.tint else ''}",
    ]
    if look.widgets:
        lines.append(f"  desktop    {look.layout} layout{', mirrored' if look.mirrored else ''}")
        lines += [f"               {widget.type:<9} {widget.design:<8} {widget.anchor}"
                  for widget in look.widgets]
    else:
        lines.append("  desktop    no widgets")
    return "\n".join(lines)


def _again(look: Look, kept: list[str]) -> str:
    dials = look.dials
    command = (f"ricer instant --cool {dials.cool} --ease {dials.ease} --warmth {dials.warmth} "
               f"--chaos {dials.chaos} --seed {look.seed}")
    if kept:
        return f"This look again: {command} (plus what was kept: {', '.join(kept)})"
    return f"This look again: {command}"


def cmd_look(app: App, args, out) -> int:
    """`instant` and `reroll`: compose a look, show it, apply it."""
    engine = app.engine
    current = engine.current_look()
    if args.command == "reroll" and current is None:
        print("There is no current look to reroll. Start with 'ricer instant'.", file=sys.stderr)
        return 1
    if args.keep and current is None:
        print("--keep needs a current look to keep parts of. Start with 'ricer instant'.",
              file=sys.stderr)
        return 1
    caps = app.capabilities()
    if not caps.gnome and not args.dry_run:
        print("ricer only supports the GNOME desktop; nothing was changed.", file=sys.stderr)
        return 2

    dials = dials_from(args, current.dials if args.command == "reroll" else None)
    keep = kept_from(current, args.keep) if args.keep else Kept()
    try:
        look = compose(dials, app.library.scan(), engine.history(), seed=args.seed,
                       screen=caps.screen, keep=keep)
    except NoWallpapersError as error:
        print(f"{error}\n(looked in {app.paths.wallpapers})", file=sys.stderr)
        return 1

    print(json.dumps(look.to_dict(), indent=2) if args.json else describe(look), file=out)
    if args.dry_run:
        for notice in build_plan(look, caps, app.paths).notices:
            print(f"note: {notice}", file=out)
        print("Dry run: nothing was changed.", file=out)
        return 0
    try:
        result = engine.apply(look, caps)
    except ApplyError as error:
        print(error, file=sys.stderr)
        return 1
    for notice in result.notices:
        print(f"note: {notice}", file=out)
    print("Applied." if result.changed else "No changes: this look is already applied.", file=out)
    print(_again(look, args.keep), file=out)
    return 0


def cmd_default(app: App, args, out) -> int:
    """Save the current look as the default, or go back to the saved one."""
    engine = app.engine
    if args.action == "set":
        look = engine.save_default()
        if look is None:
            print("There is no look to save yet. Apply one with 'ricer instant' first.", file=sys.stderr)
            return 1
        print(f"Saved as your default look:\n{describe(look)}\n"
              "Return to it at any time with: ricer default", file=out)
        return 0
    if args.action == "clear":
        print("Default look forgotten." if engine.clear_default() else "There was no default look.",
              file=out)
        return 0

    look = engine.default_look()
    if look is None:
        if app.paths.default_file.exists():
            print("The saved default look cannot be read by this version of ricer. "
                  "Apply a look you like and run 'ricer default set' again.", file=sys.stderr)
        else:
            print("No default look saved yet. Apply a look you like, then run 'ricer default set'.",
                  file=sys.stderr)
        return 1
    print(describe(look), file=out)
    if args.action == "show":
        return 0
    if not app.capabilities().gnome:
        print("ricer only supports the GNOME desktop; nothing was changed.", file=sys.stderr)
        return 2
    if not Path(look.wallpaper).is_file():
        print(f"Your default look's wallpaper is no longer there: {look.wallpaper}", file=sys.stderr)
        return 1
    try:
        result = engine.apply(look, app.capabilities())
    except ApplyError as error:
        print(error, file=sys.stderr)
        return 1
    for notice in result.notices:
        print(f"note: {notice}", file=out)
    print("Applied your default look." if result.changed
          else "No changes: your default look is already applied.", file=out)
    return 0


def cmd_setup(app: App, _args, out) -> int:
    backend = app.backend
    if not app.capabilities().extensions_allowed:
        print("GNOME has all user extensions switched off; switching them back on.", file=out)
        backend.allow_user_extensions()
    missing = 0
    for uuid, (name, purpose) in OPTIONAL_EXTENSIONS.items():
        if backend.extension_installed(uuid):
            print(f"  have       {name}", file=out)
        else:
            print(f"  installing {name} ({purpose}): answer GNOME's dialog on your screen",
                  file=out, flush=True)
            if backend.install_extension(uuid):
                print(f"  installed  {name}", file=out)
            else:
                print(f"  skipped    {name} (declined, or not available for this GNOME version)", file=out)
                missing += 1
                continue
        if uuid in ALWAYS_ON and not backend.extension_enabled(uuid):
            backend.set_extension_enabled(uuid, True)
            print(f"  enabled    {name}", file=out)

    look = app.engine.current_look()
    if look is not None:                                     # make the new pieces match the look
        result = app.engine.apply(look, app.capabilities())
        if result.changed:
            print("Re-applied the current look with what is now available.", file=out)
    print("Setup complete." if not missing else f"Setup done; {missing} extension(s) not installed.",
          file=out)
    return 0


def cmd_revert(app: App, args, out) -> int:
    count = app.engine.revert(everything=args.everything)
    print(f"Reverted {count} change{'s' if count != 1 else ''}." if count
          else "Nothing to revert.", file=out)
    return 0


def cmd_status(app: App, _args, out) -> int:
    look, default = app.engine.current_look(), app.engine.default_look()
    print(describe(look) if look else "No look applied by ricer yet.", file=out)
    if default is None:
        print("\nDefault look: none saved ('ricer default set' keeps the current one)", file=out)
    elif default == look:
        print("\nDefault look: this one", file=out)
    else:
        print(f"\nDefault look: {Path(default.wallpaper).name}, seed {default.seed} "
              "('ricer default' returns to it)", file=out)
    print("\nThis desktop:", file=out)
    for feature, available, note in app.capabilities().report():
        print(f"  {'yes' if available else 'no ':3}  {feature}{f' ({note})' if note else ''}", file=out)
    print(f"\nWallpapers: {len(app.library.scan())} in {app.paths.wallpapers}", file=out)
    return 0


def cmd_wallpapers(app: App, args, out) -> int:
    library = app.library
    if args.wallpaper_command == "list":
        found = library.scan()
        if not found:
            print(f"No wallpapers in {app.paths.wallpapers}.", file=out)
        for wallpaper in found:
            f = wallpaper.features
            print(f"{wallpaper.path}\n    warmth {f.warmth:+.2f}  colour {f.colourfulness:.2f}  "
                  f"detail {f.busyness:.2f}  brightness {f.brightness:.2f}", file=out)
        return 0
    if args.wallpaper_command == "add":
        status = 0
        for name in args.files:
            try:
                print(f"added {library.add(name)}", file=out)
            except (OSError, ValueError) as error:
                print(f"skipped {name}: {error}", file=sys.stderr)
                status = 1
        return status
    try:
        saved = wallpapers.fetch(app.paths.wallpapers, args.count, args.query)
    except OSError as error:
        print(f"Download failed: {error}", file=sys.stderr)
        return 1
    for path in saved:
        print(f"saved {path}", file=out)
    print(f"{len(saved)} new wallpaper{'s' if len(saved) != 1 else ''} in {app.paths.wallpapers}.",
          file=out)
    return 0


def cmd_widgets(app: App, args, out) -> int:
    if args.action == "start":
        if not app.capabilities().widgets:
            print("Desktop widgets need an X11 session.", file=sys.stderr)
            return 1
        print("Started." if app.daemon.start() else "Already running.", file=out)
    else:
        print("Stopped." if app.daemon.stop() else "Not running.", file=out)
    return 0


COMMANDS = {"instant": cmd_look, "reroll": cmd_look, "default": cmd_default, "setup": cmd_setup,
            "revert": cmd_revert, "status": cmd_status, "wallpapers": cmd_wallpapers,
            "widgets": cmd_widgets}


def main(argv=None, app: App | None = None, out=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    out = out or sys.stdout
    if args.command in (None, "help"):                       # bare 'ricer' gets the examples too
        return show_help(parser, getattr(args, "topic", []), out)
    if app is None:
        try:
            app = default_app()
        except Exception as error:
            print(f"ricer cannot talk to the desktop: {error}", file=sys.stderr)
            return 2
    return COMMANDS[args.command](app, args, out)


if __name__ == "__main__":
    sys.exit(main())
