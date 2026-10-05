"""Media widget: what is playing, with previous / play-pause / next buttons.

`Media` only draws and hit-tests, so it can be tested offscreen. `MprisPlayer` feeds it from
whichever MPRIS media player is active on the session bus.
"""
from __future__ import annotations

import math
import threading
import urllib.request

import cairo

from ricer.widgets.drawing import draw_bar, draw_card, draw_text, rounded_rect, set_accent_source
from ricer.widgets.style import Style

MPRIS_PREFIX = "org.mpris.MediaPlayer2."
MPRIS_PATH = "/org/mpris/MediaPlayer2"
MPRIS_IFACE = "org.mpris.MediaPlayer2.Player"
# opened by the play button when no player is running at all
LAUNCHERS = ("spotify_spotify.desktop", "spotify.desktop", "com.spotify.Client.desktop")
ACTIONS = ("Previous", "PlayPause", "Next")


def format_time(microseconds: int) -> str:
    seconds = max(0, int(microseconds // 1_000_000))
    if seconds >= 3600:
        return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60}:{seconds % 60:02d}"


def track_lines(metadata: dict, running: bool) -> tuple[str, str]:
    """(title, subtitle) for a track's MPRIS metadata."""
    title = metadata.get("xesam:title") or ("Nothing playing" if running else "No player running")
    # podcasts report an empty artist, so fall back to the show name
    artist = ", ".join(a for a in metadata.get("xesam:artist") or [] if a)
    subtitle = artist or metadata.get("xesam:album") or ("" if running else "Press play to open one")
    return title, subtitle


class Media:
    clickable = True

    def __init__(self, style: Style, _options: dict | None = None):
        self.style = style
        px = style.px
        self.width, self.height = math.ceil(px(420)), math.ceil(px(132))
        self.pad, self.art_size = px(16), px(100)
        self.text_x = self.pad * 2 + self.art_size
        self.button_y, self.button_r = px(82), px(17)
        self.buttons = {action: self.text_x + px(18 + 46 * i) for i, action in enumerate(ACTIONS)}
        # state, filled in by the player
        self.running = False
        self.playing = False
        self.metadata: dict = {}
        self.position = 0
        self.art = None                                      # GdkPixbuf, already scaled

    def tick(self, _count: int) -> bool:
        return self.playing

    def button_at(self, x: float, y: float) -> str | None:
        for action, bx in self.buttons.items():
            if math.hypot(x - bx, y - self.button_y) <= self.button_r + 3:
                return action
        return None

    def _draw_button(self, cr, action: str, cx: float) -> None:
        cy, s, r = self.button_y, self.style.px(7), self.button_r
        if action == "PlayPause":
            cr.arc(cx, cy, r, 0, 2 * math.pi)
            set_accent_source(cr, self.style, cx - r, cx + r)
            cr.fill()
            cr.set_source_rgba(*self.style.card[:3], 0.95)
            if self.playing:
                cr.rectangle(cx - s * 0.85, cy - s, s * 0.6, 2 * s)
                cr.rectangle(cx + s * 0.25, cy - s, s * 0.6, 2 * s)
            else:
                cr.move_to(cx - s * 0.6, cy - s)
                cr.line_to(cx + s, cy)
                cr.line_to(cx - s * 0.6, cy + s)
                cr.close_path()
            cr.fill()
            return
        d = 1 if action == "Next" else -1                    # mirror the glyph for "previous"
        cr.set_source_rgba(*self.style.text, 0.95)
        cr.move_to(cx - d * s, cy - s)
        cr.line_to(cx + d * s * 0.6, cy)
        cr.line_to(cx - d * s, cy + s)
        cr.close_path()
        cr.fill()
        cr.rectangle(cx + d * s * 0.7 - s * 0.2, cy - s, s * 0.4, 2 * s)
        cr.fill()

    def draw(self, cr) -> None:
        style, pad, art = self.style, self.pad, self.art_size
        draw_card(cr, style, self.width, self.height)

        rounded_rect(cr, pad, pad, art, art, style.px(12))
        if self.art is not None:
            import gi
            gi.require_version("Gdk", "3.0")
            from gi.repository import Gdk
            cr.save()
            cr.clip()
            Gdk.cairo_set_source_pixbuf(cr, self.art, pad, pad)
            cr.paint()
            cr.restore()
        else:
            placeholder = cairo.LinearGradient(pad, pad, pad + art, pad + art)
            placeholder.add_color_stop_rgba(0, *style.accent2, 0.55)
            placeholder.add_color_stop_rgba(1, *style.accent, 0.55)
            cr.set_source(placeholder)
            cr.fill()

        x, text_w = self.text_x, self.width - self.text_x - pad
        title, subtitle = track_lines(self.metadata, self.running)
        draw_text(cr, title, style.font_desc(13, "Medium"), x, style.px(14), style.text, width=text_w)
        draw_text(cr, subtitle, style.font_desc(11), x, style.px(37), style.text, alpha=0.70,
                  width=text_w)
        for action, bx in self.buttons.items():
            self._draw_button(cr, action, bx)

        length = self.metadata.get("mpris:length") or 0
        if length:
            draw_text(cr, f"{format_time(self.position)} / {format_time(length)}",
                      style.font_desc(9), self.width - pad, self.button_y - style.px(7),
                      style.text, alpha=0.65, align="right")
        draw_bar(cr, style, x + 2, self.height - pad - 2, text_w - 4,
                 self.position / length if length else 0, knob=bool(length))


def choose_player(statuses: dict[str, str], current: str | None) -> str | None:
    """Which bus name to show: stick with a playing one, else any playing, else what we had."""
    playing = sorted(name for name, status in statuses.items() if status == "Playing")
    if current in playing:
        return current
    if playing:
        return playing[0]
    if current in statuses:
        return current
    return min(statuses, default=None)


class MprisPlayer:
    """Keeps a Media widget in sync with the session's MPRIS players."""

    def __init__(self, media: Media, redraw):
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf, Gio, GLib
        self._gio, self._glib, self._pixbuf = Gio, GLib, GdkPixbuf
        self.media, self.redraw = media, redraw
        self.proxies: dict = {}
        self.current: str | None = None
        self.art_url: str | None = None
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        self.bus.signal_subscribe(
            "org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
            "/org/freedesktop/DBus", None, Gio.DBusSignalFlags.NONE, self._on_name_owner)
        names = self.bus.call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames",
            None, GLib.VariantType("(as)"), Gio.DBusCallFlags.NONE, -1, None).unpack()[0]
        for name in names:
            if name.startswith(MPRIS_PREFIX):
                self._add(name)
        self.refresh()

    # -- tracking players -----------------------------------------------
    def _add(self, name: str) -> None:
        proxy = self._gio.DBusProxy.new_sync(
            self.bus, self._gio.DBusProxyFlags.DO_NOT_AUTO_START, None, name, MPRIS_PATH,
            MPRIS_IFACE, None)
        proxy.connect("g-properties-changed", lambda *_: self.refresh())
        self.proxies[name] = proxy

    def _on_name_owner(self, _bus, _sender, _path, _iface, _signal, params) -> None:
        name, _old, new = params.unpack()
        if not name.startswith(MPRIS_PREFIX):
            return
        if new:
            self._add(name)
        else:
            self.proxies.pop(name, None)
        self.refresh()

    @staticmethod
    def _prop(proxy, name):
        value = proxy.get_cached_property(name)
        return value.unpack() if value is not None else None

    def refresh(self) -> None:
        statuses = {name: self._prop(proxy, "PlaybackStatus") for name, proxy in self.proxies.items()}
        self.current = choose_player(statuses, self.current)
        proxy = self.proxies.get(self.current)
        media = self.media
        media.running = proxy is not None
        media.playing = media.running and statuses[self.current] == "Playing"
        media.metadata = (self._prop(proxy, "Metadata") or {}) if proxy else {}
        url = media.metadata.get("mpris:artUrl")
        if url != self.art_url:
            self.art_url, media.art = url, None
            if url:
                threading.Thread(target=self._fetch_art, args=(url,), daemon=True).start()
        self.poll_position()
        self.redraw()

    # -- album art ------------------------------------------------------
    def _fetch_art(self, url: str) -> None:
        try:
            data = urllib.request.urlopen(url, timeout=10).read()
        except Exception:
            return
        self._glib.idle_add(self._set_art, url, data)

    def _set_art(self, url: str, data: bytes) -> bool:
        if url != self.art_url:
            return False
        try:
            loader = self._pixbuf.PixbufLoader()
            loader.write(data)
            loader.close()
            size = round(self.media.art_size)
            self.media.art = loader.get_pixbuf().scale_simple(
                size, size, self._pixbuf.InterpType.BILINEAR)
        except self._glib.Error:
            self.media.art = None
        self.redraw()
        return False

    # -- position and controls ------------------------------------------
    def poll_position(self) -> None:
        # Position is not announced through PropertiesChanged, so ask for it
        proxy = self.proxies.get(self.current)
        if proxy is None:
            self.media.position = 0
            return
        proxy.call(
            "org.freedesktop.DBus.Properties.Get",
            self._glib.Variant("(ss)", (MPRIS_IFACE, "Position")),
            self._gio.DBusCallFlags.NO_AUTO_START, 800, None, self._on_position)

    def _on_position(self, proxy, result) -> None:
        try:
            self.media.position = proxy.call_finish(result).unpack()[0]
        except self._glib.Error:
            return
        self.redraw()

    def press(self, action: str) -> None:
        proxy = self.proxies.get(self.current)
        if proxy is not None:
            proxy.call(action, None, self._gio.DBusCallFlags.NO_AUTO_START, -1, None, None)
        elif action == "PlayPause":
            self._launch()

    def _launch(self) -> None:
        for desktop_id in LAUNCHERS:
            try:
                app = self._gio.DesktopAppInfo.new(desktop_id)
            except TypeError:
                app = None
            if app is not None:
                app.launch([], None)
                return
