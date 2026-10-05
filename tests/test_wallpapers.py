import io
import json
import random

import pytest

from ricer import wallpapers
from ricer.look import Dials
from ricer.wallpapers import Library, NoWallpapersError, analyse, choose, rank, score

from conftest import noise, solid, two_tone


def test_analyse_reads_warmth():
    assert analyse(solid((230, 140, 40))).warmth > 0.8
    assert analyse(solid((30, 100, 220))).warmth < -0.8
    assert analyse(solid((120, 120, 120))).warmth == 0


def test_analyse_reads_brightness_colour_and_detail():
    assert analyse(solid((250, 250, 250))).brightness > 0.9
    assert analyse(solid((10, 10, 10))).brightness < 0.1
    assert analyse(solid((255, 0, 0))).colourfulness > analyse(solid((140, 120, 120))).colourfulness
    assert analyse(noise()).busyness > 0.5
    assert analyse(solid((80, 80, 200))).busyness == 0


def test_warmth_dial_ranks_matching_wallpapers_first(wallpaper_set):
    assert rank(wallpaper_set, Dials(8, 5, 10))[0].path.endswith("warm.png")
    assert rank(wallpaper_set, Dials(8, 5, 1))[0].path.endswith("cold.png")


def test_low_cool_prefers_the_muted_wallpaper(wallpaper_set):
    assert rank(wallpaper_set, Dials(1, 8, 5))[0].path.endswith("grey.png")


def test_score_is_best_for_a_perfect_match():
    perfect = wallpapers.Features(warmth=1, brightness=0.5, colourfulness=1, busyness=0)
    assert score(perfect, Dials(10, 10, 10)) == pytest.approx(0)
    assert score(perfect, Dials(1, 1, 1)) < -1


def test_choose_is_deterministic_without_rng_and_varies_with_one(wallpaper_set):
    dials = Dials(5, 5, 5)
    assert choose(wallpaper_set, dials) == choose(list(reversed(wallpaper_set)), dials)
    picks = {choose(wallpaper_set, dials, random.Random(seed)).path for seed in range(1, 40)}
    assert 1 < len(picks) <= wallpapers.SHUFFLE_POOL


def test_choose_with_empty_library_explains_what_to_do():
    with pytest.raises(NoWallpapersError, match="ricer wallpapers fetch"):
        choose([], Dials())


def test_library_scans_images_and_ignores_other_files(tmp_path):
    folder = tmp_path / "walls"
    folder.mkdir()
    solid((230, 140, 40)).save(folder / "warm.png")
    solid((30, 100, 220)).save(folder / "cold.jpg")
    (folder / "notes.txt").write_text("hello")
    (folder / "broken.png").write_text("not an image")
    library = Library(folder, tmp_path / "cache.json")
    found = library.scan()
    assert [w.path for w in found] == [str(folder / "cold.jpg"), str(folder / "warm.png")]
    assert found[1].features.warmth > 0.8 and found[1].colors


def test_library_cache_is_reused_until_the_file_changes(tmp_path, monkeypatch):
    folder = tmp_path / "walls"
    folder.mkdir()
    solid((230, 140, 40)).save(folder / "a.png")
    library = Library(folder, tmp_path / "cache.json")
    first = library.scan()

    calls = []
    real = wallpapers.analyse
    monkeypatch.setattr(wallpapers, "analyse", lambda image: calls.append(1) or real(image))
    assert library.scan() == first and not calls

    solid((30, 100, 220), size=(300, 200)).save(folder / "a.png")
    assert library.scan()[0].features.warmth < 0 and calls


def test_library_of_a_missing_folder_is_empty(tmp_path):
    assert Library(tmp_path / "nope", tmp_path / "cache.json").scan() == []


def test_library_add_copies_images_and_refuses_other_files(tmp_path):
    source = tmp_path / "pic.png"
    solid((1, 2, 3)).save(source)
    library = Library(tmp_path / "walls", tmp_path / "cache.json")
    assert library.add(source) == tmp_path / "walls" / "pic.png"
    assert (tmp_path / "walls" / "pic.png").is_file()
    with pytest.raises(ValueError):
        library.add(tmp_path / "doc.pdf")
    with pytest.raises(FileNotFoundError):
        library.add(tmp_path / "missing.png")


class FakeWallhaven:
    """Stands in for urlopen: serves search pages and image bytes, records every URL."""

    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.urls.append(url)
        assert request.get_header("User-agent", "").startswith("ricer/")
        if url.startswith(wallpapers.WALLHAVEN_SEARCH):
            page = int(url.split("page=")[1].split("&")[0])
            body = json.dumps({"data": self.pages.get(page, [])}).encode()
        else:
            body = b"image-bytes:" + url.encode()
        return io.BytesIO(body)


def item(ident, ext="jpg"):
    return {"id": ident, "path": f"https://w.wallhaven.cc/full/{ident[:2]}/wallhaven-{ident}.{ext}"}


def test_fetch_saves_new_wallpapers_and_asks_only_for_sfw(tmp_path):
    web = FakeWallhaven({1: [item("aaa111"), item("bbb222", "png")]})
    saved = wallpapers.fetch(tmp_path, 5, opener=web)
    assert [p.name for p in saved] == ["wallhaven-aaa111.jpg", "wallhaven-bbb222.png"]
    assert saved[0].read_bytes().startswith(b"image-bytes:")
    assert "purity=100" in web.urls[0] and "q=anime+scenery" in web.urls[0]


def test_fetch_stops_at_count_and_skips_files_it_already_has(tmp_path):
    (tmp_path / "wallhaven-aaa111.jpg").write_bytes(b"old")
    web = FakeWallhaven({1: [item("aaa111"), item("bbb222")], 2: [item("ccc333"), item("ddd444")]})
    saved = wallpapers.fetch(tmp_path, 2, opener=web)
    assert [p.name for p in saved] == ["wallhaven-bbb222.jpg", "wallhaven-ccc333.jpg"]
    assert (tmp_path / "wallhaven-aaa111.jpg").read_bytes() == b"old"
    assert not any("ddd444" in url for url in web.urls)


def test_fetch_gives_up_when_results_run_out(tmp_path):
    web = FakeWallhaven({1: [item("aaa111")]})
    assert len(wallpapers.fetch(tmp_path, 10, opener=web)) == 1
