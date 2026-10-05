import random

import pytest
from PIL import Image

from ricer.backends import FakeBackend
from ricer.capabilities import Capabilities
from ricer.palette import extract_colors
from ricer.paths import Paths
from ricer.wallpapers import Wallpaper, analyse


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


def as_wallpaper(name, image):
    return Wallpaper(path=f"/walls/{name}.png", features=analyse(image),
                     colors=tuple(extract_colors(image)))


@pytest.fixture
def wallpaper_set():
    """Four synthetic wallpapers with clearly different moods."""
    return [
        as_wallpaper("warm", two_tone((230, 140, 40), (200, 80, 60))),
        as_wallpaper("cold", two_tone((30, 80, 200), (40, 160, 210))),
        as_wallpaper("grey", solid((90, 90, 90))),
        as_wallpaper("noisy", noise()),
    ]


@pytest.fixture
def paths(tmp_path):
    return Paths.from_env({"HOME": str(tmp_path)})


@pytest.fixture
def backend():
    return FakeBackend()


@pytest.fixture
def full_caps():
    """A desktop where every feature is available (Ubuntu-like, X11)."""
    return Capabilities(
        gnome=True, session="x11",
        gtk_themes=frozenset({"Yaru", "Yaru-dark", "Yaru-blue-dark", "Yaru-purple-dark",
                              "Yaru-magenta-dark", "Yaru-red-dark"}),
        icon_themes=frozenset({"Yaru", "Yaru-dark", "Papirus-Dark", "Bibata-Modern-Ice"}),
        shell_themes={"Yaru-dark": "/usr/share/gnome-shell/theme/Yaru-dark/gnome-shell.css",
                      "Yaru-blue-dark": "/usr/share/gnome-shell/theme/Yaru-blue-dark/gnome-shell.css"},
        dock=True, user_theme=True, blur=True, accent_color=False,
        terminal_profile="b1dcc9dd-5262-4d8d-a863-c897e6d979b9", font="Ubuntu Sans",
        clock_24h=True,
    )


@pytest.fixture
def bare_caps():
    """Plain GNOME on Wayland with no extensions and no extra themes."""
    return Capabilities(
        gnome=True, session="wayland", gtk_themes=frozenset({"Adwaita"}),
        icon_themes=frozenset({"Adwaita"}), shell_themes={}, dock=False, user_theme=False,
        blur=False, accent_color=True, terminal_profile=None, font="Cantarell", clock_24h=False,
    )
