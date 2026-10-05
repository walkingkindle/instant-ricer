"""Apply a Look to the desktop, remembering what was there so it can be put back."""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ricer import gtk_theme, placement, shell_theme
from ricer.backends import gv, gv_uint
from ricer.capabilities import MEDIA_CONTROLS_UUID, VITALS_UUID, Capabilities
from ricer.compose import remember
from ricer.look import Look, LookError
from ricer.palette import GNOME_ACCENT_NAMES, YARU_ACCENT_HUES, hue_distance, terminal_transparency
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
GTK_THEME = INTERFACE + "gtk-theme"

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
    links: dict[Path, str | None] = field(default_factory=dict)  # symlink -> what it points at
    blocks: dict[Path, str | None] = field(default_factory=dict) # ricer's block in a file the user owns
    sheets: dict[Path, str] = field(default_factory=dict)        # stylesheets named after their content
    extensions: dict[str, bool] = field(default_factory=dict)    # uuid -> switched on
    restore: list[str] = field(default_factory=list)             # settings to hand back as they were
    notices: list[str] = field(default_factory=list)


# What a snapshot records, in the order it is written and put back: files before the settings
# that point at them, extensions last so that each one starts up already configured.
KINDS = ("files", "links", "blocks", "settings", "extensions")


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


def _theme_and_icons(look: Look, caps: Capabilities, settings: dict) -> tuple[str, str | None]:
    """Wallpaper, colour scheme, app theme, icons and cursor.

    Returns the Yaru variant suffix and the app theme that was chosen, if any.
    """
    yaru = "" if look.gtk_accent == "default" else f"-{look.gtk_accent}"
    uri = Path(look.wallpaper).as_uri()
    settings[BACKGROUND + "picture-uri"] = gv(uri)
    settings[BACKGROUND + "picture-uri-dark"] = gv(uri)
    settings[BACKGROUND + "picture-options"] = gv("zoom")
    settings[SCREENSAVER + "picture-uri"] = gv(uri)
    settings[INTERFACE + "color-scheme"] = gv("prefer-dark")

    app_theme = _first_installed((f"Yaru{yaru}-dark", "Yaru-dark"), caps.gtk_themes)
    if app_theme:
        settings[GTK_THEME] = gv(app_theme)
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
    return yaru, app_theme


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


def _transparency(look: Look) -> int:
    """Percent of the terminal's background that lets the desktop through."""
    return look.terminal.get("transparency", terminal_transparency(look.style.fill))


def _terminal(look: Look, caps: Capabilities, settings: dict) -> None:
    if not caps.terminal_profile:
        return
    profile = f"{TERMINAL_PROFILES}:{caps.terminal_profile}/"
    settings[profile + "use-theme-colors"] = gv(False)
    if caps.terminal_glass:
        settings[profile + "use-theme-transparency"] = gv(False)
        settings[profile + "use-transparent-background"] = gv(True)
        settings[profile + "background-transparency-percent"] = gv(_transparency(look))
    settings[profile + "background-color"] = gv(look.terminal["background"])
    settings[profile + "foreground-color"] = gv(look.terminal["foreground"])
    settings[profile + "bold-color-same-as-fg"] = gv(True)
    settings[profile + "palette"] = gv(look.terminal["palette"])


def sibling_theme(theme: str) -> str | None:
    """The Yaru variant nearest in hue to this one, or None for a theme that is not Yaru's.

    Flipping the theme name through it makes apps re-read a theme whose name has not changed.
    """
    match = re.fullmatch(r"Yaru(?:-([a-z]+))?-dark", theme)
    accent = (match.group(1) or "default") if match else None
    if accent not in YARU_ACCENT_HUES:
        return None
    nearest = min((name for name in YARU_ACCENT_HUES if name != accent),
                  key=lambda name: (hue_distance(YARU_ACCENT_HUES[name], YARU_ACCENT_HUES[accent]), name))
    return "Yaru-dark" if nearest == "default" else f"Yaru-{nearest}-dark"


def _shadow(paths: Paths, theme: str) -> tuple[list[Path], list[Path]]:
    """Where a recoloured theme goes: its stylesheets, and the links to the stock pictures.

    GTK 3 apps load the theme by its name. Apps built on libhandy, GNOME Terminal among
    them, drop a "-dark" from the name and ask for the dark variant of what is left.
    """
    folder = paths.themes_dir / theme / "gtk-3.0"
    sheets, links = [folder / "gtk.css", folder / "gtk-dark.css"], [folder / "gtk.gresource"]
    if theme.endswith("-dark"):
        plain = paths.themes_dir / theme[:-len("-dark")] / "gtk-3.0"
        sheets.append(plain / "gtk-dark.css")
        links.append(plain / "gtk.gresource")
    return sheets, links


def _ours(path: Path) -> bool:
    try:
        with path.open() as file:
            return gtk_theme.is_ours(file.read(len(gtk_theme.MARK)))
    except (OSError, UnicodeError):
        return False


def _left_behind(paths: Paths) -> tuple[list[Path], list[Path]]:
    """Theme files an earlier look put in the user's themes folder."""
    sheets, links = [], []
    for folder in sorted(paths.themes_dir.glob("*/gtk-3.0")):
        mine = [css for css in sorted(folder.glob("*.css")) if _ours(css)]
        sheets += mine
        if mine and (folder / "gtk.gresource").is_symlink():
            links.append(folder / "gtk.gresource")
    return sheets, links


def _windows(look: Look, caps: Capabilities, plan: Plan, paths: Paths, theme: str | None) -> None:
    """Window colours: the app theme recoloured under its own name, and the same colours by
    name for libadwaita apps, which take no theme."""
    plan.blocks[paths.gtk4_css_file] = gtk_theme.adwaita(look)

    old_sheets, old_links = _left_behind(paths)
    plan.files.update({path: None for path in old_sheets})   # whatever this look does not rewrite
    plan.links.update({path: None for path in old_links})

    folder = Path(caps.gtk3_themes[theme]) if theme in caps.gtk3_themes else None
    stock = gtk_theme.stock_sheet(folder) if folder else None
    if stock is None:
        plan.notices.append("GTK 3 apps and the terminal's frame keep the stock colours: "
                            "no app theme here that ricer can recolour (it needs Yaru).")
        return
    sheets, links = _shadow(paths, theme)
    if any(path.exists() and not _ours(path) for path in sheets) or any(
            path.exists() and not path.is_symlink() for path in links):
        plan.notices.append(f"GTK 3 apps and the terminal's frame keep the stock colours: you have "
                            f"your own copy of {theme} in {paths.themes_dir}, which ricer leaves alone.")
        return

    # a see-through terminal gets a frame to match
    glass = 1 - _transparency(look) / 100 if caps.terminal_profile and caps.terminal_glass else None
    css = gtk_theme.render(stock, look, glass)
    sheet = paths.sheets_dir / gtk_theme.sheet_name(css)
    plan.sheets[sheet] = css
    bundle = folder / "gtk.gresource"
    plan.files.update({path: gtk_theme.stub(sheet) for path in sheets})
    plan.links.update({path: str(bundle) if bundle.exists() else None for path in links})


def build_plan(look: Look, caps: Capabilities, paths: Paths) -> Plan:
    """Work out every setting, file and extension the look needs here. Touches nothing."""
    plan = Plan()
    settings, notices = plan.settings, plan.notices

    yaru, app_theme = _theme_and_icons(look, caps, settings)
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
    _windows(look, caps, plan, paths, app_theme)

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


def _target(path: Path) -> str | None:
    """What a symlink points at; None if there is no symlink there."""
    return os.readlink(path) if path.is_symlink() else None


def _point(path: Path, target: str | None) -> None:
    if path.is_symlink():
        path.unlink()
    if target is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)


def _put_block(path: Path, block: str | None) -> None:
    """Set or remove ricer's block in a file that is the user's, leaving the rest as it is."""
    text = _read(path)
    new = gtk_theme.with_block(text, block) if block else gtk_theme.without_block(text or "")
    _put(path, new if new.strip() else None)                 # nothing else in it: no file


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

    def _write(self, kind: str, key, value) -> None:
        """Put one setting, file, link, block or extension into the given state."""
        if kind == "settings":
            self._set(key, value)
        elif kind == "extensions":
            self.backend.set_extension_enabled(key, value)
        else:
            path = Path(key)
            {"files": _put, "links": _point, "blocks": _put_block}[kind](path, value)
            if value is None:
                self._tidy(path)

    def _tidy(self, path: Path) -> None:
        """Remove the theme folders that a deleted file leaves empty."""
        folder = path.parent
        while self.paths.themes_dir in folder.parents:
            try:
                folder.rmdir()
            except OSError:                                  # not empty, or already gone
                return
            folder = folder.parent

    def _restore(self, done: dict) -> None:
        for kind in KINDS:
            for key, value in done.get(kind, {}).items():
                self._write(kind, key, value)

    def _refresh_windows(self, done: dict) -> None:
        """Get running apps to show window colours that changed underneath them.

        GTK 3 apps re-read a theme only when its name changes, and GNOME Terminal not even
        then, so both are told. libadwaita apps cannot be: they read colours when they start.
        """
        themes = str(self.paths.themes_dir)
        touched = bool(done.get("links")) or any(
            path.startswith(themes) and "/gtk-3.0/" in path for path in done.get("files", {}))
        renamed = GTK_THEME in done.get("settings", {})
        if touched and not renamed:
            sibling = sibling_theme((self.backend.read(GTK_THEME) or "").strip("'"))
            if sibling:
                self.backend.reload_gtk_theme(GTK_THEME, sibling)
        if touched or renamed:
            self.backend.nudge_terminal()

    def _sweep(self, state: dict) -> None:
        """Delete generated stylesheets that nothing points at any more.

        One is still wanted while a theme file imports it or the state holds a theme file
        that does, which is what lets `revert` bring the previous look's colours back.
        """
        sheets = list(self.paths.sheets_dir.glob("*.css"))
        if not sheets:
            return
        wanted = json.dumps(state) + "".join(
            _read(css) or "" for css in self.paths.themes_dir.glob("*/gtk-3.0/*.css") if _ours(css))
        for sheet in sheets:
            if sheet.name not in wanted:
                sheet.unlink(missing_ok=True)
        for folder in (self.paths.sheets_dir, self.paths.sheets_dir.parent):
            try:
                folder.rmdir()                               # only when nothing is left in it
            except OSError:
                break

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

        settings: dict[str, str | None] = dict(plan.settings)
        for path in plan.restore:
            # only what ricer itself changed earlier is handed back; the rest was never touched
            if path in original.get("settings", {}):
                settings[path] = original["settings"][path]

        wanted = {
            "files": {str(path): content for path, content in plan.files.items()},
            "links": {str(path): target for path, target in plan.links.items()},
            "blocks": {str(path): block for path, block in plan.blocks.items()},
            "settings": settings,
            "extensions": dict(plan.extensions),
        }
        before = {
            "files": {path: _read(Path(path)) for path in wanted["files"]},
            "links": {path: _target(Path(path)) for path in wanted["links"]},
            "blocks": {path: gtk_theme.block_in(_read(Path(path))) for path in wanted["blocks"]},
            "settings": {path: self.backend.read(path) for path in settings},
            "extensions": {uuid: self.backend.extension_enabled(uuid) for uuid in plan.extensions},
        }

        def same(kind: str, a, b) -> bool:
            return self.backend.same(a, b) if kind == "settings" else a == b

        changed = {kind: {key: value for key, value in wanted[kind].items()
                          if not same(kind, before[kind][key], value)} for kind in KINDS}

        done: dict[str, dict] = {kind: {} for kind in KINDS}
        try:
            for path, content in plan.sheets.items():        # named after their content: never rewritten
                if not path.exists():
                    _put(path, content)
            for kind in KINDS:
                for key, value in changed[kind].items():
                    self._write(kind, key, value)
                    done[kind][key] = before[kind][key]
        except Exception as error:
            self._restore(done)
            self._sweep(state)
            raise ApplyError(f"could not apply the look, nothing was changed: {error}") from error

        if (str(self.paths.shell_theme_file) in changed["files"]
                and USER_THEME_NAME not in changed["settings"]):
            self.backend.reload_shell_theme(USER_THEME_NAME)
        self._restart_stale(changed["settings"], changed["extensions"])
        self._refresh_windows(changed)

        count = sum(len(part) for part in done.values())
        if count:
            state["snapshot"] = {**done, "look": state.get("look")}
            first = state.setdefault("original", {})
            for kind, part in done.items():
                for key, value in part.items():
                    first.setdefault(kind, {}).setdefault(key, value)
        saved = json.loads(json.dumps(look.to_dict()))          # as it will read back from the file
        if count or state.get("look") != saved:
            state["history"] = remember(state.get("history", []), look)
        state["look"] = saved
        self._save_state(state)
        self._sweep(state)
        if self.daemon:
            self.daemon.sync()
        return Result(changed=count, notices=plan.notices)

    def revert(self, everything: bool = False) -> int:
        """Undo the last apply, or with `everything` all of ricer's changes. Returns how many."""
        state = self.load_state()
        snapshot = state.get("original" if everything else "snapshot") or {}
        done = {kind: snapshot.get(kind, {}) for kind in KINDS}
        count = sum(len(part) for part in done.values())
        if not count:
            return 0
        self._restore(done)
        if str(self.paths.shell_theme_file) in done["files"]:
            self.backend.reload_shell_theme(USER_THEME_NAME)
        self._restart_stale(done["settings"], done["extensions"])
        self._refresh_windows(done)
        state.pop("snapshot", None)
        # undoing one apply puts the look before it back in charge
        state["look"] = None if everything else snapshot.get("look")
        if everything:
            state.pop("original", None)
            state.pop("history", None)
        self._save_state(state)
        self._sweep(state)
        if self.daemon:
            self.daemon.sync()
        return count
