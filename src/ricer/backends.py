"""Access to desktop settings. The engine only talks to a Backend, so tests can use a fake.

Settings are addressed by dconf path and carried as GVariant text ("'Yaru'", "true", "0.3").
A value of None means "not set": the desktop falls back to its default.
"""
from __future__ import annotations

import shutil
import subprocess


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


class FakeBackend:
    """In-memory stand-in for tests."""

    def __init__(self, values=None, schemas=(), effective=None):
        self.values: dict[str, str] = dict(values or {})
        self.schemas = set(schemas)
        self.effective_values: dict[tuple[str, str], object] = dict(effective or {})
        self.fail_on: set[str] = set()
        self.reloads = 0
        self.writes: list[str] = []

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
