import io
import json
import urllib.parse
import os
import random

import pytest
from PIL import Image

from ricer import wallpapers
from ricer.look import Dials
from ricer.wallpapers import Library, NoWallpapersError, analyse, choose, rank, score

from ricer.wallpapers import Grid, analyse_grid

from conftest import busy_left, noise, solid, two_tone


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


def cells(grid, values, x0, x1, y0=0.0, y1=1.0):
    """Mean of a map over a rectangle of 0..1 coordinates, whole cells only."""
    picked = [values[row * grid.cols + col]
              for row in range(int(y0 * grid.rows), int(y1 * grid.rows))
              for col in range(int(x0 * grid.cols), int(x1 * grid.cols))]
    return sum(picked) / len(picked)


def test_grid_maps_where_the_picture_is_busy_and_bright():
    grid = analyse_grid(busy_left())
    assert (grid.cols, grid.rows) == (wallpapers.GRID_COLS, wallpapers.GRID_ROWS)
    assert len(grid.busy) == len(grid.bright) == len(grid.subject) == grid.cols * grid.rows
    assert all(0 <= v <= 1 for v in grid.busy + grid.bright + grid.subject)
    assert cells(grid, grid.busy, 0.0, 0.45) > 0.8 and cells(grid, grid.busy, 0.55, 1.0) < 0.05
    assert cells(grid, grid.bright, 0.0, 0.45) > 0.4 and cells(grid, grid.bright, 0.55, 1.0) < 0.1


def test_grid_finds_a_subject_that_stands_out_and_none_in_a_flat_picture():
    scene = solid((20, 30, 60), size=(384, 216))
    patch = noise(2, (96, 72)).convert("L").point(lambda v: 150 + v // 3)
    scene.paste(Image.merge("RGB", (patch, patch.point(lambda v: v // 2), patch.point(lambda v: v // 5))),
                (240, 100))                               # a bright, detailed orange patch
    grid = analyse_grid(scene)
    inside = cells(grid, grid.subject, 0.66, 0.84, 0.50, 0.75)
    assert inside > 0.6 and cells(grid, grid.subject, 0.0, 0.5) < 0.05
    flat = analyse_grid(solid((60, 60, 90)))
    assert max(flat.subject) == 0 and max(flat.busy) == 0


def test_flat_areas_are_background_not_subject():
    scene = two_tone((6, 8, 14), (120, 110, 100), size=(384, 216))
    grid = analyse_grid(scene)
    assert cells(grid, grid.subject, 0.0, 0.45) < 0.2        # dark and empty
    assert cells(grid, grid.subject, 0.55, 1.0) < 0.35       # brighter, but just as flat


def test_a_dark_detailed_shape_against_a_bright_sky_is_a_subject():
    scene = solid((235, 170, 110), size=(384, 216))          # a flat sunset sky
    figure = noise(4, (60, 120)).convert("L").point(lambda v: v // 6)       # dark, with detail
    scene.paste(Image.merge("RGB", (figure, figure, figure)), (160, 80))
    grid = analyse_grid(scene)
    assert cells(grid, grid.subject, 0.44, 0.56, 0.42, 0.88) > 0.6          # the silhouette
    assert cells(grid, grid.subject, 0.0, 0.3) < 0.1 and cells(grid, grid.subject, 0.7, 1.0) < 0.1


def test_grid_region_weights_cells_by_how_much_of_them_is_covered():
    grid = Grid(2, 1, busy=(0.0, 1.0), bright=(0.2, 0.6), subject=(1.0, 0.0))
    assert grid.region(0, 0, 1, 1) == pytest.approx((0.5, 0.4, 0.5))
    assert grid.region(0, 0, 0.5, 1) == pytest.approx((0.0, 0.2, 1.0))
    assert grid.region(0.25, 0, 1, 1) == pytest.approx((2 / 3, 0.6 * 2 / 3 + 0.2 / 3, 1 / 3))
    assert grid.region(-3, -3, 9, 9) == pytest.approx((0.5, 0.4, 0.5))    # clamped to the picture
    assert grid.region(0.9, 0.5, 0.9, 0.5) == (1.0, 0.6, 0.0)             # a point: its cell


def test_warmth_dial_ranks_matching_wallpapers_first(wallpaper_set):
    assert rank(wallpaper_set, Dials(8, 5, 10))[0].path.endswith("warm.png")
    assert rank(wallpaper_set, Dials(8, 5, 1))[0].path.endswith("cold.png")


def test_low_cool_prefers_a_muted_wallpaper(wallpaper_set):
    assert rank(wallpaper_set, Dials(1, 8, 5))[0].path.endswith(("grey.png", "dusk.png"))


def test_score_is_best_for_a_perfect_match():
    perfect = wallpapers.Features(warmth=1, brightness=0.5, colourfulness=1, busyness=0)
    assert score(perfect, Dials(10, 10, 10)) == pytest.approx(0)
    assert score(perfect, Dials(1, 1, 1)) < -1


def test_choose_without_rng_is_the_best_match_whatever_the_order(wallpaper_set):
    dials = Dials(5, 5, 5)
    assert choose(wallpaper_set, dials) == choose(list(reversed(wallpaper_set)), dials)
    assert choose(wallpaper_set, dials) == rank(wallpaper_set, dials)[0]


def test_chaos_decides_how_far_from_the_best_match_a_draw_may_go(wallpaper_set):
    def picks(chaos):
        dials = Dials(8, 5, 10, chaos)
        return [choose(wallpaper_set, dials, random.Random(seed)).path for seed in range(300)]

    best = rank(wallpaper_set, Dials(8, 5, 10))[0].path
    calm, wild = picks(1), picks(10)
    assert calm.count(best) > 290                        # chaos 1: nearly always the best match
    assert len(set(wild)) == len(wallpaper_set)          # chaos 10: everything gets a turn
    assert wild.count(best) > 300 / len(wallpaper_set)   # ...but good matches are still favoured
    assert picks(5).count(best) > wild.count(best)


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
    assert found[1].size == (192, 108) and found[1].grid.cols == wallpapers.GRID_COLS
    assert Library(folder, tmp_path / "cache.json").scan() == found       # same again from the cache


def test_a_cache_from_an_older_version_is_rebuilt(tmp_path):
    folder = tmp_path / "walls"
    folder.mkdir()
    solid((230, 140, 40)).save(folder / "a.png")
    cache = tmp_path / "cache.json"
    stat = (folder / "a.png").stat()
    cache.write_text(json.dumps({str(folder / "a.png"): {
        "mtime": stat.st_mtime, "size": stat.st_size,
        "features": {"warmth": 0, "brightness": 0, "colourfulness": 0, "busyness": 0}, "colors": []}}))
    found = Library(folder, cache).scan()
    assert found[0].grid is not None and found[0].features.warmth > 0.8


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
            body = json.dumps({"data": self.pages.get(page, []),
                               "meta": {"last_page": max(self.pages, default=0)}}).encode()
        else:
            body = b"image-bytes:" + url.encode()
        return io.BytesIO(body)


def item(ident, ext="jpg"):
    return {"id": ident, "path": f"https://w.wallhaven.cc/full/{ident[:2]}/wallhaven-{ident}.{ext}"}


def test_fetch_saves_new_wallpapers_and_asks_only_for_sfw(tmp_path):
    web = FakeWallhaven({1: [item("aaa111"), item("bbb222", "png")]})
    saved = wallpapers.fetch(tmp_path, 5, "anime scenery", opener=web)
    assert [p.name for p in saved] == ["wallhaven-aaa111.jpg", "wallhaven-bbb222.png"]
    assert saved[0].read_bytes().startswith(b"image-bytes:")
    assert "purity=100" in web.urls[0] and "q=anime+scenery" in web.urls[0]
    assert "categories=110" in web.urls[0]
    assert not list(tmp_path.glob("*.part"))


def test_fetch_stops_at_count_and_skips_files_it_already_has(tmp_path):
    (tmp_path / "wallhaven-aaa111.jpg").write_bytes(b"old")
    web = FakeWallhaven({1: [item("aaa111"), item("bbb222")], 2: [item("ccc333"), item("ddd444")]})
    saved = wallpapers.fetch(tmp_path, 2, "sky", opener=web)
    assert [p.name for p in saved] == ["wallhaven-bbb222.jpg", "wallhaven-ccc333.jpg"]
    assert (tmp_path / "wallhaven-aaa111.jpg").read_bytes() == b"old"
    assert not any("ddd444" in url for url in web.urls)


def test_fetch_gives_up_when_results_run_out(tmp_path):
    web = FakeWallhaven({1: [item("aaa111")]})
    assert len(wallpapers.fetch(tmp_path, 10, "sky", opener=web)) == 1
    assert len(wallpapers.fetch(tmp_path, 10, opener=web, rng=random.Random(1))) == 0
    assert len(web.urls) < 3 * wallpapers.MAX_ROUNDS            # a varied fetch gives up too


def searches(web):
    return [urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            for url in web.urls if url.startswith(wallpapers.WALLHAVEN_SEARCH)]


def test_fetch_without_words_mixes_themes_from_their_best_pages(tmp_path):
    pages = {page: [item(f"p{page}n{n}") for n in range(24)] for page in range(1, wallpapers.TOP_PAGES + 1)}
    web = FakeWallhaven(pages)
    saved = wallpapers.fetch(tmp_path, 8, opener=web, rng=random.Random(7))
    asked = searches(web)
    assert len(saved) == 8 and len({p.name for p in saved}) == 8
    assert len({query["q"][0] for query in asked}) > 1 and len({query["page"][0] for query in asked}) > 1
    for query in asked:
        assert query["q"][0] in wallpapers.QUERIES and 1 <= int(query["page"][0]) <= wallpapers.TOP_PAGES
        assert query["purity"] == ["100"] and query["categories"] == ["110"]
        assert query["sorting"] == ["favorites"]
    again = FakeWallhaven(pages)
    other = tmp_path / "other"
    assert ([p.name for p in wallpapers.fetch(other, 8, opener=again, rng=random.Random(7))]
            == [p.name for p in saved])                      # the rng decides, nothing else


def test_fetch_without_words_looks_again_when_a_theme_has_fewer_pages(tmp_path):
    web = FakeWallhaven({1: [item("only11")]})
    saved = wallpapers.fetch(tmp_path, 1, opener=web, rng=random.Random(3))
    assert [p.name for p in saved] == ["wallhaven-only11.jpg"]
    assert searches(web)[-1]["page"] == ["1"]


def test_fetch_skips_what_the_library_has_held_before(tmp_path):
    web = FakeWallhaven({1: [item("aaa111"), item("bbb222"), item("ccc333")]})
    saved = wallpapers.fetch(tmp_path, 3, "sky", opener=web, seen={"aaa111", "ccc333"})
    assert [p.name for p in saved] == ["wallhaven-bbb222.jpg"]


def aged(folder, name, age):
    path = folder / name
    solid((90, 90, 90)).save(path)
    os.utime(path, (1_000_000 - age, 1_000_000 - age))
    return path


def test_retire_removes_the_oldest_fetched_images_down_to_the_cap(tmp_path):
    own = aged(tmp_path, "mine.png", 900)
    oldest, older, newer, newest = (aged(tmp_path, f"wallhaven-{name}.png", age)
                                    for name, age in (("a", 400), ("b", 300), ("c", 200), ("d", 100)))
    (tmp_path / "notes.txt").write_text("not an image, not counted")
    assert wallpapers.retire(tmp_path, 5) == []
    assert wallpapers.retire(tmp_path, 3, protected=[str(oldest)]) == [older, newer]
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "mine.png", "notes.txt", "wallhaven-a.png", "wallhaven-d.png"]
    # too few candidates: your own image and the protected one stay, over the cap
    assert wallpapers.retire(tmp_path, 1, protected=[str(oldest)]) == [newest]
    assert own.is_file() and oldest.is_file()
