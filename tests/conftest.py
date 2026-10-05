import random

import pytest
from PIL import Image

from ricer.backends import FakeBackend
from ricer.capabilities import (BLUR_UUID, MEDIA_CONTROLS_UUID, USER_THEME_UUID, VITALS_UUID,
                                Capabilities)
from ricer.palette import extract_colors
from ricer.paths import Paths
from ricer.wallpapers import Wallpaper, analyse, analyse_grid


def solid(color, size=(192, 108)):
    return Image.new("RGB", size, color)


def two_tone(left, right, size=(192, 108)):
    image = Image.new("RGB", size, left)
    image.paste(right, (size[0] // 2, 0, size[0], size[1]))
    return image


def noise(seed=1, size=(192, 108)):
    rng = random.Random(seed)
    image = Image.new("RGB", size)
    image.putdata([tuple(rng.randrange(256) for _ in range(3)) for _ in range(size[0] * size[1])])
    return image


def busy_left(size=(384, 216)):
    """Dark and flat on the right, bright noise on the left: widgets belong on the right."""
    image = Image.new("RGB", size, (16, 18, 30))
    image.paste(noise(3, (size[0] // 2, size[1])), (0, 0))
    return image


def as_wallpaper(name, image):
    return Wallpaper(path=f"/walls/{name}.png", features=analyse(image),
                     colors=tuple(extract_colors(image)), size=image.size, grid=analyse_grid(image))


@pytest.fixture(scope="session")
def wallpaper_set():
    """Synthetic wallpapers with clearly different moods. Immutable, so shared by all tests."""
    return [
        as_wallpaper("warm", two_tone((230, 140, 40), (200, 80, 60))),
        as_wallpaper("cold", two_tone((30, 80, 200), (40, 160, 210))),
        as_wallpaper("grey", solid((90, 90, 90))),
        as_wallpaper("dusk", two_tone((40, 30, 80), (20, 24, 40))),
        as_wallpaper("noisy", noise()),
    ]


@pytest.fixture(scope="session")
def lopsided():
    return as_wallpaper("lopsided", busy_left())


@pytest.fixture
def paths(tmp_path):
    return Paths.from_env({"HOME": str(tmp_path)})


@pytest.fixture
def backend():
    return FakeBackend()


FONTS = {"ui": "Ubuntu Sans", "condensed": "Ubuntu Sans Condensed", "mono": "Ubuntu Sans Mono",
         "serif": "Noto Serif Display", "geometric": "URW Gothic"}
PROFILE = "b1dcc9dd-5262-4d8d-a863-c897e6d979b9"


# a stock app theme in miniature: greys, an accent with a shade of it, a warning, a picture
STOCK_CSS = """\
/* stock theme: #2c2c2c is the window colour */
@define-color theme_bg_color #2c2c2c;
@define-color theme_selected_bg_color #7764D8;
.background { color: #F7F7F7; background-color: #2c2c2c; }
window#abc headerbar { background: #131313 linear-gradient(to top, #222222, #222222);
  box-shadow: inset 0 1px rgba(247, 247, 247, 0.07); }
button:checked { background-color: #7764D8; border-color: #533bce;
  background-image: url("assets/check.png"); }
.warning { color: #f99b11; }
decoration { box-shadow: 0 3px 9px 1px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(0, 0, 0, 0.75); }
"""
STOCK_THEMES = ("Yaru-dark", "Yaru-blue-dark", "Yaru-purple-dark", "Yaru-magenta-dark", "Yaru-red-dark")


@pytest.fixture
def stock_themes(tmp_path):
    """Stock app themes as a distribution installs them: name -> its gtk-3.0 folder."""
    folders = {}
    for name in STOCK_THEMES:
        folder = tmp_path / "usr-share/themes" / name / "gtk-3.0"
        folder.mkdir(parents=True)
        (folder / "gtk.css").write_text(STOCK_CSS)
        (folder / "gtk.gresource").write_bytes(b"the theme's pictures")
        folders[name] = str(folder)
    return folders


@pytest.fixture
def full_caps(stock_themes):
    """A desktop where every feature is available (Ubuntu-like, X11)."""
    return Capabilities(
        gnome=True, session="x11",
        gtk_themes=frozenset({"Yaru", *STOCK_THEMES}),
        icon_themes=frozenset({"Yaru", "Yaru-dark", "Yaru-blue-dark", "Adwaita", "Papirus-Dark",
                               "Bibata-Modern-Ice"}),
        shell_themes={"Yaru-dark": "/usr/share/gnome-shell/theme/Yaru-dark/gnome-shell.css",
                      "Yaru-blue-dark": "/usr/share/gnome-shell/theme/Yaru-blue-dark/gnome-shell.css"},
        dock=True, user_theme=True, blur=True, accent_color=False, terminal_profile=PROFILE,
        font="Ubuntu Sans", clock_24h=True, vitals=True, media_controls=True, desktop_icons=True,
        fonts=dict(FONTS), screen=(1920, 1080),
        installed=frozenset({USER_THEME_UUID, BLUR_UUID, VITALS_UUID, MEDIA_CONTROLS_UUID}),
        gtk3_themes=stock_themes, terminal_glass=True,
    )


@pytest.fixture
def bare_caps():
    """Plain GNOME on Wayland with no extensions and no extra themes."""
    return Capabilities(
        gnome=True, session="wayland", gtk_themes=frozenset({"Adwaita"}),
        icon_themes=frozenset({"Adwaita"}), shell_themes={}, dock=False, user_theme=False,
        blur=False, accent_color=True, terminal_profile=None, font="Cantarell", clock_24h=False,
    )
