from ricer.backends import FakeBackend
from ricer.capabilities import BLUR_UUID, DOCK_SCHEMA, TERMINAL_SCHEMA, USER_THEME_UUID, detect

SHELL = "org.gnome.shell"
IFACE = "org.gnome.desktop.interface"


def test_detects_an_ubuntu_like_desktop(paths, tmp_path):
    system = tmp_path / "usr-share"
    (system / "themes/Yaru-blue-dark").mkdir(parents=True)
    (system / "icons/Papirus-Dark").mkdir(parents=True)
    (system / "gnome-shell/theme/Yaru-dark").mkdir(parents=True)
    (system / "gnome-shell/theme/Yaru-dark/gnome-shell.css").write_text("")
    (paths.data / "icons/Bibata-Modern-Ice").mkdir(parents=True)
    (paths.home / ".themes/Mine").mkdir(parents=True)
    backend = FakeBackend(
        schemas={DOCK_SCHEMA, TERMINAL_SCHEMA},
        effective={(SHELL, "enabled-extensions"): [USER_THEME_UUID, BLUR_UUID],
                   (SHELL, "disable-user-extensions"): False,
                   (IFACE, "font-name"): "Ubuntu Sans 11",
                   (IFACE, "clock-format"): "24h",
                   (TERMINAL_SCHEMA, "default"): "abc-123"})
    caps = detect(backend, paths, {"XDG_CURRENT_DESKTOP": "ubuntu:GNOME", "XDG_SESSION_TYPE": "x11"},
                  system_data_dirs=[system])
    assert caps.gnome and caps.session == "x11" and caps.widgets
    assert caps.dock and caps.user_theme and caps.blur
    assert caps.gtk_themes == {"Yaru-blue-dark", "Mine"}
    assert caps.icon_themes == {"Papirus-Dark", "Bibata-Modern-Ice"}
    assert caps.shell_themes == {"Yaru-dark": str(system / "gnome-shell/theme/Yaru-dark/gnome-shell.css")}
    assert caps.terminal_profile == "abc-123"
    assert caps.font == "Ubuntu Sans" and caps.clock_24h and not caps.accent_color
    assert all(available for _, available, _ in caps.report())


def test_detects_a_bare_desktop_without_crashing(paths, tmp_path):
    caps = detect(FakeBackend(), paths, {"XDG_CURRENT_DESKTOP": "KDE", "XDG_SESSION_TYPE": "wayland"},
                  system_data_dirs=[tmp_path / "missing"])
    assert not caps.gnome and not caps.widgets
    assert not (caps.dock or caps.user_theme or caps.blur) and caps.terminal_profile is None
    assert caps.gtk_themes == frozenset() and caps.font == "Sans"
    notes = {feature: note for feature, available, note in caps.report() if not available}
    assert "wayland" in notes["Desktop widgets"] and "User Themes" in notes["Top bar styling"]


def test_globally_disabled_extensions_do_not_count(paths, tmp_path):
    backend = FakeBackend(effective={(SHELL, "enabled-extensions"): [USER_THEME_UUID, BLUR_UUID],
                                     (SHELL, "disable-user-extensions"): True})
    caps = detect(backend, paths, {}, system_data_dirs=[tmp_path])
    assert not caps.user_theme and not caps.blur and caps.session == "unknown"


def test_twelve_hour_clock_and_accent_setting_are_noticed(paths, tmp_path):
    backend = FakeBackend(effective={(IFACE, "clock-format"): "12h", (IFACE, "accent-color"): "blue",
                                     (IFACE, "font-name"): "Cantarell Bold 10.5"})
    caps = detect(backend, paths, {}, system_data_dirs=[tmp_path])
    assert not caps.clock_24h and caps.accent_color and caps.font == "Cantarell Bold"
