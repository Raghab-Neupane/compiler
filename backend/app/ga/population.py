from __future__ import annotations

import random
from typing import Iterable, List, Sequence, Tuple

from .chromosome import Chromosome, LLVM_PASS_REGISTRY, PassSpec


def generate_population(
    population_size: int,
    max_length: int,
    rng: random.Random,
    registry: Sequence[PassSpec] = LLVM_PASS_REGISTRY,
    id_prefix: str = "candidate",
) -> List[Chromosome]:
    if population_size < 1:
        raise ValueError("Population size must be positive.")
    if max_length < 1:
        raise ValueError("Maximum chromosome length must be positive.")
    if not registry:
        raise ValueError("The LLVM pass registry cannot be empty.")

    population: List[Chromosome] = []
    # Exercise every registered pass when the configured population allows it.
    for index, spec in enumerate(registry[:population_size]):
        population.append(
            Chromosome((spec.pass_id,), f"{id_prefix}-{index + 1:04d}", tuple(registry), max_length)
        )

    next_id = len(population) + 1
    seen = {chromosome.sequence for chromosome in population}
    attempts = 0
    while len(population) < population_size:
        length = rng.randint(1, min(max_length, len(registry)))
        sequence = tuple(rng.choice(registry).pass_id for _ in range(length))
        # Keep trying for diversity, but permit duplicates for very small search
        # spaces rather than looping forever.
        attempts += 1
        if sequence in seen and attempts < population_size * 20:
            continue
        seen.add(sequence)
        population.append(
            Chromosome(sequence, f"{id_prefix}-{next_id:04d}", tuple(registry), max_length)
        )
        next_id += 1
    return population

