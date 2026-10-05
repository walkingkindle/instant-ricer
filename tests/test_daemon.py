import json
import os

import pytest

pytest.importorskip("gi")
if not os.environ.get("DISPLAY"):
    pytest.skip("needs an X display", allow_module_level=True)

from ricer.engine import widgets_config  # noqa: E402
from ricer.generator import generate  # noqa: E402
from ricer.look import ANCHORS, Dials  # noqa: E402
from ricer.widgets import daemon  # noqa: E402


class Geo:
    x, y, width, height = 100, 50, 1920, 1080


@pytest.mark.parametrize("anchor, expected", [
    ("top-left", (140, 76)), ("top-center", (910, 76)), ("top-right", (1680, 76)),
    ("bottom-left", (140, 990)), ("bottom-right", (1680, 990)),
])
def test_position_for_every_anchor(anchor, expected):
    assert daemon.position(anchor, Geo, 300, 100) == expected
    assert anchor in ANCHORS


def test_daemon_builds_a_window_per_widget_and_reloads(wallpaper_set, full_caps, paths, monkeypatch):
    monkeypatch.setattr(daemon, "MprisPlayer", lambda widget, redraw: type(
        "Player", (), {"poll_position": lambda self: None, "press": lambda self, action: None})())
    monkeypatch.setattr(daemon.Gtk.Window, "show_all", lambda self: None)   # keep the test invisible
    paths.widgets_file.parent.mkdir(parents=True)

    def write(dials):
        look = generate(dials, wallpaper_set)
        paths.widgets_file.write_text(json.dumps(widgets_config(look, full_caps)))
        return look

    look = write(Dials(9, 6, 5))
    running = daemon.Daemon(paths)
    assert [type(w.content).__name__.lower() for w in running.windows] == [w.type for w in look.widgets]
    assert [w.get_title() for w in running.windows] == ["ricer-clock", "ricer-media", "ricer-system"]
    assert len(running.players) == 1
    assert running._tick() is True

    write(Dials(1, 1, 5))
    running.rebuild()
    assert [w.get_title() for w in running.windows] == ["ricer-clock"] and running.players == []

    paths.widgets_file.write_text("{ not json")
    running.rebuild()
    assert running.windows == []
