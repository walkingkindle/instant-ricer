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
from ricer.placement import arrange
from ricer.widgets.catalog import build
from ricer.widgets.media import Media, MprisPlayer
from ricer.widgets.style import Style

RELOAD_DELAY_MS = 200                # let a config write finish before reading it


class DesktopWindow(Gtk.Window):
    """Borderless transparent window on the desktop layer that shows one widget."""

    def __init__(self, widget, kind: str, anchor: str, on_click=None):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        # not "self.widget": GtkWindow already has a read-only field of that name
        self.content, self.anchor, self.on_click = widget, anchor, on_click
        self.set_title(f"ricer-{kind}")
        self.set_decorated(False)
        self.set_app_paintable(True)
        self.set_type_hint(Gdk.WindowTypeHint.DESKTOP)
        self.set_keep_below(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(False)
        self.stick()
        self._size = (widget.width, widget.height)
        self._spot = None
        self.set_default_size(*self._size)

        visual = self.get_screen().get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)

        self.connect("draw", self._draw)
        self.connect("realize", self._realize)
        if widget.clickable:
            self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
            self.connect("button-press-event", self._press)

    def sync_size(self) -> bool:
        """Follow the widget if it changed size (a calendar gaining a row). True if it did."""
        size = (self.content.width, self.content.height)
        if size == self._size:
            return False
        self._size = size
        self.resize(*size)
        return True

    def move_to(self, spot: tuple[int, int]) -> None:
        if spot != self._spot:
            self._spot = spot
            self.move(*spot)

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
        self.insets = (0, 0, 0)
        self.ticks = 0
        self._reload_source = 0
        config = Gio.File.new_for_path(str(paths.widgets_file))
        self.monitor = config.monitor_file(Gio.FileMonitorFlags.NONE, None)
        self.monitor.connect("changed", self._config_changed)
        Gdk.Screen.get_default().connect("monitors-changed", lambda *_: self.layout())
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
        for player in self.players:
            player.close()
        for window in self.windows:
            window.destroy()
        self.windows, self.players = [], []
        try:
            config = json.loads(self.paths.widgets_file.read_text())
            style = Style.from_config(config)
            self.insets = tuple(config.get("insets", (0, 0, 0)))
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f"ricer widgets: cannot read {self.paths.widgets_file}: {error}", file=sys.stderr)
            return
        for spec in config.get("widgets", []):
            try:
                widget = build(style, spec)
            except Exception as error:                       # one bad widget must not sink the rest
                print(f"ricer widgets: skipping {spec.get('type')}: {error}", file=sys.stderr)
                continue
            window = DesktopWindow(widget, spec["type"], spec["anchor"])
            if isinstance(widget, Media):
                player = MprisPlayer(widget, window.queue_draw)
                window.on_click = lambda x, y, w=widget, p=player: self._media_click(w, p, x, y)
                self.players.append(player)
            self.windows.append(window)
        self.layout()
        for window in self.windows:
            window.show_all()

    def layout(self) -> None:
        """Put every window in its zone of the primary monitor's work area."""
        if not self.windows:
            return
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        # the work area excludes the top bar and an always-visible dock
        area = monitor.get_workarea()
        items = [(window.anchor, window.content.width, window.content.height) for window in self.windows]
        spots = arrange(items, (area.x, area.y, area.width, area.height), self.insets)
        for window, spot in zip(self.windows, spots):
            window.move_to(spot)

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
                window.sync_size()
                window.queue_draw()
        # GTK does not announce work-area changes (a dock starting or ceasing to hide), so the
        # layout is re-checked each tick; windows only move when their spot changed
        self.layout()
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
