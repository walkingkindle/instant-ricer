"""The wallpaper library: analysing images, scoring them against the dials, fetching more."""
from __future__ import annotations

import json
import math
import random
import shutil
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from ricer import __version__
from ricer.look import Dials, dial_fraction
from ricer.palette import WARM_HUE, extract_colors

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
# Raw measurements bunch up near zero for real artwork; these stretch them over 0..1 so that
# a vivid, detailed illustration scores around 0.7 and flat grey scores 0.
COLOUR_GAIN = 3.0
DETAIL_GAIN = 18.0
SHUFFLE_POOL = 3                     # a shuffled pick comes from this many best matches
WALLHAVEN_SEARCH = "https://wallhaven.cc/api/v1/search"
DEFAULT_QUERY = "anime scenery"
MAX_PAGES = 5
USER_AGENT = f"ricer/{__version__}"


class NoWallpapersError(RuntimeError):
    """The library has no usable image."""


@dataclass(frozen=True)
class Features:
    warmth: float                    # -1 cold blues .. +1 warm ambers
    brightness: float                # 0 black .. 1 white
    colourfulness: float             # 0 grey .. 1 vivid
    busyness: float                  # 0 flat .. 1 lots of fine detail


@dataclass(frozen=True)
class Wallpaper:
    path: str
    features: Features
    colors: tuple[tuple[str, float], ...]


def analyse(image) -> Features:
    """Measure the mood of a PIL image on a small thumbnail of it."""
    small = image.convert("RGB").resize((96, 54))
    hsv = list(small.convert("HSV").getdata())
    grey = list(small.convert("L").getdata())

    weight_sum = warm_sum = 0.0
    for h, s, v in hsv:
        weight = (s / 255) * (v / 255)                       # grey and black pixels carry no mood
        warm_sum += math.cos(math.radians(h * 360 / 255 - WARM_HUE)) * weight
        weight_sum += weight
    count = len(hsv)
    warmth = warm_sum / weight_sum if weight_sum > count * 0.01 else 0.0

    width = 96
    edges = sum(abs(grey[i] - grey[i - 1]) for i in range(1, len(grey)) if i % width)
    return Features(
        warmth=round(warmth, 4),
        brightness=round(sum(grey) / count / 255, 4),
        colourfulness=round(min(1.0, weight_sum / count * COLOUR_GAIN), 4),
        busyness=round(min(1.0, edges / count / 255 * DETAIL_GAIN), 4),
    )


def score(features: Features, dials: Dials) -> float:
    """Higher is a better match. Warmth matters most, then vividness, then calmness for ease."""
    want_warmth = 2 * dial_fraction(dials.warmth) - 1
    want_colour = dial_fraction(dials.cool)
    want_busy = 1 - dial_fraction(dials.ease)
    return -(
        1.00 * ((features.warmth - want_warmth) / 2) ** 2
        + 0.50 * (features.colourfulness - want_colour) ** 2
        + 0.25 * (features.busyness - want_busy) ** 2
    )


def rank(wallpapers: list[Wallpaper], dials: Dials) -> list[Wallpaper]:
    return sorted(wallpapers, key=lambda w: (-score(w.features, dials), w.path))


def choose(wallpapers: list[Wallpaper], dials: Dials,
           rng: random.Random | None = None) -> Wallpaper:
    """Best match for the dials; with `rng`, one of the few best."""
    if not wallpapers:
        raise NoWallpapersError(
            "No wallpapers found. Add some with 'ricer wallpapers add <file>' "
            "or download a starter set with 'ricer wallpapers fetch'.")
    ranked = rank(wallpapers, dials)
    if rng is None:
        return ranked[0]
    return ranked[rng.randrange(min(SHUFFLE_POOL, len(ranked)))]


class Library:
    """A folder of images plus a cache of their analysis."""

    def __init__(self, directory: Path, cache_file: Path):
        self.directory = Path(directory)
        self.cache_file = Path(cache_file)

    def _load_cache(self) -> dict:
        try:
            return json.loads(self.cache_file.read_text())
        except (OSError, ValueError):
            return {}

    def scan(self) -> list[Wallpaper]:
        """Analyse every image in the folder, reusing cached results for unchanged files."""
        from PIL import Image, UnidentifiedImageError

        if not self.directory.is_dir():
            return []
        cache = self._load_cache()
        fresh, found = {}, []
        for path in sorted(self.directory.iterdir()):
            if path.suffix.lower() not in IMAGE_EXTENSIONS or not path.is_file():
                continue
            stat = path.stat()
            entry = cache.get(str(path))
            if not entry or entry["mtime"] != stat.st_mtime or entry["size"] != stat.st_size:
                try:
                    with Image.open(path) as image:
                        features, colors = analyse(image), extract_colors(image)
                except (OSError, UnidentifiedImageError):
                    continue                                 # not really an image; leave it out
                entry = {"mtime": stat.st_mtime, "size": stat.st_size,
                         "features": asdict(features), "colors": colors}
            fresh[str(path)] = entry
            found.append(Wallpaper(
                path=str(path),
                features=Features(**entry["features"]),
                colors=tuple((c, w) for c, w in entry["colors"]),
            ))
        if fresh != cache:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(json.dumps(fresh))
        return found

    def add(self, source: Path) -> Path:
        """Copy an image into the library and return its new path."""
        source = Path(source)
        if source.suffix.lower() not in IMAGE_EXTENSIONS:
            raise ValueError(f"{source.name}: not a supported image type {IMAGE_EXTENSIONS}")
        if not source.is_file():
            raise FileNotFoundError(source)
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / source.name
        if target.resolve() != source.resolve():
            shutil.copy2(source, target)
        return target


def fetch(directory: Path, count: int, query: str = DEFAULT_QUERY,
          opener=urllib.request.urlopen) -> list[Path]:
    """Download up to `count` new SFW wallpapers from Wallhaven into `directory`.

    Files already present are skipped and do not count. `opener` is replaceable for tests.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []

    def get(url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with opener(request, timeout=30) as response:
            return response.read()

    for page in range(1, MAX_PAGES + 1):
        params = urllib.parse.urlencode({
            "q": query, "categories": "010", "purity": "100", "atleast": "1920x1080",
            "ratios": "16x9", "sorting": "favorites", "order": "desc", "page": page,
        })
        results = json.loads(get(f"{WALLHAVEN_SEARCH}?{params}")).get("data", [])
        if not results:
            break
        for item in results:
            if len(saved) >= count:
                return saved
            suffix = Path(urllib.parse.urlparse(item["path"]).path).suffix.lower()
            target = directory / f"wallhaven-{item['id']}{suffix}"
            if suffix not in IMAGE_EXTENSIONS or target.exists():
                continue
            target.write_bytes(get(item["path"]))
            saved.append(target)
    return saved
