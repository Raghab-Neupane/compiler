from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class PassSpec:
    """A pass exposed to the GA and its actual LLVM textual pipeline name."""

    pass_id: str
    display_name: str
    pipeline: str


# These are LLVM new-pass-manager pipeline identifiers, not TAC pass names.
# The registry is validated against `opt --print-passes` before optimization.
LLVM_PASS_REGISTRY: Tuple[PassSpec, ...] = (
    PassSpec("simplifycfg", "Simplify CFG", "simplifycfg"),
    PassSpec("instcombine", "Instruction Combining", "instcombine"),
    PassSpec("sroa", "Scalar Replacement of Aggregates", "sroa"),
    PassSpec("early-cse", "Early CSE", "early-cse"),
    PassSpec("reassociate", "Reassociate Expressions", "reassociate"),
    PassSpec("gvn", "Global Value Numbering", "gvn"),
    PassSpec("dce", "Dead Code Elimination", "dce"),
    PassSpec("adce", "Aggressive DCE", "adce"),
    PassSpec("loop-simplify", "Loop Simplify", "loop-simplify"),
    PassSpec("licm", "Loop Invariant Code Motion", "licm"),
    PassSpec("indvars", "Induction Variable Simplification", "indvars"),
)


def registry_map(registry: Sequence[PassSpec] = LLVM_PASS_REGISTRY) -> Mapping[str, PassSpec]:
    return {spec.pass_id: spec for spec in registry}


def validate_sequence(
    sequence: Sequence[str],
    registry: Sequence[PassSpec] = LLVM_PASS_REGISTRY,
    max_length: Optional[int] = None,
) -> Tuple[str, ...]:
    normalized = tuple(str(pass_id).strip() for pass_id in sequence)
    if not normalized:
        raise ValueError("A chromosome must contain at least one LLVM pass.")
    if max_length is not None and len(normalized) > max_length:
        raise ValueError("Chromosome exceeds the configured maximum length.")
    known = registry_map(registry)
    unknown = [pass_id for pass_id in normalized if pass_id not in known]
    if unknown:
        raise ValueError(f"Unknown LLVM optimization pass(es): {', '.join(unknown)}")
    return normalized


@dataclass
class Chromosome:
    sequence: Tuple[str, ...]
    candidate_id: str
    registry: Tuple[PassSpec, ...] = LLVM_PASS_REGISTRY
    max_length: Optional[int] = None
    evaluation: Optional[dict[str, Any]] = field(default=None, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "sequence",
            validate_sequence(self.sequence, self.registry, self.max_length),
        )

    @property
    def pass_sequence(self) -> Tuple[str, ...]:
        return self.sequence

    def validate(self) -> bool:
        validate_sequence(self.sequence, self.registry, self.max_length)
        return True

    def copy_with_sequence(self, sequence: Sequence[str], candidate_id: str) -> "Chromosome":
        return Chromosome(
            tuple(sequence),
            candidate_id,
            registry=self.registry,
            max_length=self.max_length,
        )

