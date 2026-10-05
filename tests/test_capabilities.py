from ricer.backends import FakeBackend
from ricer.capabilities import (BLUR_UUID, DESKTOP_ICONS_SCHEMA, DOCK_SCHEMA, MEDIA_CONTROLS_UUID,
                                TERMINAL_SCHEMA, USER_THEME_UUID, VITALS_UUID, detect, font_voices)
from ricer.look import VOICES

SHELL = "org.gnome.shell"
IFACE = "org.gnome.desktop.interface"
NO_FONTS = frozenset()


def test_detects_an_ubuntu_like_desktop(paths, tmp_path):
    system = tmp_path / "usr-share"
    (system / "themes/Yaru-blue-dark").mkdir(parents=True)
    (system / "icons/Papirus-Dark").mkdir(parents=True)
    (system / "gnome-shell/theme/Yaru-dark").mkdir(parents=True)
    (system / "gnome-shell/theme/Yaru-dark/gnome-shell.css").write_text("")
    (system / "gnome-shell/extensions/ubuntu-dock@ubuntu.com").mkdir(parents=True)
    (paths.data / "icons/Bibata-Modern-Ice").mkdir(parents=True)
    (paths.home / ".themes/Mine").mkdir(parents=True)
    for uuid in (USER_THEME_UUID, BLUR_UUID, VITALS_UUID):
        (paths.data / "gnome-shell/extensions" / uuid).mkdir(parents=True)
    backend = FakeBackend(
        schemas={DOCK_SCHEMA, TERMINAL_SCHEMA, DESKTOP_ICONS_SCHEMA},
        effective={(SHELL, "enabled-extensions"): [USER_THEME_UUID, BLUR_UUID],
                   (SHELL, "disable-user-extensions"): False,
                   (IFACE, "font-name"): "Ubuntu Sans 11",
                   (IFACE, "monospace-font-name"): "Ubuntu Sans Mono 13",
                   (IFACE, "clock-format"): "24h",
                   (TERMINAL_SCHEMA, "default"): "abc-123"})
    caps = detect(backend, paths, {"XDG_CURRENT_DESKTOP": "ubuntu:GNOME", "XDG_SESSION_TYPE": "x11"},
                  system_data_dirs=[system], fonts=frozenset({"Noto Serif", "URW Gothic"}),
                  screen=(2560, 1440))
    assert caps.gnome and caps.session == "x11" and caps.widgets
    assert caps.dock and caps.user_theme and caps.blur and caps.desktop_icons
    assert caps.vitals and not caps.media_controls           # installed is enough; ricer switches it
    assert caps.gtk_themes == {"Yaru-blue-dark", "Mine"}
    assert caps.icon_themes == {"Papirus-Dark", "Bibata-Modern-Ice"}
    assert caps.shell_themes == {"Yaru-dark": str(system / "gnome-shell/theme/Yaru-dark/gnome-shell.css")}
    assert caps.terminal_profile == "abc-123" and caps.screen == (2560, 1440)
    assert caps.font == "Ubuntu Sans" and caps.clock_24h and not caps.accent_color
    assert caps.fonts == {"ui": "Ubuntu Sans", "mono": "Ubuntu Sans Mono", "serif": "Noto Serif",
                          "condensed": "Ubuntu Sans Condensed", "geometric": "URW Gothic"}
    assert caps.font_for("serif") == "Noto Serif"
    assert "ubuntu-dock@ubuntu.com" in caps.installed and caps.extensions_allowed
    missing = [feature for feature, available, _ in caps.report() if not available]
    assert missing == ["Now playing in the top bar"]


def test_detects_a_bare_desktop_without_crashing(paths, tmp_path):
    caps = detect(FakeBackend(), paths, {"XDG_CURRENT_DESKTOP": "KDE", "XDG_SESSION_TYPE": "wayland"},
                  system_data_dirs=[tmp_path / "missing"], fonts=NO_FONTS, screen=(1920, 1080))
    assert not caps.gnome and not caps.widgets
    assert not (caps.dock or caps.user_theme or caps.blur or caps.vitals or caps.media_controls)
    assert not caps.desktop_icons and caps.terminal_profile is None
    assert caps.gtk_themes == frozenset() and caps.font == "Sans"
    notes = {feature: note for feature, available, note in caps.report() if not available}
    assert "wayland" in notes["Desktop widgets"] and "ricer setup" in notes["Top bar styling"]
    assert "Vitals" in notes["Stats in the top bar"]


def test_the_global_extensions_switch_blocks_everything(paths, tmp_path):
    for uuid in (VITALS_UUID, MEDIA_CONTROLS_UUID):
        (paths.data / "gnome-shell/extensions" / uuid).mkdir(parents=True)
    backend = FakeBackend(effective={(SHELL, "enabled-extensions"): [USER_THEME_UUID, BLUR_UUID],
                                     (SHELL, "disable-user-extensions"): True})
    caps = detect(backend, paths, {}, system_data_dirs=[tmp_path], fonts=NO_FONTS, screen=(1, 1))
    assert not caps.extensions_allowed and caps.session == "unknown"
    assert not (caps.user_theme or caps.blur or caps.vitals or caps.media_controls)
    assert VITALS_UUID in caps.installed                     # still known to be there


def test_twelve_hour_clock_and_accent_setting_are_noticed(paths, tmp_path):
    backend = FakeBackend(effective={(IFACE, "clock-format"): "12h", (IFACE, "accent-color"): "blue",
                                     (IFACE, "font-name"): "Cantarell Bold 10.5"})
    caps = detect(backend, paths, {}, system_data_dirs=[tmp_path], fonts=NO_FONTS, screen=(1, 1))
    assert not caps.clock_24h and caps.accent_color and caps.font == "Cantarell Bold"


def test_every_voice_resolves_to_some_font_even_with_nothing_installed():
    voices = font_voices("Cantarell", "", NO_FONTS)
    assert set(voices) == set(VOICES)
    assert voices == {"ui": "Cantarell", "mono": "Monospace", "condensed": "Cantarell Condensed",
                      "serif": "Serif", "geometric": "Cantarell"}
    best = font_voices("Inter", "JetBrains Mono", frozenset({"Playfair Display", "Noto Serif", "Poppins"}))
    assert best["serif"] == "Playfair Display" and best["geometric"] == "Poppins"
    assert best["mono"] == "JetBrains Mono"


def test_asking_the_real_system_does_not_crash(paths, tmp_path):
    caps = detect(FakeBackend(), paths, {}, system_data_dirs=[tmp_path])     # fonts and screen for real
    assert set(caps.fonts) == set(VOICES) and caps.screen[0] > 0 and caps.screen[1] > 0
