import fcntl
import io
import json
import os
import random

from ricer import topup, wallpapers
from ricer.topup import Settings

from conftest import solid
from test_wallpapers import item


class PictureWeb:
    """Stands in for urlopen: every search page has fresh results, every image is a real picture."""

    def __init__(self, fail=None):
        self.fail, self.served = fail, 0

    def __call__(self, request, timeout=None):
        if self.fail:
            raise self.fail
        if request.full_url.startswith(wallpapers.WALLHAVEN_SEARCH):
            self.served += 1
            results = [item(f"s{self.served}n{n}", "png") for n in range(4)]
            return io.BytesIO(json.dumps({"data": results, "meta": {"last_page": 9}}).encode())
        picture = io.BytesIO()
        solid((30, 100, 220)).save(picture, "PNG")
        return io.BytesIO(picture.getvalue())


def old_fetched(paths, name, age):
    paths.wallpapers.mkdir(parents=True, exist_ok=True)
    path = paths.wallpapers / f"wallhaven-{name}.png"
    solid((90, 90, 90)).save(path)
    os.utime(path, (1_000_000 - age, 1_000_000 - age))
    return path


def names(paths):
    return sorted(path.name for path in paths.wallpapers.iterdir())


def test_a_top_up_fetches_records_and_analyses(paths):
    out = io.StringIO()
    assert topup.run(paths, opener=PictureWeb(), rng=random.Random(1), out=out) == 0
    fetched = names(paths)
    assert len(fetched) == topup.TOPUP_COUNT and all(name.startswith("wallhaven-") for name in fetched)
    assert sorted(json.loads(paths.fetched_file.read_text())) == sorted(name[10:-4] for name in fetched)
    cached = json.loads(paths.wallpaper_cache.read_text())      # ready for the next look
    assert sorted(cached) == sorted(str(paths.wallpapers / name) for name in fetched)
    assert "fetched wallhaven-" in out.getvalue() and "3 in the library" in out.getvalue()


def test_a_full_library_rotates_but_keeps_what_looks_still_need(paths):
    current, undo, default, recent = (old_fetched(paths, name, age) for name, age in
                                      (("cur", 900), ("undo", 800), ("def", 700), ("past", 600)))
    spare = [old_fetched(paths, f"spare{n}", 500 - n) for n in range(3)]
    solid((200, 80, 60)).save(paths.wallpapers / "mine.png")
    os.utime(paths.wallpapers / "mine.png", (1, 1))
    paths.config.mkdir(parents=True)
    paths.state_file.write_text(json.dumps({
        "look": {"wallpaper": str(current)}, "snapshot": {"look": {"wallpaper": str(undo)}},
        "history": [{"wallpaper": str(recent)}]}))
    paths.default_file.write_text(json.dumps({"wallpaper": str(default)}))
    topup.save_settings(paths, Settings(cap=8))

    out = io.StringIO()
    topup.run(paths, opener=PictureWeb(), rng=random.Random(1), out=out)
    left = names(paths)
    assert len(left) == 8 and "mine.png" in left
    assert all(path.name in left for path in (current, undo, default, recent))
    assert not any(path.name in left for path in spare)          # the oldest unprotected went
    assert "retired wallhaven-spare0.png" in out.getvalue()

    # none of the retired ones comes back, even when the search offers it again
    class Repeats(PictureWeb):
        def __call__(self, request, timeout=None):
            if request.full_url.startswith(wallpapers.WALLHAVEN_SEARCH):
                results = [item(f"spare{n}", "png") for n in range(3)]
                return io.BytesIO(json.dumps({"data": results, "meta": {"last_page": 9}}).encode())
            return super().__call__(request, timeout)

    topup.run(paths, opener=Repeats(), rng=random.Random(2), out=io.StringIO())
    assert names(paths) == left


def test_offline_is_logged_and_changes_nothing(paths):
    kept = old_fetched(paths, "kept", 100)
    out = io.StringIO()
    assert topup.run(paths, opener=PictureWeb(fail=OSError("no network")), out=out) == 0
    assert "nothing fetched: no network" in out.getvalue() and names(paths) == [kept.name]


def test_only_one_top_up_runs_at_a_time(paths):
    paths.cache.mkdir(parents=True)
    web = PictureWeb()
    with open(paths.topup_lock, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        out = io.StringIO()
        assert topup.run(paths, opener=web, out=out) == 0
    assert web.served == 0 and "another top-up" in out.getvalue()


def test_start_launches_the_module_unless_switched_off(paths, monkeypatch):
    launched = []
    monkeypatch.setattr(topup.subprocess, "Popen", lambda command, **options: launched.append((command, options)))
    assert topup.TopUp(paths).start() is True
    command, options = launched[0]
    assert command[1:] == ["-m", "ricer.topup"] and options["start_new_session"] is True
    assert paths.topup_log.exists()
    topup.save_settings(paths, Settings(auto=False))
    assert topup.TopUp(paths).start() is False and len(launched) == 1


def test_unreadable_settings_fall_back_to_the_defaults(paths):
    paths.config.mkdir(parents=True)
    paths.library_settings.write_text("[not what was expected")
    assert topup.load_settings(paths) == Settings(auto=True, cap=topup.DEFAULT_CAP)
