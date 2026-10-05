"""Command line: ricer instant | reroll | setup | revert | status | wallpapers | widgets."""
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
    parser.add_argument("--cool", type=dial, metavar="N",
                        help="flashiness: 1 calm and minimal, 10 loud and flashy")
    parser.add_argument("--ease", type=dial, metavar="N",
                        help="practicality: 1 looks first, 10 usability first")
    parser.add_argument("--warmth", type=dial, metavar="N",
                        help="mood: 1 cold blues, 10 warm ambers")
    parser.add_argument("--chaos", type=dial, metavar="N",
                        help="how far a run may stray from what the other dials suggest")
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
        prog="ricer", description="Instant desktop ricing for GNOME: four dials, a new look every run.")
    parser.add_argument("--version", action="version", version=f"ricer {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")

    instant = commands.add_parser(
        "instant", help="generate a new look from the dials and apply it",
        description="Each dial goes from 1 to 10; dials you leave out are 5. Every run is "
                    "different. The dials tilt the odds, and --seed brings a look back.")
    _look_options(instant, "set cool, ease and warmth at once (single dials still override)")

    reroll = commands.add_parser(
        "reroll", help="another look with the current look's dials",
        description="Like 'instant', but dials you leave out stay as they are in the current look.")
    _look_options(reroll, "set cool, ease and warmth at once (single dials still override)")

    commands.add_parser("setup", help="install the optional GNOME extensions ricer can use")

    revert = commands.add_parser("revert", help="undo the last look")
    revert.add_argument("--all", action="store_true", dest="everything",
                        help="undo everything ricer ever changed")

    commands.add_parser("status", help="show the current look and what this desktop supports")

    walls = commands.add_parser("wallpapers", help="manage the wallpaper library")
    wall_commands = walls.add_subparsers(dest="wallpaper_command", required=True, metavar="action")
    wall_commands.add_parser("list", help="list wallpapers with their measured mood")
    add = wall_commands.add_parser("add", help="copy images into the library")
    add.add_argument("files", nargs="+")
    fetch = wall_commands.add_parser("fetch", help="download SFW wallpapers from Wallhaven")
    fetch.add_argument("--count", type=int, default=DEFAULT_FETCH, metavar="N",
                       help=f"how many new images to get (default {DEFAULT_FETCH})")
    fetch.add_argument("--query", default=wallpapers.DEFAULT_QUERY,
                       help=f"search words (default: {wallpapers.DEFAULT_QUERY!r})")

    widgets = commands.add_parser("widgets", help="start or stop the desktop widgets")
    widgets.add_argument("action", choices=("start", "stop"))
    return parser


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
    cards = "no cards" if style.fill == 0 else f"{style.border} cards at {round(style.fill * 100)}%"
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
    look = app.engine.current_look()
    print(describe(look) if look else "No look applied by ricer yet.", file=out)
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


COMMANDS = {"instant": cmd_look, "reroll": cmd_look, "setup": cmd_setup, "revert": cmd_revert,
            "status": cmd_status, "wallpapers": cmd_wallpapers, "widgets": cmd_widgets}


def main(argv=None, app: App | None = None, out=None) -> int:
    args = build_parser().parse_args(argv)
    out = out or sys.stdout
    if app is None:
        try:
            app = default_app()
        except Exception as error:
            print(f"ricer cannot talk to the desktop: {error}", file=sys.stderr)
            return 2
    return COMMANDS[args.command](app, args, out)


if __name__ == "__main__":
    sys.exit(main())
