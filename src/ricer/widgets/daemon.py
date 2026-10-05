"""The widget daemon: shows the widgets listed in widgets.json and reloads when it changes.

Run with:  python -m ricer.widgets.daemon
"""
from __future__ import annotations

import json
import os
import signal
import sys

import cairo
import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk

from ricer.daemonctl import process_is_daemon
from ricer.paths import Paths
from ricer.widgets.clock import Clock
from ricer.widgets.media import Media, MprisPlayer
from ricer.widgets.style import Style
from ricer.widgets.system import System

MARGIN = 40                          # px gap between a widget and the screen edge
TOP_OFFSET = 26                      # px gap below the top bar
RELOAD_DELAY_MS = 200                # let a config write finish before reading it
WIDGETS = {"clock": Clock, "media": Media, "system": System}


def position(anchor: str, geo, width: int, height: int) -> tuple[int, int]:
    """Top-left corner for a widget of the given size at `anchor` inside the area `geo`."""
    vertical, horizontal = anchor.split("-")
    if horizontal == "left":
        x = geo.x + MARGIN
    elif horizontal == "right":
        x = geo.x + geo.width - width - MARGIN
    else:
        x = geo.x + (geo.width - width) // 2
    y = geo.y + TOP_OFFSET if vertical == "top" else geo.y + geo.height - height - MARGIN
    return x, y


class DesktopWindow(Gtk.Window):
    """Borderless transparent window on the desktop layer that shows one widget."""

    def __init__(self, widget, anchor: str, on_click=None):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        # not "self.widget": GtkWindow already has a read-only field of that name
        self.content, self.anchor, self.on_click = widget, anchor, on_click
        self.set_title(f"ricer-{type(widget).__name__.lower()}")
        self.set_decorated(False)
        self.set_app_paintable(True)
        self.set_type_hint(Gdk.WindowTypeHint.DESKTOP)
        self.set_keep_below(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(False)
        self.stick()
        self.set_default_size(widget.width, widget.height)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)

        self.connect("draw", self._draw)
        self.connect("realize", self._realize)
        self._monitors_handler = screen.connect("monitors-changed", lambda *_: self.place())
        self.connect("destroy", lambda *_: screen.disconnect(self._monitors_handler))
        if widget.clickable:
            self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
            self.connect("button-press-event", self._press)
        self.place()

    def place(self) -> None:
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        # the work area excludes the top bar and an always-visible dock
        self.move(*position(self.anchor, monitor.get_workarea(),
                            self.content.width, self.content.height))

    def _realize(self, _window) -> None:
        if not self.content.clickable:
            # empty input region: clicks fall through to the desktop underneath
            self.input_shape_combine_region(cairo.Region())

    def _draw(self, _window, cr) -> bool:
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        self.content.draw(cr)
        return False

    def _press(self, _window, event) -> bool:
        if event.button == 1 and self.on_click:
            return bool(self.on_click(event.x, event.y))
        return False


class Daemon:
    def __init__(self, paths: Paths):
        self.paths = paths
        self.windows: list[DesktopWindow] = []
        self.players: list[MprisPlayer] = []
        self.ticks = 0
        self._reload_source = 0
        config = Gio.File.new_for_path(str(paths.widgets_file))
        self.monitor = config.monitor_file(Gio.FileMonitorFlags.NONE, None)
        self.monitor.connect("changed", self._config_changed)
        self.rebuild()
        GLib.timeout_add(1000, self._tick)

    def _config_changed(self, *_args) -> None:
        if self._reload_source:
            GLib.source_remove(self._reload_source)
        self._reload_source = GLib.timeout_add(RELOAD_DELAY_MS, self._reload)

    def _reload(self) -> bool:
        self._reload_source = 0
        self.rebuild()
        return False

    def rebuild(self) -> None:
        """Throw away every window and build the set the config asks for."""
        for window in self.windows:
            window.destroy()
        self.windows, self.players = [], []
        try:
            config = json.loads(self.paths.widgets_file.read_text())
            style = Style.from_config(config)
        except (OSError, ValueError, KeyError) as error:
            print(f"ricer widgets: cannot read {self.paths.widgets_file}: {error}", file=sys.stderr)
            return
        for spec in config.get("widgets", []):
            try:
                widget = WIDGETS[spec["type"]](style, spec.get("options", {}))
            except Exception as error:                       # one bad widget must not sink the rest
                print(f"ricer widgets: skipping {spec.get('type')}: {error}", file=sys.stderr)
                continue
            window = DesktopWindow(widget, spec["anchor"])
            if isinstance(widget, Media):
                player = MprisPlayer(widget, window.queue_draw)
                window.on_click = lambda x, y, w=widget, p=player: self._media_click(w, p, x, y)
                self.players.append(player)
            self.windows.append(window)
            window.show_all()

    @staticmethod
    def _media_click(widget: Media, player: MprisPlayer, x: float, y: float) -> bool:
        action = widget.button_at(x, y)
        if action:
            player.press(action)
        return bool(action)

    def _tick(self) -> bool:
        self.ticks += 1
        for player in self.players:
            player.poll_position()
        for window in self.windows:
            if window.content.tick(self.ticks):
                window.queue_draw()
        return True


def main() -> int:
    paths = Paths.from_env()
    try:
        other = int(paths.pid_file.read_text())
    except (OSError, ValueError):
        other = 0
    if other and other != os.getpid() and process_is_daemon(other):
        print(f"ricer widgets: already running as pid {other}", file=sys.stderr)
        return 0
    if not Gtk.init_check(sys.argv)[0]:
        print("ricer widgets: no display to draw on", file=sys.stderr)
        return 1
    paths.cache.mkdir(parents=True, exist_ok=True)
    paths.pid_file.write_text(str(os.getpid()))
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, Gtk.main_quit)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, Gtk.main_quit)
    Daemon(paths)
    try:
        Gtk.main()
    finally:
        paths.pid_file.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
