import time

import pytest

pytest.importorskip("gi")
cairo = pytest.importorskip("cairo")

from ricer.engine import widgets_config  # noqa: E402
from ricer.generator import generate  # noqa: E402
from ricer.look import Dials  # noqa: E402
from ricer.widgets import system  # noqa: E402
from ricer.widgets.clock import Clock  # noqa: E402
from ricer.widgets.media import Media, choose_player, format_time, track_lines  # noqa: E402
from ricer.widgets.style import Style  # noqa: E402

from test_system import root  # noqa: E402,F401  (fixture)

NOON = time.struct_time((2026, 10, 5, 15, 7, 30, 0, 278, 0))


@pytest.fixture
def style(wallpaper_set, full_caps):
    return Style.from_config(widgets_config(generate(Dials(8, 5, 5), wallpaper_set), full_caps))


def render(widget):
    """Draw a widget offscreen and return (surface, share of pixels that got painted)."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, widget.width, widget.height)
    widget.draw(cairo.Context(surface))
    surface.flush()
    alpha = bytes(surface.get_data())[3::4]
    return surface, sum(1 for a in alpha if a) / len(alpha)


def pixel(surface, x, y):
    data = surface.get_data()
    offset = int(y) * surface.get_stride() + int(x) * 4
    b, g, r, a = data[offset:offset + 4]
    return r, g, b, a


def test_style_comes_from_the_engine_config(style, wallpaper_set, full_caps):
    look = generate(Dials(8, 5, 5), wallpaper_set)
    assert style.font == "Ubuntu Sans" and style.scale == look.widget_scale
    assert style.card[3] == look.palette.card_alpha and len(style.accent) == 3
    assert style.font_desc(10, "Medium") == f"Ubuntu Sans Medium {10 * style.scale:g}"


def test_clock_draws_and_grows_with_its_size(style):
    small = Clock(style, {"size": 64}, now=lambda: NOON)
    large = Clock(style, {"size": 140}, now=lambda: NOON)
    assert large.width > small.width and large.height > small.height
    assert 0.02 < render(large)[1] < 0.6
    assert small.tick(1)


def test_clock_options_change_its_height_and_text(style):
    full = Clock(style, {"size": 100}, now=lambda: NOON)
    bare = Clock(style, {"size": 100, "seconds": False, "date": False}, now=lambda: NOON)
    assert bare.height < full.height
    assert full.time_text(NOON) == "15:07" and full.date_text(NOON) == "MONDAY, OCTOBER 5"
    twelve = Clock(Style(**{**style.__dict__, "clock_24h": False}), {}, now=lambda: NOON)
    assert twelve.time_text(NOON) == "3:07" and twelve.date_text(NOON).endswith("PM")


def test_media_card_draws_idle_and_playing(style):
    media = Media(style)
    surface, covered = render(media)
    assert covered > 0.9                                  # the card fills the window
    idle = bytes(surface.get_data())
    media.running = media.playing = True
    media.metadata = {"xesam:title": "A Song", "xesam:artist": ["Someone"], "mpris:length": 200_000_000}
    media.position = 100_000_000
    assert bytes(render(media)[0].get_data()) != idle
    assert media.tick(1) is True


def test_media_buttons_hit_test(style):
    media = Media(style)
    for action, x in media.buttons.items():
        assert media.button_at(x, media.button_y) == action
    assert media.button_at(5, 5) is None
    assert media.button_at(media.buttons["Next"] + media.button_r * 3, media.button_y) is None


def test_track_lines_cover_songs_podcasts_and_nothing():
    assert track_lines({"xesam:title": "T", "xesam:artist": ["A", "B"]}, True) == ("T", "A, B")
    assert track_lines({"xesam:title": "Ep 1", "xesam:artist": [""], "xesam:album": "Show"}, True) == ("Ep 1", "Show")
    assert track_lines({}, True) == ("Nothing playing", "")
    assert track_lines({}, False)[0] == "No player running"


def test_format_time():
    assert format_time(83_000_000) == "1:23"
    assert format_time(16_270_000_000) == "4:31:10"
    assert format_time(-5) == "0:00"


def test_choose_player_prefers_what_is_playing():
    spotify, firefox = "org.mpris.MediaPlayer2.spotify", "org.mpris.MediaPlayer2.firefox"
    assert choose_player({}, None) is None
    assert choose_player({spotify: "Paused", firefox: "Playing"}, spotify) == firefox
    assert choose_player({spotify: "Playing", firefox: "Playing"}, spotify) == spotify
    assert choose_player({spotify: "Paused", firefox: "Paused"}, spotify) == spotify
    assert choose_player({firefox: "Paused"}, spotify) == firefox


def test_system_widget_drops_rows_without_a_sensor(style, root, monkeypatch):  # noqa: F811
    monkeypatch.setattr(system, "gpu_temperature", lambda _root: None)
    widget = system.System(style, {"rows": ["cpu", "ram", "temp", "gpu", "battery"]}, root=root)
    assert widget.rows == ["cpu", "ram", "temp", "battery"]
    shorter = system.System(style, {"rows": ["cpu", "ram"]}, root=root)
    assert shorter.height < widget.height
    assert render(widget)[1] > 0.9


def test_system_widget_samples_cpu_every_other_tick(style, root):  # noqa: F811
    widget = system.System(style, {"rows": ["cpu", "ram"]}, root=root)
    assert widget.tick(1) is False
    (root / "proc/stat").write_text("cpu  150 0 150 750 100 0 0 0 0 0\n")
    assert widget.tick(2) is True
    assert widget.cpu == pytest.approx(2 / 3)
    assert widget.reading("cpu")[1] == "67%"


def test_hot_temperature_is_flagged(style, root, monkeypatch):  # noqa: F811
    widget = system.System(style, {"rows": ["temp"]}, root=root)
    assert widget.reading("temp") == (pytest.approx(32 / 70), "62°C", False)
    monkeypatch.setattr(system, "cpu_temperature", lambda _root: 91.0)
    assert widget.reading("temp")[1:] == ("91°C", True)


def test_flat_style_paints_the_bar_in_one_colour(style):
    from ricer.widgets.drawing import draw_bar
    flat = Style(**{**style.__dict__, "gradient": False})
    for variant, expect_same in ((flat, True), (style, False)):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 20)
        draw_bar(cairo.Context(surface), variant, 10, 10, 180, 1.0, line_width=6)
        surface.flush()
        assert (pixel(surface, 20, 10)[:3] == pixel(surface, 180, 10)[:3]) is expect_same
