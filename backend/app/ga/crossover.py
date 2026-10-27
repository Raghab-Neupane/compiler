from __future__ import annotations

import random
from typing import Sequence, Tuple

from .chromosome import PassSpec, validate_sequence


def one_point_crossover(
    first: Sequence[str],
    second: Sequence[str],
    max_length: int,
    rng: random.Random,
    registry: Sequence[PassSpec],
) -> Tuple[str, ...]:
    first_cut = rng.randint(0, len(first))
    second_cut = rng.randint(0, len(second))
    child = tuple(first[:first_cut] + tuple(second[second_cut:]))[:max_length]
    if not child:
        child = (rng.choice(registry).pass_id,)
    return validate_sequence(child, registry, max_length)

