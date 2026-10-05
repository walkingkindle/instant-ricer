import dataclasses

import pytest

from ricer.generator import generate
from ricer.look import Dials, Dock, Look, LookError, WidgetSpec, dial_fraction


def test_dial_fraction_spans_zero_to_one():
    assert dial_fraction(1) == 0.0
    assert dial_fraction(10) == 1.0


@pytest.mark.parametrize("bad", [0, 11, -3, 5.5, "5", True])
def test_dials_reject_out_of_range_and_non_integers(bad):
    with pytest.raises(LookError):
        Dials(cool=bad).validate()


def test_look_survives_a_json_round_trip(wallpaper_set):
    import json
    look = generate(Dials(7, 4, 8), wallpaper_set, seed=3)
    assert Look.from_dict(json.loads(json.dumps(look.to_dict()))) == look


def test_two_widgets_cannot_share_an_anchor(wallpaper_set):
    look = generate(Dials(5, 5, 5), wallpaper_set)
    clash = dataclasses.replace(look, widgets=(WidgetSpec("clock", "top-center"),
                                               WidgetSpec("media", "top-center")))
    with pytest.raises(LookError, match="anchor"):
        clash.validate()


def test_bad_pieces_are_rejected(wallpaper_set):
    look = generate(Dials(5, 5, 5), wallpaper_set)
    with pytest.raises(LookError):
        dataclasses.replace(look, bar_style="neon").validate()
    with pytest.raises(LookError):
        dataclasses.replace(look, dock=Dock(opacity=1.5)).validate()
    with pytest.raises(LookError):
        dataclasses.replace(look, palette=dataclasses.replace(look.palette, accent="red")).validate()
    with pytest.raises(LookError):
        WidgetSpec("system", "bottom-left", {"rows": ["cpu", "fans"]}).validate()
