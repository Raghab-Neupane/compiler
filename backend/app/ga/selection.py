from __future__ import annotations

import random
from typing import Any, Iterable, List, Sequence


def _rank(candidate: Any) -> tuple:
    result = candidate.evaluation if hasattr(candidate, "evaluation") else candidate
    equivalent = bool(result and result.get("equivalent"))
    fitness = result.get("fitness") if result else None
    return (equivalent, fitness if fitness is not None else float("-inf"))


def tournament_select(
    candidates: Sequence[Any],
    rng: random.Random,
    tournament_size: int = 3,
) -> Any:
    if not candidates:
        raise ValueError("Cannot select from an empty candidate collection.")
    contenders = rng.sample(list(candidates), min(max(1, tournament_size), len(candidates)))
    return max(contenders, key=_rank)

