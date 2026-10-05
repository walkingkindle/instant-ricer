"""Access to the desktop. The engine only talks to a Backend, so tests can use a fake.

Settings are addressed by dconf path and carried as GVariant text ("'Yaru'", "true", "0.3").
A value of None means "not set": the desktop falls back to its default.
"""
from __future__ import annotations

import shutil
import subprocess

SHELL = "org.gnome.shell"
INSTALL_TIMEOUT_MS = 180_000         # the user has to answer GNOME's dialog


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

    def __init__(self, values=None, schemas=(), effective=None, extensions=None, installable=()):
        self.values: dict[str, str] = dict(values or {})
        self.schemas = set(schemas)
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

    def effective(self, schema, key):
        return self.effective_values.get((schema, key))

    def reload_shell_theme(self, name_path):
        self.reloads += 1

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
