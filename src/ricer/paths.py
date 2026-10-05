"""Where ricer keeps its files. Everything hangs off the environment so tests can redirect it."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

THEME_NAME = "Ricer"


@dataclass(frozen=True)
class Paths:
    home: Path
    config: Path                     # state.json, widgets.json
    cache: Path                      # wallpaper analysis, daemon pid and log
    data: Path                       # XDG data home: themes live under here
    wallpapers: Path

    @classmethod
    def from_env(cls, env=None) -> "Paths":
        env = os.environ if env is None else env
        home = Path(env.get("HOME") or Path.home())
        config = Path(env.get("XDG_CONFIG_HOME") or home / ".config")
        cache = Path(env.get("XDG_CACHE_HOME") or home / ".cache")
        data = Path(env.get("XDG_DATA_HOME") or home / ".local/share")
        wallpapers = Path(env.get("RICER_WALLPAPERS") or home / "Pictures/Wallpapers")
        return cls(home=home, config=config / "ricer", cache=cache / "ricer", data=data,
                   wallpapers=wallpapers)

    @property
    def state_file(self) -> Path:
        return self.config / "state.json"

    @property
    def default_file(self) -> Path:
        return self.config / "default.json"

    @property
    def widgets_file(self) -> Path:
        return self.config / "widgets.json"

    @property
    def wallpaper_cache(self) -> Path:
        return self.cache / "wallpapers.json"

    @property
    def pid_file(self) -> Path:
        return self.cache / "widgets.pid"

    @property
    def log_file(self) -> Path:
        return self.cache / "widgets.log"

    @property
    def themes_dir(self) -> Path:
        return self.data / "themes"

    @property
    def shell_theme_file(self) -> Path:
        return self.themes_dir / THEME_NAME / "gnome-shell" / "gnome-shell.css"

    @property
    def sheets_dir(self) -> Path:
        """Generated app stylesheets, each named after its content."""
        return self.data / "ricer" / "sheets"

    @property
    def gtk4_css_file(self) -> Path:
        """The user's own GTK 4 stylesheet; ricer keeps one marked block in it."""
        return self.config.parent / "gtk-4.0" / "gtk.css"

    @property
    def autostart_file(self) -> Path:
        return self.config.parent / "autostart" / "ricer-widgets.desktop"
