"""Command line: ricer instant | revert | status | wallpapers | widgets."""
from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass

from ricer import __version__, wallpapers
from ricer.capabilities import Capabilities, detect
from ricer.daemonctl import DaemonControl
from ricer.engine import ApplyError, Engine, build_plan
from ricer.generator import generate
from ricer.look import DIAL_MAX, DIAL_MIN, Dials, Look
from ricer.paths import Paths
from ricer.wallpapers import Library, NoWallpapersError

DEFAULT_DIAL = 5
DEFAULT_FETCH = 12


@dataclass
class App:
    """Everything a command needs. Tests build one around fakes."""
    paths: Paths
    backend: object
    daemon: object
    env: dict | None = None

    @property
    def library(self) -> Library:
        return Library(self.paths.wallpapers, self.paths.wallpaper_cache)

    @property
    def engine(self) -> Engine:
        return Engine(self.backend, self.paths, self.daemon)

    def capabilities(self) -> Capabilities:
        return detect(self.backend, self.paths, self.env)


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ricer", description="Instant desktop ricing for GNOME, driven by three dials.")
    parser.add_argument("--version", action="version", version=f"ricer {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")

    instant = commands.add_parser(
        "instant", help="generate a look from the dials and apply it",
        description="Each dial goes from 1 to 10. Unset dials default to 5. "
                    "The same dials always give the same look.")
    instant.add_argument("--cool", type=dial, metavar="N",
                         help="flashiness: 1 calm and minimal, 10 loud and flashy")
    instant.add_argument("--ease", type=dial, metavar="N",
                         help="practicality: 1 looks first, 10 usability first")
    instant.add_argument("--warmth", type=dial, metavar="N",
                         help="mood: 1 cold blues, 10 warm ambers")
    instant.add_argument("--all", type=dial, metavar="N", dest="all_dials",
                         help="set all three dials at once (single dials still override)")
    variant = instant.add_mutually_exclusive_group()
    variant.add_argument("--shuffle", action="store_true",
                         help="a different variant for the same dials; prints its seed")
    variant.add_argument("--seed", type=int, metavar="N", help="reproduce a shuffled variant")
    instant.add_argument("--dry-run", action="store_true",
                         help="show the look without changing anything")
    instant.add_argument("--json", action="store_true", help="print the look as JSON")

    revert = commands.add_parser("revert", help="undo the last 'instant'")
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


def dials_from(args) -> Dials:
    base = args.all_dials if args.all_dials is not None else DEFAULT_DIAL
    return Dials(*(base if value is None else value
                   for value in (args.cool, args.ease, args.warmth)))


def describe(look: Look) -> str:
    dials, dock = look.dials, look.dock
    widgets = ", ".join(f"{w.type} ({w.anchor})" for w in look.widgets) or "none"
    lines = [
        f"cool {dials.cool} · ease {dials.ease} · warmth {dials.warmth}"
        + (f" · seed {look.seed}" if look.seed else ""),
        f"  wallpaper  {look.wallpaper}",
        f"  colours    {look.palette.accent} / {look.palette.accent2}"
        f"{' gradient' if look.gradient else ''}, theme accent {look.gtk_accent}",
        f"  top bar    {look.bar_style}{', blur on' if look.blur else ''}",
        f"  dock       {'auto-hide' if dock.autohide else 'always visible'}, "
        f"{'floating' if dock.floating else 'full width'}, {dock.icon_size}px icons",
        f"  widgets    {widgets}",
    ]
    return "\n".join(lines)


def cmd_instant(app: App, args, out) -> int:
    seed = args.seed or 0
    if args.shuffle:
        seed = random.SystemRandom().randrange(1, 2 ** 31)
    caps = app.capabilities()
    if not caps.gnome and not args.dry_run:
        print("ricer only supports the GNOME desktop; nothing was changed.", file=sys.stderr)
        return 2
    try:
        look = generate(dials_from(args), app.library.scan(), seed)
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
        result = app.engine.apply(look, caps)
    except ApplyError as error:
        print(error, file=sys.stderr)
        return 1
    for notice in result.notices:
        print(f"note: {notice}", file=out)
    print("Applied." if result.changed else "No changes: this look is already applied.", file=out)
    if args.shuffle:
        print(f"Reproduce this variant with --seed {seed}", file=out)
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


COMMANDS = {"instant": cmd_instant, "revert": cmd_revert, "status": cmd_status,
            "wallpapers": cmd_wallpapers, "widgets": cmd_widgets}


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
