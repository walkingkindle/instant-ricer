"""Apply a Look to the desktop, remembering what was there so it can be put back."""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ricer import placement, shell_theme
from ricer.backends import gv, gv_uint
from ricer.capabilities import MEDIA_CONTROLS_UUID, VITALS_UUID, Capabilities
from ricer.compose import remember
from ricer.look import Look, LookError
from ricer.palette import GNOME_ACCENT_NAMES
from ricer.paths import THEME_NAME, Paths

BACKGROUND = "/org/gnome/desktop/background/"
SCREENSAVER = "/org/gnome/desktop/screensaver/"
INTERFACE = "/org/gnome/desktop/interface/"
DOCK = "/org/gnome/shell/extensions/dash-to-dock/"
USER_THEME_NAME = "/org/gnome/shell/extensions/user-theme/name"
BLUR = "/org/gnome/shell/extensions/blur-my-shell/"
VITALS = "/org/gnome/shell/extensions/vitals/"
MEDIA = "/org/gnome/shell/extensions/mediacontrols/"
DESKTOP_ICONS = "/org/gnome/shell/extensions/ding/"
TERMINAL_PROFILES = "/org/gnome/terminal/legacy/profiles:/"

FANCY_ICONS = ("Papirus-Dark",)      # used by "fancy" looks when installed
FANCY_CURSORS = ("Bibata-Modern-Ice",)
STOCK_CURSORS = ("Yaru", "Adwaita")
RESOURCE_SHELL_THEME = 'url("resource:///org/gnome/shell/theme/gnome-shell-dark.css")'
# what Vitals calls each sensor ricer can ask for
VITALS_SENSORS = {"cpu": "_processor_usage_", "ram": "_memory_usage_", "temp": "__temperature_avg__",
                  "net": "__network-rx_max__", "battery": "_battery_percentage_"}
VITALS_SIDES = {"left": 0, "center": 1, "right": 2}
# Settings an extension only reads when it starts. If one changes while the extension stays
# switched on, the extension is restarted so the change shows.
RESTART_ON_CHANGE = {VITALS_UUID: (VITALS + "hot-sensors",)}


class ApplyError(RuntimeError):
    """Applying failed part-way; everything written so far was put back."""


@dataclass
class Plan:
    settings: dict[str, str] = field(default_factory=dict)       # dconf path -> GVariant text
    files: dict[Path, str | None] = field(default_factory=dict)  # None means "must not exist"
    extensions: dict[str, bool] = field(default_factory=dict)    # uuid -> switched on
    restore: list[str] = field(default_factory=list)             # settings to hand back as they were
    notices: list[str] = field(default_factory=list)


@dataclass
class Result:
    changed: int
    notices: list[str]


def _first_installed(candidates, installed) -> str | None:
    return next((name for name in candidates if name in installed), None)


def widgets_config(look: Look, caps: Capabilities) -> dict:
    """What the widget daemon reads."""
    return {
        "font": caps.font,
        "display_font": caps.font_for(look.style.voice),
        "clock_24h": caps.clock_24h,
        "style": asdict(look.style),
        "palette": asdict(look.palette),
        "insets": list(placement.dock_insets(look.dock)),
        "widgets": [asdict(widget) for widget in look.widgets] if caps.widgets else [],
    }


def autostart_entry() -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Ricer Widgets\n"
        "Comment=Desktop widgets drawn by ricer\n"
        f"Exec={sys.executable} -m ricer.widgets.daemon\n"
        "X-GNOME-Autostart-enabled=true\n"
        "X-GNOME-Autostart-Delay=3\n"
        "NoDisplay=true\n"
    )


def _theme_and_icons(look: Look, caps: Capabilities, settings: dict) -> str:
    """Wallpaper, colour scheme, app theme, icons and cursor. Returns the Yaru variant suffix."""
    yaru = "" if look.gtk_accent == "default" else f"-{look.gtk_accent}"
    uri = Path(look.wallpaper).as_uri()
    settings[BACKGROUND + "picture-uri"] = gv(uri)
    settings[BACKGROUND + "picture-uri-dark"] = gv(uri)
    settings[BACKGROUND + "picture-options"] = gv("zoom")
    settings[SCREENSAVER + "picture-uri"] = gv(uri)
    settings[INTERFACE + "color-scheme"] = gv("prefer-dark")

    gtk_theme = _first_installed((f"Yaru{yaru}-dark", "Yaru-dark"), caps.gtk_themes)
    if gtk_theme:
        settings[INTERFACE + "gtk-theme"] = gv(gtk_theme)
    if caps.accent_color:
        settings[INTERFACE + "accent-color"] = gv(GNOME_ACCENT_NAMES[look.gtk_accent])

    fancy = look.icon_style == "fancy"
    stock_icons = (f"Yaru{yaru}-dark", "Yaru-dark", "Adwaita")
    icons = _first_installed((*FANCY_ICONS, *stock_icons) if fancy else stock_icons, caps.icon_themes)
    if icons:
        settings[INTERFACE + "icon-theme"] = gv(icons)
    cursor = _first_installed((*FANCY_CURSORS, *STOCK_CURSORS) if fancy else STOCK_CURSORS,
                              caps.icon_themes)
    if cursor:
        settings[INTERFACE + "cursor-theme"] = gv(cursor)
    return yaru


def _dock(look: Look, caps: Capabilities, plan: Plan) -> None:
    if not caps.dock:
        plan.notices.append("Dock left alone: Dash to Dock / Ubuntu Dock not found.")
        return
    dock, settings = look.dock, plan.settings
    settings[DOCK + "dock-position"] = gv(dock.position)
    settings[DOCK + "extend-height"] = gv(not dock.floating)
    settings[DOCK + "dock-fixed"] = gv(not dock.autohide)
    settings[DOCK + "autohide"] = gv(dock.autohide)
    settings[DOCK + "intellihide"] = gv(dock.autohide)
    settings[DOCK + "transparency-mode"] = gv("FIXED")
    settings[DOCK + "background-opacity"] = gv(dock.opacity)
    settings[DOCK + "dash-max-icon-size"] = gv(dock.icon_size)
    settings[DOCK + "running-indicator-style"] = gv(dock.indicator)
    settings[DOCK + "custom-background-color"] = gv(dock.tint)
    settings[DOCK + "background-color"] = gv(look.palette.card)


def _bar(look: Look, caps: Capabilities, plan: Plan, paths: Paths, yaru: str) -> None:
    """The bar's own style, and the extensions that put widgets inside it."""
    bar, settings, notices = look.bar, plan.settings, plan.notices
    if caps.user_theme:
        if bar.style == "stock":
            settings[USER_THEME_NAME] = gv("")
        else:
            stock = _first_installed((f"Yaru{yaru}-dark", "Yaru-dark"), caps.shell_themes)
            base = f'url("{caps.shell_themes[stock]}")' if stock else RESOURCE_SHELL_THEME
            plan.files[paths.shell_theme_file] = shell_theme.render(look, base)
            settings[USER_THEME_NAME] = gv(THEME_NAME)
    elif bar.style != "stock":
        notices.append("Top bar left alone: it needs the 'User Themes' extension (ricer setup).")

    if caps.vitals:
        plan.extensions[VITALS_UUID] = bool(bar.stats)
        if bar.stats:
            settings[VITALS + "hot-sensors"] = gv([VITALS_SENSORS[sensor] for sensor in bar.stats])
            settings[VITALS + "position-in-panel"] = gv(VITALS_SIDES[bar.stats_side])
            settings[VITALS + "show-battery"] = gv("battery" in bar.stats)
            settings[VITALS + "fixed-widths"] = gv(True)
            settings[VITALS + "hide-icons"] = gv(False)
            settings[VITALS + "update-time"] = gv(3)
    elif bar.stats:
        notices.append("No stats in the top bar: they need the 'Vitals' extension (ricer setup).")

    if caps.media_controls:
        plan.extensions[MEDIA_CONTROLS_UUID] = bar.media
        if bar.media:
            settings[MEDIA + "extension-position"] = gv(bar.media_side.capitalize())
            # after the workspace indicator or the clock; ahead of everything on the right
            settings[MEDIA + "extension-index"] = gv_uint(0 if bar.media_side == "right" else 1)
            settings[MEDIA + "label-width"] = gv_uint(round(200 * look.style.scale))
            settings[MEDIA + "show-label"] = gv(True)
            settings[MEDIA + "show-player-icon"] = gv(True)
            settings[MEDIA + "show-control-icons"] = gv(True)
            settings[MEDIA + "show-control-icons-previous"] = gv(look.dials.ease >= 9)
            settings[MEDIA + "show-control-icons-seek-backward"] = gv(False)
            settings[MEDIA + "show-control-icons-seek-forward"] = gv(False)
    elif bar.media:
        notices.append("No player in the top bar: it needs the 'Media Controls' extension (ricer setup).")


def _terminal(look: Look, caps: Capabilities, settings: dict) -> None:
    if not caps.terminal_profile:
        return
    profile = f"{TERMINAL_PROFILES}:{caps.terminal_profile}/"
    settings[profile + "use-theme-colors"] = gv(False)
    settings[profile + "use-theme-transparency"] = gv(False)
    settings[profile + "use-transparent-background"] = gv(True)
    settings[profile + "background-transparency-percent"] = gv(
        round(40 * (1 - max(0.5, look.style.fill))))
    settings[profile + "background-color"] = gv(look.terminal["background"])
    settings[profile + "foreground-color"] = gv(look.terminal["foreground"])
    settings[profile + "bold-color-same-as-fg"] = gv(True)
    settings[profile + "palette"] = gv(look.terminal["palette"])


def build_plan(look: Look, caps: Capabilities, paths: Paths) -> Plan:
    """Work out every setting, file and extension the look needs here. Touches nothing."""
    plan = Plan()
    settings, notices = plan.settings, plan.notices

    yaru = _theme_and_icons(look, caps, settings)
    _dock(look, caps, plan)
    _bar(look, caps, plan, paths, yaru)

    if caps.blur:
        settings[BLUR + "dash-to-dock/blur"] = gv(look.blur)
        settings[BLUR + "dash-to-dock/static-blur"] = gv(True)
        # a tinted dock keeps its own colour; otherwise the blur extension paints the dock
        settings[BLUR + "dash-to-dock/override-background"] = gv(not look.dock.tint)
        settings[BLUR + "overview/blur"] = gv(look.blur)
        # a blurred strip would show through floating bar pieces, so only the stock bar gets it
        settings[BLUR + "panel/blur"] = gv(look.blur and look.bar.style == "stock")
    elif look.blur:
        notices.append("No blur: it needs the 'Blur my Shell' extension (ricer setup).")

    _terminal(look, caps, settings)

    config = widgets_config(look, caps)
    plan.files[paths.widgets_file] = json.dumps(config, indent=2) + "\n"
    plan.files[paths.autostart_file] = autostart_entry() if config["widgets"] else None
    if look.widgets and not caps.widgets:
        notices.append(f"No desktop widgets: they need an X11 session (this one is {caps.session}).")

    if caps.desktop_icons:
        icons = (DESKTOP_ICONS + "show-home", DESKTOP_ICONS + "show-volumes")
        if config["widgets"]:
            for path in icons:                               # they would sit under the widgets
                settings[path] = gv(False)
        else:
            plan.restore.extend(icons)                       # back to however the user had them
    return plan


def _read(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


def _put(path: Path, content: str | None) -> None:
    if content is None:
        path.unlink(missing_ok=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


class Engine:
    def __init__(self, backend, paths: Paths, daemon=None):
        self.backend = backend
        self.paths = paths
        self.daemon = daemon

    # -- state ----------------------------------------------------------
    def load_state(self) -> dict:
        try:
            return json.loads(self.paths.state_file.read_text())
        except (OSError, ValueError):
            return {}

    def _save_state(self, state: dict) -> None:
        _put(self.paths.state_file, json.dumps(state, indent=2) + "\n")

    def current_look(self) -> Look | None:
        """The look ricer last applied, or None (also for one saved by an older version)."""
        data = self.load_state().get("look")
        try:
            return Look.from_dict(data) if data else None
        except LookError:
            return None

    def history(self) -> list[dict]:
        """Fingerprints of the looks applied recently, newest first."""
        return self.load_state().get("history", [])

    # -- the default look -----------------------------------------------
    # Stored whole, not as dials and a seed: a seed only leads back to a look while the
    # wallpaper folder and the generator stay as they were, and a default has to outlast both.
    def save_default(self) -> Look | None:
        """Keep the current look as the one to come back to. None if no look is applied."""
        look = self.current_look()
        if look is not None:
            _put(self.paths.default_file, json.dumps(look.to_dict(), indent=2) + "\n")
        return look

    def default_look(self) -> Look | None:
        """The saved default look; None if there is none or this version cannot read it."""
        try:
            return Look.from_dict(json.loads(self.paths.default_file.read_text()))
        except (OSError, ValueError):                        # LookError is a ValueError
            return None

    def clear_default(self) -> bool:
        existed = self.paths.default_file.exists()
        self.paths.default_file.unlink(missing_ok=True)
        return existed

    # -- apply / revert -------------------------------------------------
    def _set(self, path: str, value: str | None) -> None:
        if value is None:
            self.backend.reset(path)
        else:
            self.backend.write(path, value)

    def _restore(self, settings: dict, files: dict, extensions: dict) -> None:
        for path, content in files.items():
            _put(Path(path), content)
        for path, value in settings.items():
            self._set(path, value)
        for uuid, enabled in extensions.items():
            self.backend.set_extension_enabled(uuid, enabled)

    def _restart_stale(self, changed_settings, switched_extensions) -> None:
        """Restart extensions whose start-up-only settings changed while they stayed on."""
        for uuid, paths in RESTART_ON_CHANGE.items():
            if (uuid not in switched_extensions and any(path in changed_settings for path in paths)
                    and self.backend.extension_enabled(uuid)):
                self.backend.set_extension_enabled(uuid, False)
                self.backend.set_extension_enabled(uuid, True)

    def apply(self, look: Look, caps: Capabilities) -> Result:
        plan = build_plan(look, caps, self.paths)
        state = self.load_state()
        original = state.get("original") or {}

        targets: dict[str, str | None] = dict(plan.settings)
        for path in plan.restore:
            # only what ricer itself changed earlier is handed back; the rest was never touched
            if path in original.get("settings", {}):
                targets[path] = original["settings"][path]

        before_settings = {path: self.backend.read(path) for path in targets}
        before_files = {str(path): _read(path) for path in plan.files}
        before_extensions = {uuid: self.backend.extension_enabled(uuid) for uuid in plan.extensions}
        changed_settings = {path: value for path, value in targets.items()
                            if not self.backend.same(before_settings[path], value)}
        changed_files = {path: content for path, content in plan.files.items()
                         if before_files[str(path)] != content}
        changed_extensions = {uuid: enabled for uuid, enabled in plan.extensions.items()
                              if before_extensions[uuid] != enabled}

        done_settings, done_files, done_extensions = {}, {}, {}
        try:
            # files first: the stylesheet has to exist before the theme setting points at it
            for path, content in changed_files.items():
                _put(path, content)
                done_files[str(path)] = before_files[str(path)]
            for path, value in changed_settings.items():
                self._set(path, value)
                done_settings[path] = before_settings[path]
            # extensions last, so each one starts up already configured
            for uuid, enabled in changed_extensions.items():
                self.backend.set_extension_enabled(uuid, enabled)
                done_extensions[uuid] = before_extensions[uuid]
        except Exception as error:
            self._restore(done_settings, done_files, done_extensions)
            raise ApplyError(f"could not apply the look, nothing was changed: {error}") from error

        if self.paths.shell_theme_file in changed_files and USER_THEME_NAME not in changed_settings:
            self.backend.reload_shell_theme(USER_THEME_NAME)
        self._restart_stale(changed_settings, changed_extensions)

        done = {"settings": done_settings, "files": done_files, "extensions": done_extensions}
        changed = sum(len(part) for part in done.values())
        if changed:
            state["snapshot"] = {**done, "look": state.get("look")}
            first = state.setdefault("original", {})
            for kind, part in done.items():
                for key, value in part.items():
                    first.setdefault(kind, {}).setdefault(key, value)
        saved = json.loads(json.dumps(look.to_dict()))          # as it will read back from the file
        if changed or state.get("look") != saved:
            state["history"] = remember(state.get("history", []), look)
        state["look"] = saved
        self._save_state(state)
        if self.daemon:
            self.daemon.sync()
        return Result(changed=changed, notices=plan.notices)

    def revert(self, everything: bool = False) -> int:
        """Undo the last apply, or with `everything` all of ricer's changes. Returns how many."""
        state = self.load_state()
        snapshot = state.get("original" if everything else "snapshot") or {}
        settings, files = snapshot.get("settings", {}), snapshot.get("files", {})
        extensions = snapshot.get("extensions", {})
        if not (settings or files or extensions):
            return 0
        self._restore(settings, files, extensions)
        if str(self.paths.shell_theme_file) in files:
            self.backend.reload_shell_theme(USER_THEME_NAME)
        self._restart_stale(settings, extensions)
        state.pop("snapshot", None)
        # undoing one apply puts the look before it back in charge
        state["look"] = None if everything else snapshot.get("look")
        if everything:
            state.pop("original", None)
            state.pop("history", None)
        self._save_state(state)
        if self.daemon:
            self.daemon.sync()
        return len(settings) + len(files) + len(extensions)
