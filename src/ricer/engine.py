"""Apply a Look to the desktop, remembering what was there so it can be put back."""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ricer import shell_theme
from ricer.backends import gv
from ricer.capabilities import Capabilities
from ricer.look import Look
from ricer.palette import GNOME_ACCENT_NAMES
from ricer.paths import THEME_NAME, Paths

BACKGROUND = "/org/gnome/desktop/background/"
SCREENSAVER = "/org/gnome/desktop/screensaver/"
INTERFACE = "/org/gnome/desktop/interface/"
DOCK = "/org/gnome/shell/extensions/dash-to-dock/"
USER_THEME_NAME = "/org/gnome/shell/extensions/user-theme/name"
BLUR = "/org/gnome/shell/extensions/blur-my-shell/"
TERMINAL_PROFILES = "/org/gnome/terminal/legacy/profiles:/"

ICON_THEMES = ("Papirus-Dark",)      # used when installed, ahead of the accent-matched stock set
CURSOR_THEMES = ("Bibata-Modern-Ice",)
RESOURCE_SHELL_THEME = 'url("resource:///org/gnome/shell/theme/gnome-shell-dark.css")'


class ApplyError(RuntimeError):
    """Applying failed part-way; everything written so far was put back."""


@dataclass
class Plan:
    settings: dict[str, str] = field(default_factory=dict)       # dconf path -> GVariant text
    files: dict[Path, str | None] = field(default_factory=dict)  # None means "must not exist"
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
        "clock_24h": caps.clock_24h,
        "scale": look.widget_scale,
        "gradient": look.gradient,
        "palette": asdict(look.palette),
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


def build_plan(look: Look, caps: Capabilities, paths: Paths) -> Plan:
    """Work out every setting and file the look needs on this desktop. Touches nothing."""
    plan = Plan()
    settings, notices = plan.settings, plan.notices
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
    icons = _first_installed((*ICON_THEMES, f"Yaru{yaru}-dark", "Yaru-dark"), caps.icon_themes)
    if icons:
        settings[INTERFACE + "icon-theme"] = gv(icons)
    cursor = _first_installed(CURSOR_THEMES, caps.icon_themes)
    if cursor:
        settings[INTERFACE + "cursor-theme"] = gv(cursor)

    if caps.dock:
        dock = look.dock
        settings[DOCK + "dock-position"] = gv(dock.position)
        settings[DOCK + "extend-height"] = gv(not dock.floating)
        settings[DOCK + "dock-fixed"] = gv(not dock.autohide)
        settings[DOCK + "autohide"] = gv(dock.autohide)
        settings[DOCK + "intellihide"] = gv(dock.autohide)
        settings[DOCK + "transparency-mode"] = gv("FIXED")
        settings[DOCK + "background-opacity"] = gv(dock.opacity)
        settings[DOCK + "dash-max-icon-size"] = gv(dock.icon_size)
        settings[DOCK + "running-indicator-style"] = gv("DASHES" if look.gradient else "DOTS")
    else:
        notices.append("Dock left alone: Dash to Dock / Ubuntu Dock not found.")

    if caps.user_theme:
        if look.bar_style == "stock":
            settings[USER_THEME_NAME] = gv("")
        else:
            stock = _first_installed((f"Yaru{yaru}-dark", "Yaru-dark"), caps.shell_themes)
            base = f'url("{caps.shell_themes[stock]}")' if stock else RESOURCE_SHELL_THEME
            plan.files[paths.shell_theme_file] = shell_theme.render(look, base)
            settings[USER_THEME_NAME] = gv(THEME_NAME)
    elif look.bar_style != "stock":
        notices.append("Top bar left alone: enable the 'User Themes' extension to style it.")

    if caps.blur:
        settings[BLUR + "dash-to-dock/blur"] = gv(look.blur)
        settings[BLUR + "dash-to-dock/static-blur"] = gv(True)
        settings[BLUR + "overview/blur"] = gv(look.blur)
        # a blurred strip would show through the floating cards, so only the stock bar gets it
        settings[BLUR + "panel/blur"] = gv(look.blur and look.bar_style == "stock")
    elif look.blur:
        notices.append("No blur: enable the 'Blur my Shell' extension to get it.")

    if caps.terminal_profile:
        profile = f"{TERMINAL_PROFILES}:{caps.terminal_profile}/"
        settings[profile + "use-theme-colors"] = gv(False)
        settings[profile + "use-theme-transparency"] = gv(False)
        settings[profile + "use-transparent-background"] = gv(True)
        settings[profile + "background-transparency-percent"] = gv(
            round(100 * (1 - look.palette.card_alpha) * 0.4))
        settings[profile + "background-color"] = gv(look.terminal["background"])
        settings[profile + "foreground-color"] = gv(look.terminal["foreground"])
        settings[profile + "bold-color-same-as-fg"] = gv(True)
        settings[profile + "palette"] = gv(look.terminal["palette"])

    config = widgets_config(look, caps)
    plan.files[paths.widgets_file] = json.dumps(config, indent=2) + "\n"
    plan.files[paths.autostart_file] = autostart_entry() if config["widgets"] else None
    if look.widgets and not caps.widgets:
        notices.append(f"No desktop widgets: they need an X11 session (this one is {caps.session}).")
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
        data = self.load_state().get("look")
        return Look.from_dict(data) if data else None

    # -- apply / revert -------------------------------------------------
    def _restore(self, settings: dict, files: dict) -> None:
        for path, content in files.items():
            _put(Path(path), content)
        for path, value in settings.items():
            if value is None:
                self.backend.reset(path)
            else:
                self.backend.write(path, value)

    def apply(self, look: Look, caps: Capabilities) -> Result:
        plan = build_plan(look, caps, self.paths)
        before_settings = {path: self.backend.read(path) for path in plan.settings}
        before_files = {str(path): _read(path) for path in plan.files}
        changed_settings = {path: value for path, value in plan.settings.items()
                            if not self.backend.same(before_settings[path], value)}
        changed_files = {path: content for path, content in plan.files.items()
                         if before_files[str(path)] != content}

        done_settings, done_files = {}, {}
        try:
            # files first: the stylesheet has to exist before the theme setting points at it
            for path, content in changed_files.items():
                _put(path, content)
                done_files[str(path)] = before_files[str(path)]
            for path, value in changed_settings.items():
                self.backend.write(path, value)
                done_settings[path] = before_settings[path]
        except Exception as error:
            self._restore(done_settings, done_files)
            raise ApplyError(f"could not apply the look, nothing was changed: {error}") from error

        if self.paths.shell_theme_file in changed_files and USER_THEME_NAME not in changed_settings:
            self.backend.reload_shell_theme(USER_THEME_NAME)

        state = self.load_state()
        if done_settings or done_files:
            state["snapshot"] = {"settings": done_settings, "files": done_files,
                                 "look": state.get("look")}
            original = state.setdefault("original", {"settings": {}, "files": {}})
            for kind, done in (("settings", done_settings), ("files", done_files)):
                for key, value in done.items():
                    original[kind].setdefault(key, value)
        state["look"] = look.to_dict()
        self._save_state(state)
        if self.daemon:
            self.daemon.sync()
        return Result(changed=len(done_settings) + len(done_files), notices=plan.notices)

    def revert(self, everything: bool = False) -> int:
        """Undo the last apply, or with `everything` all of ricer's changes. Returns how many."""
        state = self.load_state()
        snapshot = state.get("original" if everything else "snapshot")
        if not snapshot or not (snapshot["settings"] or snapshot["files"]):
            return 0
        self._restore(snapshot["settings"], snapshot["files"])
        if str(self.paths.shell_theme_file) in snapshot["files"]:
            self.backend.reload_shell_theme(USER_THEME_NAME)
        state.pop("snapshot", None)
        # undoing one apply puts the look before it back in charge
        state["look"] = None if everything else snapshot.get("look")
        if everything:
            state.pop("original", None)
        self._save_state(state)
        if self.daemon:
            self.daemon.sync()
        return len(snapshot["settings"]) + len(snapshot["files"])
