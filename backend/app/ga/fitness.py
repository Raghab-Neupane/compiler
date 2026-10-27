from __future__ import annotations

import statistics
import math
from typing import Any, Iterable, Optional


OBJECTIVES = {"execution_time", "binary_size"}


def calculate_fitness(
    metric: Optional[float],
    objective: str,
    equivalent: bool,
) -> Optional[float]:
    if objective not in OBJECTIVES:
        raise ValueError(f"Unsupported fitness objective: {objective}")
    if not equivalent or metric is None:
        return None
    try:
        value = float(metric)
    except (TypeError, ValueError):
        return None
    if value < 0 or not math.isfinite(value):
        return None
    return 1.0 / max(value, 1.0)


def median_metric(samples: Iterable[float]) -> Optional[float]:
    values = []
    for sample in samples:
        try:
            value = float(sample)
        except (TypeError, ValueError):
            continue
        if value >= 0 and math.isfinite(value):
            values.append(value)
    return statistics.median(values) if values else None


def median_absolute_deviation(samples: Iterable[float]) -> float:
    values = [float(sample) for sample in samples]
    if not values:
        return float("inf")
    center = statistics.median(values)
    return statistics.median(abs(value - center) for value in values)
