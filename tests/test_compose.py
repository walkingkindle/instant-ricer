import dataclasses
import random

import pytest

from ricer import compose as composing
from ricer.compose import compose, difference, fingerprint, novelty, placement_cost, remember
from ricer.generator import generate, kept_from
from ricer.look import Dials


def test_with_a_seed_compose_is_exactly_that_look(wallpaper_set):
    assert compose(Dials(7, 5, 5), wallpaper_set, seed=99) == generate(Dials(7, 5, 5), wallpaper_set, 99)
    history = [fingerprint(generate(Dials(7, 5, 5), wallpaper_set, 99))]
    assert compose(Dials(7, 5, 5), wallpaper_set, history, seed=99) == generate(Dials(7, 5, 5), wallpaper_set, 99)


def test_a_composed_look_can_be_had_again_from_its_seed(wallpaper_set):
    look = compose(Dials(8, 6, 4), wallpaper_set, entropy=random.Random(3))
    assert generate(Dials(8, 6, 4), wallpaper_set, look.seed) == look
    assert compose(Dials(8, 6, 4), wallpaper_set, entropy=random.Random(3)) == look


def test_difference_is_zero_for_the_same_look_and_grows_with_each_feature(wallpaper_set):
    a = fingerprint(generate(Dials(8, 5, 5), wallpaper_set, 1))
    assert difference(a, a) == 0
    assert difference(a, {**a, "wallpaper": "/other.png"}) == pytest.approx(0.35)
    assert difference(a, {**a, "bar": "nope", "voice": "nope"}) == pytest.approx(0.15)
    nothing_alike = {"wallpaper": "x", "widgets": {"tv": "crt"}, "zones": {"tv": "floor"}, "bar": "x",
                     "layout": "x", "voice": "x"}
    assert difference(a, nothing_alike) == pytest.approx(1.0)
    assert difference({"widgets": {}, "zones": {}}, {"widgets": {}, "zones": {}}) == 0


def test_changing_one_widget_design_is_a_partial_difference():
    a = {"wallpaper": "w", "widgets": {"clock": "digital", "media": "card"}, "zones": {}, "bar": "b",
         "layout": "l", "voice": "v"}
    b = {**a, "widgets": {"clock": "analog", "media": "card"}}
    assert difference(a, b) == pytest.approx(0.25 * 0.5)


def test_novelty_weighs_the_latest_look_most(wallpaper_set):
    a, b = (fingerprint(generate(Dials(8, 5, 5), wallpaper_set, seed)) for seed in (1, 2))
    assert novelty(a, []) == 1.0
    assert novelty(a, [a]) == 0
    assert novelty(a, [a, b]) < novelty(a, [b, a])           # matching the newest costs more


def test_runs_in_a_row_avoid_repeating_the_wallpaper(wallpaper_set):
    entropy, history, walls = random.Random(11), [], []
    for _ in range(40):
        look = compose(Dials(6, 5, 5), wallpaper_set, history, entropy=entropy)
        walls.append(look.wallpaper)
        history = remember(history, look)
    repeats = sum(1 for earlier, later in zip(walls, walls[1:]) if earlier == later)
    assert repeats == 0 and len(set(walls)) >= 4
    # nor does one come back in the run after next, while there are others to use
    assert all(len(set(walls[i:i + 3])) == 3 for i in range(len(walls) - 2))

    without_memory = [compose(Dials(6, 5, 5), wallpaper_set, [], entropy=entropy).wallpaper for _ in range(40)]
    assert sum(1 for earlier, later in zip(without_memory, without_memory[1:]) if earlier == later) > 5


def test_at_the_lowest_chaos_the_best_wallpaper_simply_stays(wallpaper_set):
    entropy, history, walls = random.Random(2), [], set()
    for _ in range(6):
        look = compose(Dials(8, 5, 10, 1), wallpaper_set, history, entropy=entropy)
        walls.add(look.wallpaper)
        history = remember(history, look)
    assert walls == {"/walls/warm.png"}


def test_candidate_seeds_prefer_fresh_wallpapers_without_changing_any_seed(wallpaper_set):
    dials = Dials(6, 5, 5)
    plain = composing.candidate_seeds(dials, wallpaper_set, [], composing.Kept(), 1000)
    assert plain == list(range(1000, 1000 + composing.CANDIDATES))
    stale = generate(dials, wallpaper_set, 1000).wallpaper
    seeds = composing.candidate_seeds(dials, wallpaper_set, [{"wallpaper": stale}], composing.Kept(), 1000)
    assert all(generate(dials, wallpaper_set, seed).wallpaper != stale for seed in seeds)
    assert seeds == sorted(seeds) and len(seeds) == composing.CANDIDATES
    kept = composing.candidate_seeds(dials, wallpaper_set, [{"wallpaper": stale}],
                                     composing.Kept(wallpaper=stale), 1000)
    assert kept == plain                                     # a kept wallpaper is not second-guessed


def test_a_badly_placed_candidate_loses_to_a_well_placed_one(wallpaper_set, monkeypatch):
    first = random.Random(5).randrange(1, 2 ** 31 - composing.SCAN)
    monkeypatch.setattr(composing, "placement_cost",
                        lambda look, wallpaper, screen: 0.2 if look.seed == first + 3 else 2.0)
    monkeypatch.setattr(composing, "novelty", lambda print_, history: 1.0)
    assert compose(Dials(8, 5, 5), wallpaper_set, entropy=random.Random(5)).seed == first + 3


def test_placement_is_a_gate_not_a_ranking(wallpaper_set, monkeypatch):
    first = random.Random(5).randrange(1, 2 ** 31 - composing.SCAN)
    # all candidates are "good enough"; the most novel one must win even though it costs more
    monkeypatch.setattr(composing, "placement_cost",
                        lambda look, wallpaper, screen: 0.44 if look.seed == first + 6 else 0.05)
    monkeypatch.setattr(composing, "novelty",
                        lambda print_, history: 0.9 if print_ == "pick-me" else 0.8)
    monkeypatch.setattr(composing, "fingerprint", lambda look: "pick-me" if look.seed == first + 6 else "x")
    assert compose(Dials(8, 5, 5), wallpaper_set, entropy=random.Random(5)).seed == first + 6


def test_placement_cost_handles_empty_and_full_desktops(wallpaper_set, lopsided):
    empty = generate(Dials(cool=1), wallpaper_set, 1)
    assert not empty.widgets and placement_cost(empty, wallpaper_set[0]) == composing.EMPTY_COST
    full = generate(Dials(cool=9), [lopsided], 4)
    assert full.widgets and 0 <= placement_cost(full, lopsided) < 1.5


def test_remember_keeps_only_the_last_few(wallpaper_set):
    history = []
    for seed in range(1, 12):
        history = remember(history, generate(Dials(), wallpaper_set, seed))
    assert len(history) == composing.HISTORY
    assert history[0] == fingerprint(generate(Dials(), wallpaper_set, 11))


def test_compose_honours_kept_parts(wallpaper_set):
    current = generate(Dials(8, 5, 5), wallpaper_set, 3)
    for _ in range(5):
        look = compose(Dials(8, 5, 5), wallpaper_set, [fingerprint(current)],
                       keep=kept_from(current, ["wallpaper", "style"]))
        assert look.wallpaper == current.wallpaper and look.style == current.style
