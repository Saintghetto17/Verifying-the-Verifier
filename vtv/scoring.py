"""Deterministic scoring rule (Eq. 1), descriptive Overall (Eq. 2) and pair outcomes.

Faithfulness is never requested from the model. It is computed from the counts
of the structured evidence ledger:

* ``P`` confirmed requirements, ``M`` missing requirements,
* ``U`` unsupported visual elements,
* ``R_bad`` relations missing or drawn in the wrong direction,
* ``L_bad`` mismatched label bindings,

with ``D = U + R_bad + L_bad`` and coverage ``c = P / (P + M)``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

VALID_AXIS_SCORES = frozenset({1, 3, 5})

# Penalty variants on the unsupported-element counter (Table VI).
U_PENALTY_VARIANTS: dict[str, str] = {
    "current": "Current: U>=2 -> 1, U=1 -> 1 or 3",
    "shift_one": "U>=3 -> 1, U=2 -> 1 or 3",
    "single_free": "Single accusation not penalized",
    "no_u": "No penalty for U",
}


@dataclass(frozen=True)
class EvidenceCounts:
    P: int
    M: int
    U: int
    R_bad: int = 0
    L_bad: int = 0

    def __post_init__(self) -> None:
        if min(self.P, self.M, self.U, self.R_bad, self.L_bad) < 0:
            raise ValueError("evidence counts cannot be negative")
        if self.P + self.M < 1:
            raise ValueError("coverage needs at least one requirement")

    @property
    def coverage(self) -> float:
        return self.P / (self.P + self.M)

    def effective_u(self, variant: str = "current") -> int:
        if variant == "current":
            return self.U
        if variant == "shift_one":
            return max(self.U - 1, 0)
        if variant == "single_free":
            return 0 if self.U == 1 else self.U
        if variant == "no_u":
            return 0
        raise ValueError(f"unknown U-penalty variant: {variant}")

    def defects(self, variant: str = "current") -> int:
        return self.effective_u(variant) + self.R_bad + self.L_bad

    def as_dict(self) -> dict[str, int | float]:
        return {**asdict(self), "D": self.defects(), "coverage": round(self.coverage, 6)}

    @classmethod
    def from_dict(cls, value: dict) -> "EvidenceCounts":
        return cls(P=int(value["P"]), M=int(value["M"]), U=int(value["U"]),
                   R_bad=int(value.get("R_bad", 0)), L_bad=int(value.get("L_bad", 0)))


def faithfulness(counts: EvidenceCounts, tau_min: float = 0.60, tau_max: float = 0.80,
                 variant: str = "current") -> int:
    """Eq. (1): F in {1, 3, 5}, monotone non-increasing in D and non-decreasing in c."""
    d = counts.defects(variant)
    c = counts.coverage
    if d == 0 and c >= tau_max:
        return 5
    if d == 0 and c >= tau_min:
        return 3
    if d == 1 and counts.M == 0:
        return 3
    return 1


def overall(f: int, clarity: int, compactness: int, style: int,
            weights: tuple[float, float, float, float] = (0.45, 0.25, 0.15, 0.15)) -> float:
    """Eq. (2): descriptive weighted combination of the four axes."""
    for value in (f, clarity, compactness, style):
        if value not in VALID_AXIS_SCORES:
            raise ValueError("every axis must be 1, 3 or 5")
    wf, wcl, wco, ws = weights
    return round(wf * f + wcl * clarity + wco * compactness + ws * style, 8)


def outcome(reference: float, corrupted: float) -> str:
    """Pair outcome from the reference's point of view: win, tie or inversion."""
    if reference > corrupted:
        return "win"
    if reference < corrupted:
        return "inversion"
    return "tie"
