from __future__ import annotations

import random
from typing import List, Sequence, Tuple

from .chromosome import PassSpec, validate_sequence


def mutate(
    sequence: Sequence[str],
    mutation_probability: float,
    max_length: int,
    rng: random.Random,
    registry: Sequence[PassSpec],
) -> Tuple[str, ...]:
    if not 0.0 <= mutation_probability <= 1.0:
        raise ValueError("Mutation probability must be between 0 and 1.")
    mutable = list(sequence)
    if rng.random() >= mutation_probability:
        return validate_sequence(mutable, registry, max_length)

    operation = rng.choice(("replace", "insert", "remove"))
    if operation == "replace" and mutable:
        mutable[rng.randrange(len(mutable))] = rng.choice(registry).pass_id
    elif operation == "insert" and len(mutable) < max_length:
        mutable.insert(rng.randrange(len(mutable) + 1), rng.choice(registry).pass_id)
    elif operation == "remove" and len(mutable) > 1:
        mutable.pop(rng.randrange(len(mutable)))
    return validate_sequence(mutable, registry, max_length)

