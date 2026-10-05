"""Find out what this desktop can do, so the engine can skip what is missing."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from ricer.paths import Paths

SYSTEM_DATA_DIRS = ("/usr/share", "/usr/local/share")
USER_THEME_UUID = "user-theme@gnome-shell-extensions.gcampax.github.com"
BLUR_UUID = "blur-my-shell@aunetx"
DOCK_SCHEMA = "org.gnome.shell.extensions.dash-to-dock"
TERMINAL_SCHEMA = "org.gnome.Terminal.ProfilesList"
INTERFACE = "org.gnome.desktop.interface"


@dataclass(frozen=True)
class Capabilities:
    gnome: bool
    session: str                              # "x11", "wayland" or "unknown"
    gtk_themes: frozenset[str]
    icon_themes: frozenset[str]               # cursor themes live in the same folders
    shell_themes: dict[str, str]              # stock shell theme name -> its gnome-shell.css
    dock: bool
    user_theme: bool
    blur: bool
    accent_color: bool                        # GNOME 47+ accent setting exists
    terminal_profile: str | None
    font: str
    clock_24h: bool

    @property
    def widgets(self) -> bool:
        return self.session == "x11"

    def report(self) -> list[tuple[str, bool, str]]:
        """(feature, available, note) rows for 'ricer status'."""
        return [
            ("GNOME desktop", self.gnome, "" if self.gnome else "ricer only supports GNOME"),
            ("Desktop widgets", self.widgets,
             "" if self.widgets else f"need an X11 session (this one is {self.session})"),
            ("Dock styling", self.dock, "" if self.dock else "Dash to Dock / Ubuntu Dock not found"),
            ("Top bar styling", self.user_theme,
             "" if self.user_theme else "enable the 'User Themes' extension"),
            ("Blur", self.blur, "" if self.blur else "enable the 'Blur my Shell' extension"),
            ("Terminal colours", self.terminal_profile is not None,
             "" if self.terminal_profile else "GNOME Terminal not found"),
        ]


def _subdirs(directories) -> frozenset[str]:
    names = set()
    for directory in directories:
        try:
            names.update(entry.name for entry in Path(directory).iterdir() if entry.is_dir())
        except OSError:
            pass
    return frozenset(names)


def detect(backend, paths: Paths, env=None, system_data_dirs=SYSTEM_DATA_DIRS) -> Capabilities:
    env = os.environ if env is None else env
    data_dirs = [Path(d) for d in system_data_dirs]

    extensions = set(backend.effective("org.gnome.shell", "enabled-extensions") or [])
    if backend.effective("org.gnome.shell", "disable-user-extensions"):
        extensions = set()

    shell_themes = {}
    for directory in data_dirs:
        for css in sorted((directory / "gnome-shell/theme").glob("*/gnome-shell.css")):
            shell_themes.setdefault(css.parent.name, str(css))

    font = backend.effective(INTERFACE, "font-name") or "Sans 11"
    profile = (backend.effective(TERMINAL_SCHEMA, "default")
               if backend.has_schema(TERMINAL_SCHEMA) else None)

    return Capabilities(
        gnome="GNOME" in (env.get("XDG_CURRENT_DESKTOP") or "").upper().split(":"),
        session=(env.get("XDG_SESSION_TYPE") or "unknown").lower(),
        gtk_themes=_subdirs([*(d / "themes" for d in data_dirs),
                             paths.data / "themes", paths.home / ".themes"]),
        icon_themes=_subdirs([*(d / "icons" for d in data_dirs),
                              paths.data / "icons", paths.home / ".icons"]),
        shell_themes=shell_themes,
        dock=backend.has_schema(DOCK_SCHEMA),
        user_theme=USER_THEME_UUID in extensions,
        blur=BLUR_UUID in extensions,
        accent_color=backend.effective(INTERFACE, "accent-color") is not None,
        terminal_profile=profile or None,
        font=re.sub(r"\s+[\d.]+$", "", font),
        clock_24h=backend.effective(INTERFACE, "clock-format") != "12h",
    )
