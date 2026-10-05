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
from ricer.chance import draw
from ricer.look import DIAL_MIN, Dials, dial_fraction
from ricer.palette import WARM_HUE, extract_colors

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
# Raw measurements bunch up near zero for real artwork; these stretch them over 0..1 so that
# a vivid, detailed illustration scores around 0.7 and flat grey scores 0.
COLOUR_GAIN = 3.0
DETAIL_GAIN = 18.0
GRID_COLS, GRID_ROWS = 32, 18        # resolution of the per-wallpaper placement maps
CELL = 8                             # thumbnail pixels per grid cell when measuring
BUSY_GAIN = 9.0                      # stretches local detail so busy artwork lands near 1
SUBJECT_FLOOR = 10.0                 # raw stand-out level below which nothing counts as a subject
CACHE_VERSION = 4
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
class Grid:
    """Coarse maps of a wallpaper, row by row, every value 0..1. Used to place widgets."""
    cols: int
    rows: int
    busy: tuple[float, ...]          # fine detail: text is hard to read over it
    bright: tuple[float, ...]        # luminance
    subject: tuple[float, ...]       # how much a cell stands out: likely what the picture is of

    def region(self, x0: float, y0: float, x1: float, y1: float) -> tuple[float, float, float]:
        """Mean (busy, bright, subject) over a rectangle given in 0..1 image coordinates."""
        x0, x1 = sorted((min(1.0, max(0.0, x0)), min(1.0, max(0.0, x1))))
        y0, y1 = sorted((min(1.0, max(0.0, y0)), min(1.0, max(0.0, y1))))
        totals, area = [0.0, 0.0, 0.0], 0.0
        for row in range(int(y0 * self.rows), min(self.rows, int(math.ceil(y1 * self.rows)) or 1)):
            height = min(y1 * self.rows, row + 1) - max(y0 * self.rows, row)
            for col in range(int(x0 * self.cols), min(self.cols, int(math.ceil(x1 * self.cols)) or 1)):
                weight = max(0.0, height) * max(0.0, min(x1 * self.cols, col + 1) - max(x0 * self.cols, col))
                index = row * self.cols + col
                totals[0] += self.busy[index] * weight
                totals[1] += self.bright[index] * weight
                totals[2] += self.subject[index] * weight
                area += weight
        if area <= 0:                                        # a degenerate rectangle: nearest cell
            index = min(self.rows - 1, int(y0 * self.rows)) * self.cols + min(self.cols - 1, int(x0 * self.cols))
            return self.busy[index], self.bright[index], self.subject[index]
        return totals[0] / area, totals[1] / area, totals[2] / area


@dataclass(frozen=True)
class Wallpaper:
    path: str
    features: Features
    colors: tuple[tuple[str, float], ...]
    size: tuple[int, int] = (1920, 1080)
    grid: Grid | None = None


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


def _blur(values: list[float], cols: int, rows: int) -> list[float]:
    """3x3 box blur, so a map reads as regions rather than speckle."""
    out = []
    for row in range(rows):
        for col in range(cols):
            near = [values[r * cols + c]
                    for r in range(max(0, row - 1), min(rows, row + 2))
                    for c in range(max(0, col - 1), min(cols, col + 2))]
            out.append(sum(near) / len(near))
    return out


def analyse_grid(image, cols: int = GRID_COLS, rows: int = GRID_ROWS) -> Grid:
    """Map where a PIL image is busy, bright, and where its subject probably is."""
    width, height = cols * CELL, rows * CELL
    small = image.convert("RGB").resize((width, height))
    grey = list(small.convert("L").getdata())
    ycc = list(small.convert("YCbCr").getdata())
    mean = [sum(pixel[i] for pixel in ycc) / len(ycc) for i in range(3)]

    busy, bright, standout = [], [], []
    for row in range(rows):
        for col in range(cols):
            edges = light = 0
            sums = [0, 0, 0]
            for y in range(row * CELL, (row + 1) * CELL):
                base = y * width
                for x in range(col * CELL, (col + 1) * CELL):
                    value = grey[base + x]
                    light += value
                    if x + 1 < width:
                        edges += abs(value - grey[base + x + 1])
                    if y + 1 < height:
                        edges += abs(value - grey[base + width + x])
                    pixel = ycc[base + x]
                    sums[0] += pixel[0]
                    sums[1] += pixel[1]
                    sums[2] += pixel[2]
            n = CELL * CELL
            busy.append(min(1.0, edges / (2 * n) / 255 * BUSY_GAIN))
            bright.append(light / n / 255)
            # what stands out: a colour unlike the rest, or being brighter than the rest.
            # Being darker does not count: a dark empty sky is background, not subject.
            colour = math.hypot(sums[1] / n - mean[1], sums[2] / n - mean[2])
            standout.append(colour + 0.5 * max(0.0, sums[0] / n - mean[0]))

    busy = _blur(busy, cols, rows)
    # a subject also has detail and some light; flat or dark areas are background
    raw = _blur([s * (0.1 + 0.9 * b) * (0.4 + 0.6 * light)
                 for s, b, light in zip(standout, busy, bright)], cols, rows)
    # scale to the picture's own strongest area; a small subject must not be drowned out by
    # the 97th percentile, nor a single hot cell define the scale
    top = max(sorted(raw)[int(len(raw) * 0.97)], 0.5 * max(raw))
    strength = min(1.0, top / SUBJECT_FLOOR)
    subject = [min(1.0, value / top) * strength if top > 0 else 0.0 for value in raw]
    return Grid(cols, rows, tuple(round(v, 3) for v in busy), tuple(round(v, 3) for v in bright),
                tuple(round(v, 3) for v in subject))


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
    """A wallpaper for the dials: the best match, or with `rng` a draw that favours good matches.

    Chaos decides how strongly: at 1 it is almost always the best match, at 10 nearly any.
    """
    if not wallpapers:
        raise NoWallpapersError(
            "No wallpapers found. Add some with 'ricer wallpapers add <file>' "
            "or download a starter set with 'ricer wallpapers fetch'.")
    ranked = rank(wallpapers, dials)
    if rng is None:
        return ranked[0]
    sharpness = 1 / (0.012 * 1.5 ** (dials.chaos - DIAL_MIN))
    best = score(ranked[0].features, dials)
    by_path = {wallpaper.path: wallpaper for wallpaper in ranked}
    odds = {path: math.exp((score(w.features, dials) - best) * sharpness) for path, w in by_path.items()}
    return by_path[draw(rng, odds)]


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
            if (not entry or entry.get("v") != CACHE_VERSION
                    or entry["mtime"] != stat.st_mtime or entry["size"] != stat.st_size):
                try:
                    with Image.open(path) as image:
                        entry = {"v": CACHE_VERSION, "mtime": stat.st_mtime, "size": stat.st_size,
                                 "pixels": list(image.size), "features": asdict(analyse(image)),
                                 "colors": extract_colors(image), "grid": asdict(analyse_grid(image))}
                except (OSError, UnidentifiedImageError):
                    continue                                 # not really an image; leave it out
            fresh[str(path)] = entry
            grid = entry["grid"]
            found.append(Wallpaper(
                path=str(path),
                features=Features(**entry["features"]),
                colors=tuple((c, w) for c, w in entry["colors"]),
                size=tuple(entry["pixels"]),
                grid=Grid(grid["cols"], grid["rows"], tuple(grid["busy"]), tuple(grid["bright"]),
                          tuple(grid["subject"])),
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
