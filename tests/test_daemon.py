import json
import os

import pytest

pytest.importorskip("gi")
if not os.environ.get("DISPLAY"):
    pytest.skip("needs an X display", allow_module_level=True)

from ricer.engine import widgets_config  # noqa: E402
from ricer.generator import generate  # noqa: E402
from ricer.look import DESIGNS, Dials, WidgetSpec  # noqa: E402
from ricer.placement import arrange  # noqa: E402
from ricer.widgets import daemon  # noqa: E402

import dataclasses  # noqa: E402


class FakePlayer:
    made = []

    def __init__(self, widget, redraw):
        self.closed, self.polls, self.presses = False, 0, []
        FakePlayer.made.append(self)

    def poll_position(self):
        self.polls += 1

    def press(self, action):
        self.presses.append(action)

    def close(self):
        self.closed = True


@pytest.fixture
def running(wallpaper_set, full_caps, paths, monkeypatch):
    """A daemon over a temp config, with windows kept off the screen and no real media player."""
    FakePlayer.made = []
    monkeypatch.setattr(daemon, "MprisPlayer", FakePlayer)
    monkeypatch.setattr(daemon.Gtk.Window, "show_all", lambda self: None)
    paths.widgets_file.parent.mkdir(parents=True)
    look = generate(Dials(9, 6, 5), wallpaper_set, 4)

    def write(widgets):
        config = widgets_config(dataclasses.replace(look, widgets=tuple(widgets)), full_caps)
        paths.widgets_file.write_text(json.dumps(config))

    write([])
    return daemon.Daemon(paths), write


def spec(kind, design, anchor, **options):
    defaults = {"system": {"rows": ["cpu", "ram"]}, "progress": {"rows": ["day"]}}.get(kind, {})
    return WidgetSpec(kind, design, anchor, {"fill": 0.5, "align": "left", **defaults, **options})


def test_a_window_is_built_for_every_widget_type_and_design(running):
    service, write = running
    every = [spec(kind, design, "top-left") for kind, designs in DESIGNS.items() for design in designs]
    write(every)
    service.rebuild()
    assert [w.get_title() for w in service.windows] == [f"ricer-{s.type}" for s in every]
    assert len(service.players) == len(DESIGNS["media"])
    assert service._tick() is True and service.ticks == 1
    assert all(player.polls == 1 for player in service.players)


def test_windows_are_laid_out_by_zone_inside_the_work_area(running):
    service, write = running
    write([spec("clock", "digital", "top-center", size=80), spec("system", "bars", "bottom-right"),
           spec("progress", "bars", "bottom-right"), spec("media", "pill", "left")])
    service.rebuild()
    monitor = daemon.Gdk.Display.get_default().get_primary_monitor() or daemon.Gdk.Display.get_default().get_monitor(0)
    area = monitor.get_workarea()
    items = [(w.anchor, w.content.width, w.content.height) for w in service.windows]
    expected = arrange(items, (area.x, area.y, area.width, area.height), service.insets)
    assert [w._spot for w in service.windows] == expected
    system_spot, progress_spot = service.windows[1]._spot, service.windows[2]._spot
    assert system_spot[1] + service.windows[1].content.height < progress_spot[1]    # stacked, not overlapping
    assert system_spot[0] + service.windows[1].content.width == progress_spot[0] + service.windows[2].content.width


def test_reloading_closes_the_old_media_players(running):
    service, write = running
    write([spec("media", "card", "bottom-left")])
    service.rebuild()
    first = service.players[0]
    write([spec("media", "cover", "left"), spec("clock", "words", "top-left")])
    service.rebuild()
    assert first.closed and len(service.players) == 1 and not service.players[0].closed
    assert [w.get_title() for w in service.windows] == ["ricer-media", "ricer-clock"]


def test_a_click_on_a_button_reaches_the_player(running):
    service, write = running
    write([spec("media", "card", "bottom-left")])
    service.rebuild()
    window, player = service.windows[0], service.players[0]
    x, y = window.content.buttons["Next"], window.content.button_y
    assert window.on_click(x, y) is True and player.presses == ["Next"]
    assert window.on_click(2, 2) is False and player.presses == ["Next"]


def test_a_window_follows_a_widget_that_changes_size(running):
    service, write = running
    write([spec("calendar", "month", "top-right")])
    service.rebuild()
    window = service.windows[0]
    assert window.sync_size() is False
    window.content.height += 30                              # as when a month needs another row
    assert window.sync_size() is True and window._size == (window.content.width, window.content.height)


def test_dock_clearance_from_the_config_is_used(running, paths):
    service, write = running
    write([spec("greeting", "plain", "left")])
    config = json.loads(paths.widgets_file.read_text())
    config["insets"] = [90, 0, 0]
    paths.widgets_file.write_text(json.dumps(config))
    service.rebuild()
    shifted = service.windows[0]._spot[0]
    config["insets"] = [0, 0, 0]
    paths.widgets_file.write_text(json.dumps(config))
    service.rebuild()
    assert shifted == service.windows[0]._spot[0] + 90


def test_bad_config_or_a_bad_widget_does_not_stop_the_rest(running, paths, capsys):
    service, write = running
    write([spec("clock", "digital", "top-left"), spec("media", "card", "left")])
    config = json.loads(paths.widgets_file.read_text())
    config["widgets"][0]["design"] = "sundial"               # unknown design: skipped, with a message
    paths.widgets_file.write_text(json.dumps(config))
    service.rebuild()
    assert [w.get_title() for w in service.windows] == ["ricer-media"]
    assert "skipping clock" in capsys.readouterr().err

    paths.widgets_file.write_text("{ not json")
    service.rebuild()
    assert service.windows == [] and "cannot read" in capsys.readouterr().err
    assert service._tick() is True                           # an empty daemon keeps ticking
