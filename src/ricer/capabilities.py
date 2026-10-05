"""Find out what this desktop can do, so the engine can skip what is missing."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from ricer.look import VOICES
from ricer.paths import Paths

SYSTEM_DATA_DIRS = ("/usr/share", "/usr/local/share")
USER_THEME_UUID = "user-theme@gnome-shell-extensions.gcampax.github.com"
BLUR_UUID = "blur-my-shell@aunetx"
VITALS_UUID = "Vitals@CoreCoding.com"
MEDIA_CONTROLS_UUID = "mediacontrols@cliffniff.github.com"
# optional extensions `ricer setup` offers, with what each one unlocks
OPTIONAL_EXTENSIONS = {
    USER_THEME_UUID: ("User Themes", "styling the top bar"),
    BLUR_UUID: ("Blur my Shell", "blur behind the dock and overview"),
    VITALS_UUID: ("Vitals", "system stats in the top bar"),
    MEDIA_CONTROLS_UUID: ("Media Controls", "now playing in the top bar"),
}
DOCK_SCHEMA = "org.gnome.shell.extensions.dash-to-dock"
DESKTOP_ICONS_SCHEMA = "org.gnome.shell.extensions.ding"
TERMINAL_SCHEMA = "org.gnome.Terminal.ProfilesList"
INTERFACE = "org.gnome.desktop.interface"
DEFAULT_SCREEN = (1920, 1080)
# typeface voices: families to use if installed, best first
VOICE_FAMILIES = {
    "serif": ("Noto Serif Display", "Playfair Display", "Libre Baskerville", "Noto Serif",
              "DejaVu Serif"),
    "geometric": ("URW Gothic", "Poppins", "Montserrat", "Jost", "Century Gothic"),
}
VOICE_FALLBACKS = {"serif": "Serif", "mono": "Monospace"}


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
    font: str                                 # interface font family
    clock_24h: bool
    vitals: bool = False                      # installed; ricer switches it on and off per look
    media_controls: bool = False
    desktop_icons: bool = False               # the desktop-icons extension can be told to hide them
    fonts: dict[str, str] = field(default_factory=dict)      # typeface voice -> font family
    screen: tuple[int, int] = DEFAULT_SCREEN
    installed: frozenset[str] = frozenset()   # uuids of installed extensions
    extensions_allowed: bool = True           # False when GNOME has user extensions switched off

    @property
    def widgets(self) -> bool:
        return self.session == "x11"

    def font_for(self, voice: str) -> str:
        return self.fonts.get(voice) or self.font

    def report(self) -> list[tuple[str, bool, str]]:
        """(feature, available, note) rows for 'ricer status'."""
        def need(uuid: str) -> str:
            return f"install the '{OPTIONAL_EXTENSIONS[uuid][0]}' extension: ricer setup"

        return [
            ("GNOME desktop", self.gnome, "" if self.gnome else "ricer only supports GNOME"),
            ("Desktop widgets", self.widgets,
             "" if self.widgets else f"need an X11 session (this one is {self.session})"),
            ("Top bar styling", self.user_theme, "" if self.user_theme else need(USER_THEME_UUID)),
            ("Stats in the top bar", self.vitals, "" if self.vitals else need(VITALS_UUID)),
            ("Now playing in the top bar", self.media_controls,
             "" if self.media_controls else need(MEDIA_CONTROLS_UUID)),
            ("Blur", self.blur, "" if self.blur else need(BLUR_UUID)),
            ("Dock styling", self.dock, "" if self.dock else "Dash to Dock / Ubuntu Dock not found"),
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


def installed_font_families() -> frozenset[str]:
    """Names of the font families on this system; empty if they cannot be listed."""
    try:
        import gi
        gi.require_version("PangoCairo", "1.0")
        from gi.repository import PangoCairo
        return frozenset(family.get_name() for family in PangoCairo.FontMap.get_default().list_families())
    except Exception:
        return frozenset()


def primary_screen() -> tuple[int, int]:
    """Pixel size of the primary monitor; a common default if there is no display to ask."""
    try:
        import gi
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        geometry = monitor.get_geometry()
        return geometry.width, geometry.height
    except Exception:
        return DEFAULT_SCREEN


def font_voices(ui: str, mono: str, families: frozenset[str]) -> dict[str, str]:
    """Which font family plays each typeface voice on this system."""
    voices = {"ui": ui, "mono": mono or VOICE_FALLBACKS["mono"],
              # a width request: fonts with a condensed face use it, others ignore it
              "condensed": f"{ui} Condensed"}
    for voice, wanted in VOICE_FAMILIES.items():
        voices[voice] = next((name for name in wanted if name in families),
                             VOICE_FALLBACKS.get(voice, ui))
    assert set(voices) == set(VOICES)
    return voices


def _family(font_name: str | None, default: str) -> str:
    """'Ubuntu Sans 11' -> 'Ubuntu Sans'."""
    return re.sub(r"\s+[\d.]+$", "", font_name or default)


def detect(backend, paths: Paths, env=None, system_data_dirs=SYSTEM_DATA_DIRS,
           fonts: frozenset[str] | None = None, screen: tuple[int, int] | None = None) -> Capabilities:
    env = os.environ if env is None else env
    data_dirs = [Path(d) for d in system_data_dirs]

    allowed = not backend.effective("org.gnome.shell", "disable-user-extensions")
    enabled = set(backend.effective("org.gnome.shell", "enabled-extensions") or []) if allowed else set()
    installed = _subdirs([*(d / "gnome-shell/extensions" for d in data_dirs),
                          paths.data / "gnome-shell/extensions"])

    shell_themes = {}
    for directory in data_dirs:
        for css in sorted((directory / "gnome-shell/theme").glob("*/gnome-shell.css")):
            shell_themes.setdefault(css.parent.name, str(css))

    font = _family(backend.effective(INTERFACE, "font-name"), "Sans 11")
    mono = _family(backend.effective(INTERFACE, "monospace-font-name"), "Monospace 11")
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
        user_theme=USER_THEME_UUID in enabled,
        blur=BLUR_UUID in enabled,
        accent_color=backend.effective(INTERFACE, "accent-color") is not None,
        terminal_profile=profile or None,
        font=font,
        clock_24h=backend.effective(INTERFACE, "clock-format") != "12h",
        vitals=allowed and VITALS_UUID in installed,
        media_controls=allowed and MEDIA_CONTROLS_UUID in installed,
        desktop_icons=backend.has_schema(DESKTOP_ICONS_SCHEMA),
        fonts=font_voices(font, mono, installed_font_families() if fonts is None else fonts),
        screen=primary_screen() if screen is None else screen,
        installed=installed,
        extensions_allowed=allowed,
    )
