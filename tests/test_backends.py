"""The two GnomeBackend methods that get running apps to re-read a theme, without a desktop."""
import pytest

from ricer import backends
from ricer.backends import TERMINAL_VARIANT, BackendError, GnomeBackend

THEME = "/org/gnome/desktop/interface/gtk-theme"


class Recorder(GnomeBackend):
    """A GnomeBackend whose settings are a dict, recording every write and reset in order."""

    def __init__(self, values=None, has_variant=True, fail_on=None, running=True):
        self.values, self.calls = dict(values or {}), []
        self.has_variant, self.fail_on, self.running = has_variant, fail_on, running
        self.waits = 0

    def _terminal_caught_up(self):
        self.waits += 1
        return self.running

    def read(self, path):
        return self.values.get(path)

    def write(self, path, value):
        if value == self.fail_on:
            raise BackendError("refused")
        self.calls.append((path, value))
        self.values[path] = value

    def reset(self, path):
        self.calls.append((path, None))
        self.values.pop(path, None)

    def has_key(self, schema, key):
        return self.has_variant

    def effective(self, schema, key):
        return self.values.get(TERMINAL_VARIANT, "'system'").strip("'")


@pytest.fixture(autouse=True)
def pauses(monkeypatch):
    slept = []
    monkeypatch.setattr(backends.time, "sleep", slept.append)
    return slept


@pytest.mark.parametrize("kept, steps", [
    ("'dark'", [(TERMINAL_VARIANT, "'light'"), (TERMINAL_VARIANT, "'dark'")]),
    ("'light'", [(TERMINAL_VARIANT, "'dark'"), (TERMINAL_VARIANT, "'light'")]),
    (None, [(TERMINAL_VARIANT, "'light'"), (TERMINAL_VARIANT, None)]),       # unset goes back to unset
])
def test_the_terminal_is_nudged_through_the_other_variant_and_back(kept, steps, pauses):
    backend = Recorder({TERMINAL_VARIANT: kept} if kept else {})
    backend.nudge_terminal()
    assert backend.calls == steps and backend.values.get(TERMINAL_VARIANT) == kept
    assert pauses == [backends.NUDGE_PAUSE] * 2              # it has to see each value
    assert backend.waits == 2                                # idle before, settled after


def test_no_terminal_no_nudge():
    for backend in (Recorder(has_variant=False), Recorder({TERMINAL_VARIANT: "'dark'"}, running=False)):
        backend.nudge_terminal()
        assert backend.calls == []                           # not installed; installed but not running


def test_a_failed_nudge_still_puts_the_preference_back():
    backend = Recorder({TERMINAL_VARIANT: "'dark'"}, fail_on="'light'")
    with pytest.raises(BackendError):
        backend.nudge_terminal()
    assert backend.values == {TERMINAL_VARIANT: "'dark'"}


def test_the_app_theme_is_reloaded_through_a_sibling():
    backend = Recorder({THEME: "'Yaru-purple-dark'"})
    backend.reload_gtk_theme(THEME, "Yaru-blue-dark")
    assert backend.calls == [(THEME, "'Yaru-blue-dark'"), (THEME, "'Yaru-purple-dark'")]
    unset = Recorder()
    unset.reload_gtk_theme(THEME, "Yaru-blue-dark")
    assert unset.calls == []                                 # nothing ricer set: nothing to flip
