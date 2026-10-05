import collections
import statistics

import pytest

from ricer import chance


def test_streams_repeat_and_do_not_share_state():
    assert chance.stream(7, "style").random() == chance.stream(7, "style").random()
    assert chance.stream(7, "style").random() != chance.stream(7, "bar").random()
    assert chance.stream(7, "style").random() != chance.stream(8, "style").random()


def shares(weights, chaos, draws=4000):
    rng = chance.stream(1, f"shares-{chaos}")
    counts = collections.Counter(chance.pick(rng, weights, chaos) for _ in range(draws))
    return {key: counts[key] / draws for key in weights}


def test_chaos_sharpens_or_flattens_the_odds():
    weights = {"favourite": 0.6, "second": 0.3, "rare": 0.1}
    calm, neutral, wild = shares(weights, 1), shares(weights, 5), shares(weights, 10)
    assert calm["favourite"] > 0.82 and calm["rare"] < 0.02
    assert neutral["favourite"] == pytest.approx(0.6, abs=0.05)
    assert wild["favourite"] < 0.55 and wild["rare"] > 0.12
    assert calm["favourite"] > neutral["favourite"] > wild["favourite"]


def test_zero_weight_is_never_picked_whatever_the_chaos():
    for chaos in (1, 5, 10):
        assert shares({"yes": 1.0, "no": 0.0, "never": -2}, chaos, 300) == {"yes": 1.0, "no": 0, "never": 0}
    with pytest.raises(ValueError):
        chance.pick(chance.stream(1, "x"), {"a": 0, "b": 0}, 5)


def test_draw_follows_the_weights_exactly():
    rng = chance.stream(3, "draw")
    counts = collections.Counter(chance.draw(rng, {"a": 3, "b": 1}) for _ in range(4000))
    assert counts["a"] / 4000 == pytest.approx(0.75, abs=0.03)


def test_jitter_stays_in_bounds_and_grows_with_chaos():
    def samples(chaos):
        rng = chance.stream(5, f"jitter-{chaos}")
        return [chance.jitter(rng, 0.5, chaos) for _ in range(2000)]

    calm, wild = samples(1), samples(10)
    assert all(0 <= value <= 1 for value in calm + wild)
    assert statistics.mean(calm) == pytest.approx(0.5, abs=0.02)
    assert statistics.pstdev(wild) > 3 * statistics.pstdev(calm)
    rng = chance.stream(5, "edge")
    assert all(0.9 <= chance.jitter(rng, 1.4, 10, 0.9, 1.35) <= 1.35 for _ in range(200))


def test_noisy_dial_centres_on_the_dial():
    rng = chance.stream(9, "dial")
    readings = [chance.noisy_dial(rng, 7, 5) for _ in range(3000)]
    assert statistics.mean(readings) == pytest.approx(7, abs=0.06)
    assert chance.temperature(1) < 1 < chance.temperature(10)


def test_helpers():
    assert chance.bump(0.5, 0.5, 0.2) == 1 and chance.bump(0.6, 0.5, 0.2) == pytest.approx(0.5)
    assert chance.bump(0.9, 0.5, 0.2) == 0
    weights = chance.softmin_weights({"cheap": 0.1, "dear": 0.6}, 10)
    assert weights["cheap"] == 1 and weights["dear"] < 0.01
    rng = chance.stream(2, "coin")
    assert not chance.chance(rng, 0) and chance.chance(rng, 1) and chance.chance(rng, 7)
