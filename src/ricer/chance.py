"""Controlled randomness: seeded streams, and choices whose odds the dials shape.

Every random decision in a look goes through here, so one seed reproduces the whole look and
the chaos dial has a single, consistent meaning: how far choices may stray from the odds.
"""
from __future__ import annotations

import math
import random

from ricer.look import DIAL_MAX, DIAL_MIN


def stream(seed: int, stage: str) -> random.Random:
    """An independent random stream for one stage of generating a look.

    Stages do not share a stream, so pinning one stage (--keep) leaves the others unchanged.
    """
    return random.Random(f"{seed}/{stage}")


def temperature(chaos: int) -> float:
    """Below 1 sharpens the odds toward the favourite; above 1 flattens them."""
    return 0.35 + 0.17 * (chaos - DIAL_MIN)


def draw(rng: random.Random, weights: dict):
    """Choose a key of `weights` with odds exactly proportional to its value."""
    options = [(key, weight) for key, weight in weights.items() if weight > 0]
    if not options:
        raise ValueError("nothing to pick from: every option has zero weight")
    remaining = rng.random() * sum(weight for _, weight in options)
    for key, weight in options:
        remaining -= weight
        if remaining <= 0:
            return key
    return options[-1][0]


def pick(rng: random.Random, weights: dict, chaos: int):
    """Choose a key of `weights` with odds given by its values, tempered by chaos.

    A weight of zero or less is a hard exclusion at any chaos level.
    """
    exponent = 1 / temperature(chaos)
    return draw(rng, {key: weight ** exponent for key, weight in weights.items() if weight > 0})


def spread(chaos: int, base: float = 0.03, per_step: float = 0.025) -> float:
    """Standard deviation of the noise added to a 0..1 trait at this chaos level."""
    return base + per_step * (chaos - DIAL_MIN)


def jitter(rng: random.Random, mean: float, chaos: int, low: float = 0.0, high: float = 1.0,
           scale: float = 1.0) -> float:
    """`mean` plus chaos-sized noise, kept within low..high. `scale` widens or narrows it."""
    return max(low, min(high, rng.gauss(mean, spread(chaos) * scale * (high - low))))


def noisy_dial(rng: random.Random, value: int, chaos: int) -> float:
    """A dial reading with chaos-sized noise, for thresholds that should not be knife edges."""
    return rng.gauss(value, 0.3 + 0.12 * (chaos - DIAL_MIN))


def chance(rng: random.Random, probability: float) -> bool:
    return rng.random() < max(0.0, min(1.0, probability))


def bump(x: float, centre: float, width: float) -> float:
    """A tent function: 1 at `centre`, falling to 0 at `width` away. For weights over a dial."""
    return max(0.0, 1 - abs(x - centre) / width)


def softmin_weights(costs: dict, sharpness: float) -> dict:
    """Turn costs (lower is better) into pick() weights; higher sharpness favours the best more."""
    best = min(costs.values())
    return {key: math.exp(-(cost - best) * sharpness) for key, cost in costs.items()}


__all__ = ["stream", "temperature", "draw", "pick", "spread", "jitter", "noisy_dial", "chance", "bump",
           "softmin_weights", "DIAL_MIN", "DIAL_MAX"]
