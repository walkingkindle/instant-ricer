import dataclasses
import datetime
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("gi")
cairo = pytest.importorskip("cairo")

from ricer import metrics  # noqa: E402
from ricer.look import DESIGNS  # noqa: E402
from ricer.palette import hex_to_rgb  # noqa: E402
from ricer.widgets import calendars, clock, drawing, greeting, media, ornament, progress, system  # noqa: E402
from ricer.widgets.catalog import CATALOG, build  # noqa: E402
from ricer.widgets.style import Style  # noqa: E402

from test_system import root  # noqa: E402,F401  (fixture)

EVENING = time.struct_time((2026, 10, 5, 18, 56, 41, 0, 278, 0))
TODAY = datetime.date(2026, 10, 5)
MOMENT = datetime.datetime(2026, 10, 5, 18, 0, 0)
TRACK = {"xesam:title": "A Song", "xesam:artist": ["Someone"], "mpris:length": 200_000_000}


def make_style(**overrides):
    base = dict(accent=hex_to_rgb("#f2c27d"), accent2=hex_to_rgb("#b88cff"), text=hex_to_rgb("#f2f7ff"),
                hot=hex_to_rgb("#ff6b6b"), card=hex_to_rgb("#14121f"), fill=0.58, border="hairline",
                radius=16, weight=0.3, font="Sans", display="Sans", caps=True, gradient=True, scale=1.0)
    return Style(**{**base, **overrides})


STYLES = {
    "glass": make_style(),
    "bare": make_style(fill=0.0, border="none", caps=False, display="Serif", gradient=False),
    "big outline": make_style(border="accent", radius=4, weight=0.9, display="Monospace", scale=1.25),
}
OPTIONS = {
    "clock": {"size": 90, "seconds": True, "date": True},
    "greeting": {"size": 24},
    "system": {"rows": ["cpu", "ram", "temp"]},
    "progress": {"rows": ["day", "week", "month", "year"]},
    "ornament": {"size": 180, "seed": 7},
}
ALL = [(kind, design) for kind, designs in DESIGNS.items() for design in designs]


def make(kind, design, style, root=None, **extra):   # noqa: F811
    options = {**OPTIONS.get(kind, {}), "fill": style.fill, **extra}
    cls = CATALOG[kind][design]
    if kind == "clock":
        return cls(style, options, now=lambda: EVENING)
    if kind == "greeting":
        return cls(style, options, now=lambda: EVENING, name="Aleksa")
    if kind == "calendar":
        return cls(style, options, today=lambda: TODAY)
    if kind == "progress":
        return cls(style, options, now=lambda: MOMENT)
    if kind == "system":
        return cls(style, options, root=root)
    widget = cls(style, options)
    if kind == "media":
        widget.running = widget.playing = True
        widget.metadata, widget.position = dict(TRACK), 100_000_000
    return widget


def render(widget):
    """Draw a widget offscreen; returns (surface, context, share of pixels painted)."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, widget.width, widget.height)
    cr = cairo.Context(surface)
    widget.draw(cr)
    surface.flush()
    alpha = bytes(surface.get_data())[3::4]
    return surface, cr, sum(1 for a in alpha if a) / len(alpha)


def pixel(surface, x, y):
    data = surface.get_data()
    offset = int(y) * surface.get_stride() + int(x) * 4
    b, g, r, a = data[offset:offset + 4]
    return r, g, b, a


# -- every design -----------------------------------------------------------------------------

def test_the_catalog_draws_exactly_the_designs_a_look_may_name():
    assert {kind: tuple(designs) for kind, designs in CATALOG.items()} == DESIGNS


@pytest.mark.parametrize("kind, design", ALL)
@pytest.mark.parametrize("style_name", STYLES)
def test_every_design_draws_under_every_style(kind, design, style_name, root):  # noqa: F811
    widget = make(kind, design, STYLES[style_name], root)
    assert widget.width > 20 and widget.height > 20
    _surface, cr, painted = render(widget)
    assert painted > 0.01
    assert not cr.has_current_point()        # nothing left behind to grow a stray line from
    assert isinstance(widget.tick(60), bool)


@pytest.mark.parametrize("kind, design", [pair for pair in ALL if pair[0] in metrics.STRUCTURED])
def test_card_designs_are_exactly_the_size_the_planner_expects(kind, design, root):  # noqa: F811
    for style in STYLES.values():
        widget = make(kind, design, style, root)
        expected = metrics.nominal(kind, design, widget.options, style.scale)
        if (kind, design) == ("calendar", "month"):
            assert widget.width == expected[0] and widget.height <= expected[1]   # planned for 6 weeks
        else:
            assert (widget.width, widget.height) == expected


@pytest.mark.parametrize("kind, design", [pair for pair in ALL if pair[0] in ("clock", "greeting", "ornament")])
def test_text_designs_stay_within_the_planners_estimate(kind, design):
    for display in ("Sans", "Serif", "Monospace"):
        for weight in (0.1, 0.9):
            for size in ((60, 100, 140) if kind == "clock" else (20, 30) if kind == "greeting" else (140, 300)):
                style = make_style(display=display, weight=weight, fill=0.0)
                widget = make(kind, design, style, size=size)
                estimate = metrics.nominal(kind, design, widget.options, style.scale)
                assert widget.width <= estimate[0] * 1.25, (display, weight, size)
                assert widget.height <= estimate[1] * 1.25, (display, weight, size)
                assert widget.width >= estimate[0] * 0.4 and widget.height >= estimate[1] * 0.5


@pytest.mark.parametrize("kind, design", sorted(metrics.WIDTH_AWARE))
def test_a_width_can_be_imposed_so_stacked_cards_line_up(kind, design, root):  # noqa: F811
    for style in (STYLES["glass"], STYLES["big outline"]):
        widget = make(kind, design, style, root, width=420)
        assert widget.width == round(420 * style.scale)
        assert render(widget)[2] > 0.5


@pytest.mark.parametrize("kind, design", ALL)
def test_a_card_is_drawn_only_when_the_widget_has_a_fill(kind, design, root):  # noqa: F811
    if kind == "ornament" or (kind, design) == ("clock", "analog"):
        return                                # these never sit in a rectangular card
    carded, _, covered = render(make(kind, design, make_style(fill=0.6, radius=0), root))
    bare, _, uncovered = render(make(kind, design, make_style(fill=0.0, radius=0), root))
    assert pixel(carded, 2, 2)[3] > 100 and covered > 0.95
    assert pixel(bare, 2, 2)[3] == 0 and uncovered < covered


# -- style and drawing ------------------------------------------------------------------------

def test_style_reads_the_engines_config(wallpaper_set, full_caps):
    from ricer.engine import widgets_config
    from ricer.generator import generate
    from ricer.look import Dials
    look = generate(Dials(8, 5, 5), wallpaper_set, 2)
    look = dataclasses.replace(look, style=dataclasses.replace(look.style, voice="serif"))
    style = Style.from_config(widgets_config(look, full_caps))
    assert (style.font, style.display) == ("Ubuntu Sans", "Noto Serif Display")
    assert (style.fill, style.radius, style.scale) == (look.style.fill, look.style.radius, look.style.scale)
    assert len(style.accent) == 3 and style.card == hex_to_rgb(look.palette.card)


def test_weight_and_fonts():
    names = [make_style(weight=w).weight_name() for w in (0.0, 0.2, 0.5, 0.65, 0.8, 1.0)]
    assert names == ["Thin", "Light", "", "Medium", "Semi-Bold", "Bold"]
    style = make_style(weight=0.5, scale=1.5, font="Inter", display="Fraunces")
    assert style.weight_name(0.4) == "Bold" and style.weight_name(-0.4) == "Thin"
    assert style.ui(10) == "Inter 15" and style.ui(10, "Medium") == "Inter Medium 15"
    assert style.show(80) == "Fraunces 80" and style.show(80, 0.4) == "Fraunces Bold 80"
    assert style.label("Temp") == "TEMP" and make_style(caps=False).label("Temp") == "Temp"
    assert make_style(caps=False).label_spacing == 0 < style.label_spacing


def test_draw_card_borders_and_bare():
    def corner(**style):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 120, 60)
        drawing.draw_card(cairo.Context(surface), make_style(radius=0, **style), 120, 60, style.get("fill", 0.5))
        surface.flush()
        return pixel(surface, 1, 30), pixel(surface, 60, 30)

    edge, middle = corner(border="accent", fill=0.5)
    assert edge[0] > edge[2] and middle[3] > 0               # an amber edge on a dark card
    assert corner(border="none", fill=0.5)[0] == corner(border="none", fill=0.5)[1]
    assert corner(border="accent", fill=0.0) == ((0, 0, 0, 0), (0, 0, 0, 0))   # bare means nothing at all


def test_a_flat_style_paints_bars_in_one_colour_and_a_gradient_in_two():
    for style, same in ((make_style(gradient=False), True), (make_style(gradient=True), False)):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 20)
        drawing.draw_bar(cairo.Context(surface), style, 10, 10, 180, 1.0, line_width=6)
        surface.flush()
        assert (pixel(surface, 20, 10)[:3] == pixel(surface, 180, 10)[:3]) is same


def test_bars_start_past_the_longest_label():
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 300, 120)
    style = make_style()
    rows = [("Day", 1.0, "100%", False), ("A very long label", 1.0, "100%", True)]
    drawing.draw_rows(cairo.Context(surface), style, rows, 300, bare=False)
    surface.flush()
    label_end = 18 + drawing.measure_text("A VERY LONG LABEL", style.ui(9), style.label_spacing)[0]
    assert pixel(surface, label_end + 6, 34)[3] == 0         # a gap, not a bar, right after the label
    assert pixel(surface, label_end + 20, 34)[3] > 0         # then both bars begin together
    hot = pixel(surface, label_end + 40, 66)
    assert hot[0] > 200 and hot[2] < 150                     # the hot row is painted red


def test_align_x():
    assert [drawing.align_x(a, 200, 10) for a in ("left", "center", "right")] == [10, 100, 190]


# -- clock ------------------------------------------------------------------------------------

@pytest.mark.parametrize("hour, minute, expected", [
    (18, 0, ("six", "o'clock")), (18, 2, ("six", "o'clock")), (18, 5, ("five past", "six")),
    (18, 17, ("quarter past", "six")), (18, 30, ("half past", "six")), (18, 35, ("twenty-five to", "seven")),
    (18, 45, ("quarter to", "seven")), (18, 56, ("five to", "seven")), (18, 58, ("seven", "o'clock")),
    (23, 58, ("twelve", "o'clock")), (0, 20, ("twenty past", "twelve")), (11, 40, ("twenty to", "twelve")),
])
def test_time_in_words(hour, minute, expected):
    assert clock.time_in_words(hour, minute) == expected


def test_clock_text_in_both_hour_formats():
    twenty_four, twelve = make_style(), make_style(clock_24h=False)
    assert clock.time_text(twenty_four, EVENING) == "18:56" and clock.time_text(twelve, EVENING) == "6:56"
    assert clock.long_date(EVENING) == "Monday, October 5" and clock.short_date(EVENING) == "Mon 5 Oct"
    digital = make("clock", "digital", twelve)
    assert digital.date_line(EVENING) == "MONDAY, OCTOBER 5 · PM"
    assert make("clock", "digital", make_style(caps=False)).date_line(EVENING) == "Monday, October 5"


def test_clock_options_change_its_size():
    style = make_style(fill=0.0)
    full = make("clock", "digital", style)
    assert make("clock", "digital", style, seconds=False, date=False).height < full.height
    assert make("clock", "digital", style, size=140).width > full.width
    assert make("clock", "analog", style, size=100, date=False).height == 208
    assert make("clock", "stacked", style).height > make("clock", "stacked", style, date=False).height


def test_a_clock_redraws_each_second_only_if_it_shows_seconds():
    moment = [EVENING]
    quiet = clock.DigitalClock(make_style(), {"seconds": False}, now=lambda: moment[0])
    assert quiet.tick(1) is True and quiet.tick(2) is False          # first draw, then idle
    moment[0] = time.struct_time((2026, 10, 5, 18, 57, 0, 0, 278, 0))
    assert quiet.tick(3) is True                                       # the minute turned
    lively = clock.AnalogClock(make_style(), {"seconds": True}, now=lambda: EVENING)
    assert lively.tick(1) and lively.tick(2)


def test_the_stacked_clock_paints_minutes_in_the_accent():
    widget = make("clock", "stacked", make_style(fill=0.0, gradient=False), date=False, size=120)
    surface, _, _ = render(widget)
    def reddest(y0, y1):
        best = (0, 0, 0)
        for y in range(y0, y1, 3):
            for x in range(0, widget.width, 3):
                r, g, b, a = pixel(surface, x, y)
                if a > 200 and r + g + b > sum(best):
                    best = (r, g, b)
        return best
    top, bottom = reddest(0, widget.height // 2 - 10), reddest(widget.height // 2 + 10, widget.height)
    assert top[2] > 235                                      # hours: near-white text
    assert bottom[0] > bottom[2] + 60                        # minutes: amber, far less blue


# -- greeting ---------------------------------------------------------------------------------

@pytest.mark.parametrize("hour, text", [(4, "Good night"), (5, "Good morning"), (11, "Good morning"),
                                        (12, "Good afternoon"), (17, "Good afternoon"),
                                        (18, "Good evening"), (22, "Good evening"), (23, "Good night")])
def test_greeting_for(hour, text):
    assert greeting.greeting_for(hour) == text


def test_first_name_comes_from_the_account():
    assert greeting.first_name(lambda uid: SimpleNamespace(pw_gecos="Ada Lovelace,,,", pw_name="ada")) == "Ada"
    assert greeting.first_name(lambda uid: SimpleNamespace(pw_gecos="", pw_name="ada")) == "Ada"
    def missing(uid):
        raise KeyError(uid)
    assert greeting.first_name(missing) == ""


def test_greeting_lines_and_redraw():
    widget = make("greeting", "plain", make_style())
    assert widget.line(18) == "Good evening, Aleksa"
    assert greeting.Greeting(make_style(), {"name": False}, now=lambda: EVENING).line(9) == "Good morning"
    assert greeting.Greeting(make_style(), {}, now=lambda: EVENING, name="").line(9) == "Good morning"
    assert widget.tick(1) is True and widget.tick(2) is False


# -- calendar ---------------------------------------------------------------------------------

def test_month_calendar_grows_and_shrinks_with_the_month():
    day = [datetime.date(2026, 2, 10)]                       # Feb 2026: Sunday start, exactly 4 weeks? no: 5
    widget = calendars.MonthCalendar(make_style(), {}, today=lambda: day[0])
    weeks = {}
    for month_day in (datetime.date(2026, 2, 10), datetime.date(2026, 3, 10), datetime.date(2026, 8, 10)):
        day[0] = month_day
        assert widget.tick(1) is True and widget.tick(2) is False
        weeks[len(widget.weeks())] = widget.height
    assert len(weeks) >= 2 and sorted(weeks.values()) == [weeks[n] for n in sorted(weeks)]
    assert widget.weeks()[0][-1] in (1, 2)                   # weeks start on Monday: Aug 1 2026 is a Saturday


def test_calendars_highlight_today():
    style = make_style(gradient=False, fill=0.6)
    amber = lambda p: p[0] > 200 and p[2] < 160 and p[3] > 200   # noqa: E731

    week = make("calendar", "week", style)
    surface, _, _ = render(week)
    column = (week.width - 2 * week.pad) / 7
    assert amber(pixel(surface, week.pad + column * 0.5, week.height * 0.72))       # Monday the 5th
    assert not amber(pixel(surface, week.pad + column * 2.5, week.height * 0.72))

    month = make("calendar", "month", style)
    surface, _, _ = render(month)
    cell = (month.width - 2 * month.pad) / 7
    row_h = cell * 0.86
    today_y = style.px(62) + 1 * row_h + row_h / 2           # the 5th is in the second week row
    assert amber(pixel(surface, month.pad + cell * 0.5 + cell * 0.3, today_y))
    assert not amber(pixel(surface, month.pad + cell * 1.5 + cell * 0.3, today_y))


# -- progress ---------------------------------------------------------------------------------

def test_progress_through_day_week_month_and_year():
    noon_wednesday = datetime.datetime(2026, 7, 1, 12, 0, 0)         # a Wednesday, day 182 of 365
    assert progress.progress("day", noon_wednesday) == pytest.approx(0.5)
    assert progress.progress("week", noon_wednesday) == pytest.approx(2.5 / 7)
    assert progress.progress("month", noon_wednesday) == pytest.approx(0.5 / 31)
    assert progress.progress("year", noon_wednesday) == pytest.approx(181.5 / 365)
    assert progress.progress("year", datetime.datetime(2028, 12, 31, 23, 59, 59)) == pytest.approx(1, abs=1e-6)
    widget = make("progress", "bars", make_style(), rows=["day", "year"])
    assert widget.rows == ["day", "year"] and widget.tick(30) and not widget.tick(31)


# -- media ------------------------------------------------------------------------------------

@pytest.mark.parametrize("design, buttons", [("card", ("Previous", "PlayPause", "Next")),
                                             ("pill", ("PlayPause", "Next")),
                                             ("cover", ("Previous", "PlayPause", "Next"))])
def test_media_buttons_hit_test(design, buttons):
    for style in (make_style(), make_style(scale=1.3)):
        widget = make("media", design, style)
        assert tuple(widget.buttons) == buttons
        for action, x in widget.buttons.items():
            assert widget.button_at(x, widget.button_y) == action
            assert 0 < x < widget.width and 0 < widget.button_y < widget.height
        assert widget.button_at(3, 3) is None


def test_media_draws_differently_when_playing_and_shows_progress():
    widget = make("media", "card", make_style())
    playing = bytes(render(widget)[0].get_data())
    widget.playing = False
    assert bytes(render(widget)[0].get_data()) != playing
    assert widget.tick(1) is False
    idle = media.Media(make_style(), {"fill": 0.5})
    assert render(idle)[2] > 0.9 and idle.times is not None
    assert media.Media(make_style(), {"width": 320}).times is None        # too narrow for the times


def test_track_lines_cover_songs_podcasts_and_nothing():
    assert media.track_lines({"xesam:title": "T", "xesam:artist": ["A", "B"]}, True) == ("T", "A, B")
    assert media.track_lines({"xesam:title": "Ep 1", "xesam:artist": [""], "xesam:album": "Show"}, True) == ("Ep 1", "Show")
    assert media.track_lines({}, True) == ("Nothing playing", "")
    assert media.track_lines({}, False)[0] == "No player running"


def test_format_time():
    assert media.format_time(83_000_000) == "1:23"
    assert media.format_time(16_270_000_000) == "4:31:10"
    assert media.format_time(-5) == "0:00"


def test_choose_player_prefers_what_is_playing():
    spotify, firefox = "org.mpris.MediaPlayer2.spotify", "org.mpris.MediaPlayer2.firefox"
    assert media.choose_player({}, None) is None
    assert media.choose_player({spotify: "Paused", firefox: "Playing"}, spotify) == firefox
    assert media.choose_player({spotify: "Playing", firefox: "Playing"}, spotify) == spotify
    assert media.choose_player({spotify: "Paused", firefox: "Paused"}, spotify) == spotify
    assert media.choose_player({firefox: "Paused"}, spotify) == firefox


# -- system -----------------------------------------------------------------------------------

def test_system_widget_drops_rows_without_a_sensor(root, monkeypatch):  # noqa: F811
    monkeypatch.setattr(system, "gpu_temperature", lambda _root: None)
    for design in DESIGNS["system"]:
        widget = make("system", design, make_style(), root, rows=["cpu", "ram", "temp", "gpu", "battery"])
        assert widget.rows == ["cpu", "ram", "temp", "battery"]
        assert [label for label, *_ in widget.readings()] == ["CPU", "RAM", "Temp", "Bat"]


def test_system_widget_samples_cpu_every_other_tick(root):  # noqa: F811
    widget = make("system", "bars", make_style(), root, rows=["cpu", "ram"])
    assert widget.tick(1) is False
    (root / "proc/stat").write_text("cpu  150 0 150 750 100 0 0 0 0 0\n")
    assert widget.tick(2) is True
    assert widget.cpu == pytest.approx(2 / 3) and widget.reading("cpu")[1] == "67%"


def test_hot_temperature_is_flagged(root, monkeypatch):  # noqa: F811
    widget = make("system", "rings", make_style(), root, rows=["temp"])
    assert widget.reading("temp") == (pytest.approx(32 / 70), "62°C", False)
    monkeypatch.setattr(system, "cpu_temperature", lambda _root: 91.0)
    assert widget.reading("temp")[1:] == ("91°C", True)
    assert render(widget)[2] > 0.5


def test_more_rows_make_each_system_design_bigger(root):  # noqa: F811
    style = make_style()
    for design, grows in (("bars", "height"), ("rings", "width"), ("line", "width")):
        few = make("system", design, style, root, rows=["cpu", "ram"])
        many = make("system", design, style, root, rows=["cpu", "ram", "temp", "battery"])
        assert getattr(many, grows) > getattr(few, grows)


# -- ornament ---------------------------------------------------------------------------------

@pytest.mark.parametrize("design", DESIGNS["ornament"])
def test_an_ornament_is_fixed_by_its_seed(design):
    def pixels(seed):
        return bytes(render(make("ornament", design, make_style(), seed=seed))[0].get_data())

    assert pixels(1) == pixels(1)
    assert len({pixels(seed) for seed in range(1, 9)}) == 8


def test_ornaments_never_sit_in_a_card():
    for design in DESIGNS["ornament"]:
        surface, _, covered = render(make("ornament", design, make_style(fill=0.9)))
        assert covered < 0.8 and pixel(surface, 0, 0)[3] == 0


def test_build_makes_the_widget_a_config_entry_names():
    widget = build(make_style(), {"type": "calendar", "design": "week", "anchor": "left",
                                  "options": {"fill": 0.4, "width": 300}})
    assert isinstance(widget, calendars.WeekCalendar) and widget.width == 300 and widget.fill == 0.4
    with pytest.raises(KeyError):
        build(make_style(), {"type": "clock", "design": "sundial", "anchor": "left"})
