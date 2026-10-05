"""Access to the desktop. The engine only talks to a Backend, so tests can use a fake.

Settings are addressed by dconf path and carried as GVariant text ("'Yaru'", "true", "0.3").
A value of None means "not set": the desktop falls back to its default.
"""
from __future__ import annotations

import shutil
import subprocess
import time

SHELL = "org.gnome.shell"
INSTALL_TIMEOUT_MS = 180_000         # the user has to answer GNOME's dialog
TERMINAL_SETTINGS = "org.gnome.Terminal.Legacy.Settings"
TERMINAL_VARIANT = "/org/gnome/terminal/legacy/theme-variant"
TERMINAL_BUS_NAME, TERMINAL_OBJECT = "org.gnome.Terminal", "/org/gnome/Terminal"
TERMINAL_PATIENCE_MS = 3000          # how long a busy terminal is waited for
NUDGE_PAUSE = 0.02                   # seconds: long enough for an idle terminal to see the first value


def gv(value) -> str:
    """Python value to GVariant text."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(gv(item) for item in value) + "]"
    raise TypeError(f"cannot express {value!r} as a GVariant")


def gv_uint(value: int) -> str:
    """An unsigned 32-bit GVariant, for the settings that are declared that way."""
    return f"uint32 {int(value)}"


class BackendError(RuntimeError):
    pass


class GnomeBackend:
    """The real desktop: dconf for writes, GSettings for defaults and schema lookups."""

    def __init__(self):
        from gi.repository import Gio, GLib
        self._gio, self._glib = Gio, GLib
        self._dconf = shutil.which("dconf")
        if not self._dconf:
            raise BackendError("the 'dconf' command is needed but was not found")

    def _run(self, *args: str) -> str:
        done = subprocess.run([self._dconf, *args], capture_output=True, text=True)
        if done.returncode != 0:
            raise BackendError(f"dconf {' '.join(args)}: {done.stderr.strip()}")
        return done.stdout.strip()

    # -- settings -------------------------------------------------------
    def read(self, path: str) -> str | None:
        return self._run("read", path) or None

    def write(self, path: str, value: str) -> None:
        self._run("write", path, value)

    def reset(self, path: str) -> None:
        self._run("reset", path)

    def same(self, a: str | None, b: str | None) -> bool:
        """Compare two values by meaning, so 0.3 equals 0.29999999999999999."""
        if a is None or b is None:
            return a is b
        try:
            return self._glib.Variant.parse(None, a).equal(self._glib.Variant.parse(None, b))
        except self._glib.Error:
            return a == b

    def has_schema(self, schema: str) -> bool:
        return self._gio.SettingsSchemaSource.get_default().lookup(schema, True) is not None

    def has_key(self, schema: str, key: str) -> bool:
        """Whether a schema declares a key. Safe for schemas that have no fixed path."""
        found = self._gio.SettingsSchemaSource.get_default().lookup(schema, True)
        return found is not None and found.has_key(key)

    def effective(self, schema: str, key: str):
        """Current value including the default, or None if the schema or key does not exist."""
        found = self._gio.SettingsSchemaSource.get_default().lookup(schema, True)
        if found is None or not found.has_key(key):
            return None
        return self._gio.Settings.new(schema).get_value(key).unpack()

    def reload_shell_theme(self, name_path: str) -> None:
        """Make User Themes re-read the stylesheet by flipping the theme name off and on."""
        current = self.read(name_path)
        if current:
            self.write(name_path, "''")
            self.write(name_path, current)

    def reload_gtk_theme(self, name_path: str, sibling: str) -> None:
        """Make running GTK 3 apps re-read the app theme, which they do only when its name changes.

        The name goes to a sibling theme and straight back; apps load both before they
        next draw, so what they show is only the result.
        """
        current = self.read(name_path)
        if current:
            self.write(name_path, gv(sibling))
            self.write(name_path, current)

    def _terminal_caught_up(self) -> bool:
        """Wait until a running GNOME Terminal has dealt with all it was sent. False if none runs."""
        gio, none = self._gio, self._gio.DBusCallFlags.NONE
        try:
            bus = gio.bus_get_sync(gio.BusType.SESSION)
            running, = bus.call_sync(
                "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner",
                self._glib.Variant("(s)", (TERMINAL_BUS_NAME,)), None, none, TERMINAL_PATIENCE_MS, None)
            if running:
                # its main loop answers this one, and only gets to it after everything before it
                bus.call_sync(TERMINAL_BUS_NAME, TERMINAL_OBJECT, "org.gtk.Actions", "List", None, None,
                              gio.DBusCallFlags.NO_AUTO_START, TERMINAL_PATIENCE_MS, None)
            return bool(running)
        except self._glib.Error:
            return True                                      # it may be there: better told than not

    def nudge_terminal(self) -> None:
        """Make a running GNOME Terminal re-read the app theme.

        The terminal settles on a theme when it starts and looks again only when its own
        light or dark preference changes, so that is flipped and put back. Each time it
        reads the value of that moment, so it has to notice the first before the second is
        written: it is given time to finish whatever it is doing, and then a short pause.
        The second arrives while it is still loading for the first, so it never draws that.
        """
        if not self.has_key(TERMINAL_SETTINGS, "theme-variant") or not self._terminal_caught_up():
            return
        kept = self.read(TERMINAL_VARIANT)
        other = "light" if self.effective(TERMINAL_SETTINGS, "theme-variant") != "light" else "dark"
        try:
            self.write(TERMINAL_VARIANT, gv(other))
            time.sleep(NUDGE_PAUSE)
        finally:
            if kept is None:
                self.reset(TERMINAL_VARIANT)
            else:
                self.write(TERMINAL_VARIANT, kept)
        time.sleep(NUDGE_PAUSE)                              # the last value has to reach it first
        self._terminal_caught_up()                           # so the next thing finds it settled

    # -- extensions -----------------------------------------------------
    def extension_enabled(self, uuid: str) -> bool:
        return (uuid in (self.effective(SHELL, "enabled-extensions") or [])
                and uuid not in (self.effective(SHELL, "disabled-extensions") or []))

    def set_extension_enabled(self, uuid: str, enabled: bool) -> None:
        tool = shutil.which("gnome-extensions")
        if not tool:
            raise BackendError("the 'gnome-extensions' command is needed but was not found")
        done = subprocess.run([tool, "enable" if enabled else "disable", uuid],
                              capture_output=True, text=True)
        if done.returncode != 0:
            raise BackendError(f"could not {'enable' if enabled else 'disable'} {uuid}: "
                               f"{done.stderr.strip() or done.stdout.strip()}")

    def extension_installed(self, uuid: str) -> bool:
        tool = shutil.which("gnome-extensions")
        return bool(tool) and subprocess.run([tool, "info", uuid], capture_output=True).returncode == 0

    def install_extension(self, uuid: str) -> bool:
        """Ask GNOME Shell to install an extension from extensions.gnome.org.

        The shell shows its own confirmation dialog; this returns once the user has answered.
        True if the extension is installed afterwards.
        """
        try:
            bus = self._gio.bus_get_sync(self._gio.BusType.SESSION)
            bus.call_sync("org.gnome.Shell", "/org/gnome/Shell", "org.gnome.Shell.Extensions",
                          "InstallRemoteExtension", self._glib.Variant("(s)", (uuid,)),
                          self._glib.VariantType("(s)"), self._gio.DBusCallFlags.NONE,
                          INSTALL_TIMEOUT_MS, None)
        except self._glib.Error:
            pass                                             # judged below by what is installed
        return self.extension_installed(uuid)

    def allow_user_extensions(self) -> None:
        """Undo GNOME's global 'extensions off' switch, which blocks every user extension."""
        self.write("/org/gnome/shell/disable-user-extensions", "false")


class FakeBackend:
    """In-memory stand-in for tests."""

    def __init__(self, values=None, schemas=(), effective=None, extensions=None, installable=(),
                 keys=()):
        self.values: dict[str, str] = dict(values or {})
        self.schemas = set(schemas)
        self.keys = set(keys)                                        # (schema, key) pairs that exist
        self.theme_reloads: list[str] = []                           # sibling themes flipped through
        self.terminal_nudges = 0
        self.effective_values: dict[tuple[str, str], object] = dict(effective or {})
        self.extensions: dict[str, bool] = dict(extensions or {})    # installed uuid -> enabled
        self.installable = set(installable)                          # uuids the user will accept
        self.fail_on: set[str] = set()
        self.reloads = 0
        self.writes: list[str] = []
        self.install_requests: list[str] = []

    def read(self, path):
        return self.values.get(path)

    def write(self, path, value):
        if path in self.fail_on:
            raise BackendError(f"refused to write {path}")
        self.values[path] = value
        self.writes.append(path)

    def reset(self, path):
        self.values.pop(path, None)

    def same(self, a, b):
        return a == b

    def has_schema(self, schema):
        return schema in self.schemas

    def has_key(self, schema, key):
        return (schema, key) in self.keys

    def effective(self, schema, key):
        return self.effective_values.get((schema, key))

    def reload_shell_theme(self, name_path):
        self.reloads += 1

    def reload_gtk_theme(self, name_path, sibling):
        self.theme_reloads.append(sibling)

    def nudge_terminal(self):
        self.terminal_nudges += 1

    def extension_enabled(self, uuid):
        return self.extensions.get(uuid, False)

    def set_extension_enabled(self, uuid, enabled):
        if uuid in self.fail_on:
            raise BackendError(f"refused to switch {uuid}")
        if uuid not in self.extensions:
            raise BackendError(f"{uuid} is not installed")
        self.extensions[uuid] = enabled
        self.writes.append(uuid)

    def extension_installed(self, uuid):
        return uuid in self.extensions

    def install_extension(self, uuid):
        self.install_requests.append(uuid)
        if uuid in self.installable:
            self.extensions[uuid] = True                     # GNOME enables what it installs
        return uuid in self.extensions

    def allow_user_extensions(self):
        self.effective_values[("org.gnome.shell", "disable-user-extensions")] = False
