"""Media widget: what is playing, with controls, in three designs.

`Media` and its designs only draw and hit-test, so they can be tested offscreen.
`MprisPlayer` feeds one from whichever MPRIS media player is active on the session bus.
"""
from __future__ import annotations

import math
import threading
import urllib.request

import cairo

from ricer import metrics
from ricer.widgets.drawing import Widget, draw_bar, draw_text, rounded_rect, set_accent_source
from ricer.widgets.style import Style

MPRIS_PREFIX = "org.mpris.MediaPlayer2."
MPRIS_PATH = "/org/mpris/MediaPlayer2"
MPRIS_IFACE = "org.mpris.MediaPlayer2.Player"
# opened by the play button when no player is running at all
LAUNCHERS = ("spotify_spotify.desktop", "spotify.desktop", "com.spotify.Client.desktop")


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


class Media(Widget):
    """The full card: cover, title, artist, three buttons, times and a progress bar."""

    clickable = True
    design = "card"

    def __init__(self, style: Style, options: dict | None = None):
        super().__init__(style, options or {})
        width, height = metrics.media_size(self.design, self.options.get("width"))
        self.width, self.height = math.ceil(style.px(width)), math.ceil(style.px(height))
        self.arrange(width, height)
        # state, filled in by the player
        self.running = False
        self.playing = False
        self.metadata: dict = {}
        self.position = 0
        self.art = None                                      # GdkPixbuf, scaled to art_size

    def arrange(self, w: float, h: float) -> None:
        """Lay the parts out for a card of logical size w x h."""
        px = self.style.px
        self.art_x = self.art_y = px(16)
        self.art_size = px(100)
        self.text_x, self.text_w = px(132), px(w - 132 - 16)
        self.title_y, self.subtitle_y = px(14), px(37)
        self.title_font, self.subtitle_font = self.style.ui(13, "Medium"), self.style.ui(11)
        self.text_align = "left"
        self.button_y, self.button_r = px(82), px(17)
        self.buttons = {action: px(132 + 18 + 46 * index)
                        for index, action in enumerate(("Previous", "PlayPause", "Next"))}
        self.bar = (px(134), px(h - 18), px(w - 134 - 18), True)          # x, y, width, knob
        # elapsed / total fits beside the buttons only on a wide card
        self.times = (px(w - 16), px(75)) if w >= 400 else None

    def tick(self, _count: int) -> bool:
        return self.playing

    def button_at(self, x: float, y: float) -> str | None:
        for action, bx in self.buttons.items():
            if math.hypot(x - bx, y - self.button_y) <= self.button_r + 3:
                return action
        return None

    def _draw_button(self, cr, action: str, cx: float) -> None:
        cy, r = self.button_y, self.button_r
        s = r * 0.42
        if action == "PlayPause":
            cr.arc(cx, cy, r, 0, 2 * math.pi)
            set_accent_source(cr, self.style, cx - r, cx + r)
            cr.fill()
            cr.set_source_rgba(*self.style.card, 0.95)
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

    def _draw_art(self, cr) -> None:
        style, x, y, size = self.style, self.art_x, self.art_y, self.art_size
        rounded_rect(cr, x, y, size, size, min(style.radius * 0.75, size / 2))
        if self.art is not None:
            import gi
            gi.require_version("Gdk", "3.0")
            from gi.repository import Gdk
            cr.save()
            cr.clip()
            Gdk.cairo_set_source_pixbuf(cr, self.art, x, y)
            cr.paint()
            cr.restore()
        else:
            placeholder = cairo.LinearGradient(x, y, x + size, y + size)
            placeholder.add_color_stop_rgba(0, *style.accent2, 0.55)
            placeholder.add_color_stop_rgba(1, *style.accent, 0.55)
            cr.set_source(placeholder)
            cr.fill()

    def draw(self, cr) -> None:
        style = self.style
        self.draw_card(cr)
        self._draw_art(cr)
        title, subtitle = track_lines(self.metadata, self.running)
        anchor = self.text_x + (self.text_w / 2 if self.text_align == "center" else 0)
        draw_text(cr, title, self.title_font, anchor, self.title_y, style.text, width=self.text_w,
                  align=self.text_align, shadow=self.bare)
        draw_text(cr, subtitle, self.subtitle_font, anchor, self.subtitle_y, style.text, alpha=0.70,
                  width=self.text_w, align=self.text_align, shadow=self.bare)
        for action, bx in self.buttons.items():
            self._draw_button(cr, action, bx)

        length = self.metadata.get("mpris:length") or 0
        if length and self.times:
            draw_text(cr, f"{format_time(self.position)} / {format_time(length)}", style.ui(9),
                      *self.times, style.text, alpha=0.65, align="right", shadow=self.bare)
        x, y, width, knob = self.bar
        draw_bar(cr, style, x, y, width, self.position / length if length else 0,
                 knob=knob and bool(length), line_width=3 if knob else 2)


class MediaPill(Media):
    """A small strip: cover, title, artist, play and next."""

    design = "pill"

    def arrange(self, w: float, h: float) -> None:
        px = self.style.px
        self.art_x = self.art_y = px(10)
        self.art_size = px(48)
        self.text_x, self.text_w = px(70), px(w - 70 - 96)
        self.title_y, self.subtitle_y = px(13), px(34)
        self.title_font, self.subtitle_font = self.style.ui(12, "Medium"), self.style.ui(10)
        self.text_align = "left"
        self.button_y, self.button_r = px(h / 2), px(15)
        self.buttons = {"PlayPause": px(w - 68), "Next": px(w - 28)}
        self.bar = (px(70), px(h - 7), px(w - 70 - 96), False)
        self.times = None


class MediaCover(Media):
    """Big cover art on top, the track and controls underneath."""

    design = "cover"

    def arrange(self, w: float, h: float) -> None:
        px = self.style.px
        art = w - 32
        self.art_x = self.art_y = px(16)
        self.art_size = px(art)
        self.text_x, self.text_w = px(16), px(art)
        self.title_y, self.subtitle_y = px(16 + art + 10), px(16 + art + 33)
        self.title_font, self.subtitle_font = self.style.ui(13, "Medium"), self.style.ui(11)
        self.text_align = "center"
        self.button_y, self.button_r = px(16 + art + 84), px(17)
        self.buttons = {action: px(w / 2 + 48 * (index - 1))
                        for index, action in enumerate(("Previous", "PlayPause", "Next"))}
        self.bar = (px(18), px(16 + art + 60), px(art - 4), True)
        self.times = None


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
        self.closed = False
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        self._subscription = self.bus.signal_subscribe(
            "org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
            "/org/freedesktop/DBus", None, Gio.DBusSignalFlags.NONE, self._on_name_owner)
        names = self.bus.call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames",
            None, GLib.VariantType("(as)"), Gio.DBusCallFlags.NONE, -1, None).unpack()[0]
        for name in names:
            if name.startswith(MPRIS_PREFIX):
                self._add(name)
        self.refresh()

    def close(self) -> None:
        """Stop listening. Without this a reloaded daemon keeps every old player alive."""
        self.closed = True
        self.bus.signal_unsubscribe(self._subscription)
        self.proxies.clear()

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
        if self.closed:
            return
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
        if self.closed or url != self.art_url:
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
        if not self.closed:
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


DESIGNS = {"card": Media, "pill": MediaPill, "cover": MediaCover}
