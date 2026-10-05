import dataclasses
import json

import pytest

from ricer.generator import generate
from ricer.look import (ANCHORS, DESIGNS, Bar, Dials, Dock, Look, LookError, Style, WidgetSpec,
                        dial_fraction)


def test_dial_fraction_spans_zero_to_one():
    assert dial_fraction(1) == 0.0
    assert dial_fraction(10) == 1.0


@pytest.mark.parametrize("name", ["cool", "ease", "warmth", "chaos"])
@pytest.mark.parametrize("bad", [0, 11, -3, 5.5, "5", True])
def test_dials_reject_out_of_range_and_non_integers(name, bad):
    with pytest.raises(LookError, match=name):
        Dials(**{name: bad}).validate()


def test_look_survives_a_json_round_trip(wallpaper_set):
    for seed in range(1, 12):
        look = generate(Dials(8, 6, 7, 6), wallpaper_set, seed)
        assert Look.from_dict(json.loads(json.dumps(look.to_dict()))) == look


def test_a_look_saved_before_the_bar_had_a_clock_choice_still_reads(wallpaper_set):
    look = generate(Dials(8, 6, 7, 6), wallpaper_set, 4)
    old = json.loads(json.dumps(look.to_dict()))
    del old["bar"]["clock"], old["bar"]["menu"]
    read = Look.from_dict(old)
    assert read.bar == dataclasses.replace(look.bar, clock="full", menu=())    # GNOME's own, untouched
    read.validate()


def test_a_look_from_version_one_is_refused_cleanly():
    old = {"dials": {"cool": 5, "ease": 5, "warmth": 5}, "seed": 0, "wallpaper": "/w.png",
           "bar_style": "cards", "widget_scale": 1.0, "widgets": []}
    with pytest.raises(LookError, match="not a look this version understands"):
        Look.from_dict(old)


def test_every_widget_type_has_designs_and_anchors_are_unique():
    assert all(designs for designs in DESIGNS.values())
    assert len(set(ANCHORS)) == 9


def test_bad_pieces_are_rejected(wallpaper_set):
    look = generate(Dials(), wallpaper_set, 1)
    broken = [
        dataclasses.replace(look, layout="pile"),
        dataclasses.replace(look, icon_style="neon"),
        dataclasses.replace(look, wallpaper=""),
        dataclasses.replace(look, bar=Bar(style="neon")),
        dataclasses.replace(look, bar=Bar(stats=("cpu", "cpu"))),
        dataclasses.replace(look, bar=Bar(stats=("fans",))),
        dataclasses.replace(look, bar=Bar(media_side="top")),
        dataclasses.replace(look, bar=Bar(clock="sundial")),
        dataclasses.replace(look, bar=Bar(menu=("profile", "profile"))),
        dataclasses.replace(look, bar=Bar(menu=("horoscope",))),
        dataclasses.replace(look, dock=Dock(opacity=1.5)),
        dataclasses.replace(look, dock=Dock(indicator="LASERS")),
        dataclasses.replace(look, style=Style(border="dotted")),
        dataclasses.replace(look, style=Style(voice="comic")),
        dataclasses.replace(look, style=Style(fill=1.2)),
        dataclasses.replace(look, palette=dataclasses.replace(look.palette, accent="red")),
        dataclasses.replace(look, terminal={"background": "#000000"}),
        dataclasses.replace(look, widgets=(WidgetSpec("clock", "sundial", "center"),)),
        dataclasses.replace(look, widgets=(WidgetSpec("clock", "digital", "middle"),)),
        dataclasses.replace(look, widgets=(WidgetSpec("toaster", "plain", "center"),)),
        dataclasses.replace(look, widgets=(WidgetSpec("system", "bars", "left", {"rows": ["fans"]}),)),
        dataclasses.replace(look, widgets=(WidgetSpec("progress", "bars", "left", {"rows": []}),)),
    ]
    for look in broken:
        with pytest.raises(LookError):
            look.validate()


def test_several_widgets_may_share_a_zone(wallpaper_set):
    look = generate(Dials(), wallpaper_set, 1)
    stacked = dataclasses.replace(look, widgets=(
        WidgetSpec("clock", "digital", "top-left"), WidgetSpec("greeting", "plain", "top-left")))
    stacked.validate()
