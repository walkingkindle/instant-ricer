"""Keeping the wallpaper library fresh: a few new images after each look, the oldest making room.

`python -m ricer.topup` is the background process `TopUp.start` launches. It only touches the
wallpaper folder and ricer's cache, never the desktop.
"""
from __future__ import annotations

import fcntl
import json
import random
import subprocess
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from ricer import wallpapers
from ricer.paths import Paths
from ricer.wallpapers import Library

TOPUP_MODULE = "ricer.topup"
TOPUP_COUNT = 3                      # new images after each look
DEFAULT_CAP = 200                    # images the library holds before the oldest fetched go


@dataclass(frozen=True)
class Settings:
    auto: bool = True                # fetch after each look
    cap: int = DEFAULT_CAP


def load_settings(paths: Paths) -> Settings:
    try:
        data = json.loads(paths.library_settings.read_text())
        return Settings(auto=bool(data.get("auto", True)), cap=max(1, int(data.get("cap", DEFAULT_CAP))))
    except (OSError, ValueError, AttributeError):
        return Settings()


def save_settings(paths: Paths, settings: Settings) -> None:
    paths.library_settings.parent.mkdir(parents=True, exist_ok=True)
    paths.library_settings.write_text(json.dumps(asdict(settings), indent=2) + "\n")


def _json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def protected(paths: Paths) -> set[str]:
    """Wallpapers that must stay: the current look's, the one revert returns to, the recent
    looks' and the default look's."""
    state = _json(paths.state_file)
    state = state if isinstance(state, dict) else {}
    looks = [state.get("look"), (state.get("snapshot") or {}).get("look"),
             _json(paths.default_file), *state.get("history", [])]
    return {look["wallpaper"] for look in looks if isinstance(look, dict) and look.get("wallpaper")}


def gather(paths: Paths, count: int, query: str | None = None, opener=urllib.request.urlopen,
           rng: random.Random | None = None) -> list[Path]:
    """Fetch new wallpapers, never one the library has held before."""
    held = {wallpapers.fetched_id(path) for path in wallpapers.images_in(paths.wallpapers)} - {None}
    known = _json(paths.fetched_file)
    seen = held | set(known if isinstance(known, list) else [])
    saved: list[Path] = []
    try:
        saved = wallpapers.fetch(paths.wallpapers, count, query, opener=opener, rng=rng, seen=seen)
    finally:                                                 # what is on disk counts even if a later download failed
        now = {wallpapers.fetched_id(path) for path in wallpapers.images_in(paths.wallpapers)} - {None}
        paths.fetched_file.parent.mkdir(parents=True, exist_ok=True)
        paths.fetched_file.write_text(json.dumps(sorted(seen | now)))
    return saved


def run(paths: Paths, opener=urllib.request.urlopen, rng: random.Random | None = None,
        out=None) -> int:
    """One top-up: fetch a few, retire down to the cap, analyse the newcomers."""
    out = out or sys.stdout

    def log(text: str) -> None:
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}", file=out, flush=True)

    paths.cache.mkdir(parents=True, exist_ok=True)
    with open(paths.topup_lock, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            log("another top-up is running; leaving it to that one")
            return 0
        try:
            saved = gather(paths, TOPUP_COUNT, opener=opener, rng=rng)
        except (OSError, ValueError, KeyError) as error:     # offline, or an answer that is not what was expected
            log(f"nothing fetched: {error}")
            return 0
        gone = wallpapers.retire(paths.wallpapers, load_settings(paths).cap, protected(paths))
        total = len(Library(paths.wallpapers, paths.wallpaper_cache).scan())
        log(f"fetched {', '.join(path.name for path in saved) or 'nothing new'}"
            + (f"; retired {', '.join(path.name for path in gone)}" if gone else "")
            + f"; {total} in the library")
    return 0


class TopUp:
    """Starts the background top-up. The CLI calls this after a look is applied."""

    def __init__(self, paths: Paths):
        self.paths = paths

    def start(self) -> bool:
        """Launch a top-up unless automatic fetching is off. Returns True if it was launched."""
        if not load_settings(self.paths).auto:
            return False
        self.paths.cache.mkdir(parents=True, exist_ok=True)
        with open(self.paths.topup_log, "ab") as log:
            subprocess.Popen([sys.executable, "-m", TOPUP_MODULE], stdin=subprocess.DEVNULL,
                             stdout=log, stderr=log, start_new_session=True)
        return True


if __name__ == "__main__":
    sys.exit(run(Paths.from_env()))
