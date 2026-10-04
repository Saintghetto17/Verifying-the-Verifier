"""Exact statistics used in the paper (standard library only)."""

from __future__ import annotations

import math
from dataclasses import dataclass

Z95 = 1.959963984540054


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """95% Wilson score interval for a proportion k/n."""
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _binom_pmf(k: int, n: int, p: float) -> float:
    if p in (0.0, 1.0):
        return float(k == (n if p == 1.0 else 0))
    return math.exp(math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
                    + k * math.log(p) + (n - k) * math.log(1 - p))


def binomial_test(k: int, n: int, p: float = 0.5) -> float:
    """Exact two-sided binomial test (sum of outcomes no more likely than k)."""
    if n == 0:
        return 1.0
    observed = _binom_pmf(k, n, p)
    total = sum(q for i in range(n + 1) if (q := _binom_pmf(i, n, p)) <= observed * (1 + 1e-7))
    return min(1.0, total)


def mcnemar_exact(b: int, c: int) -> float:
    """Exact McNemar test on the discordant counts b and c."""
    return binomial_test(min(b, c), b + c, 0.5)


def sign_test(wins: int, inversions: int) -> float:
    """Among resolved pairs, is the reference chosen more often than chance?"""
    return binomial_test(wins, wins + inversions, 0.5)


def jaccard(a: set, b: set) -> float:
    union = a | b
    return len(a & b) / len(union) if union else math.nan


@dataclass(frozen=True)
class Decomposition:
    """Win / tie / inversion decomposition of N pairs (Section V)."""

    n: int
    wins: int
    ties: int
    inversions: int

    @property
    def psr(self) -> float:
        return self.wins / self.n if self.n else math.nan

    @property
    def inversion_rate(self) -> float:
        return self.inversions / self.n if self.n else math.nan

    @property
    def tie_adjusted(self) -> float:
        return (self.wins + self.ties / 2) / self.n if self.n else math.nan

    @property
    def psr_ci(self) -> tuple[float, float]:
        return wilson(self.wins, self.n)

    @property
    def p_vs_coin(self) -> float:
        """Exact binomial test of PSR against the no-tie null of 50%."""
        return binomial_test(self.wins, self.n, 0.5)

    @property
    def p_sign(self) -> float:
        return sign_test(self.wins, self.inversions)

    def as_dict(self) -> dict[str, float | int]:
        lo, hi = self.psr_ci
        return {"n": self.n, "wins": self.wins, "ties": self.ties, "inversions": self.inversions,
                "psr": self.psr, "psr_ci_low": lo, "psr_ci_high": hi, "inversion_rate": self.inversion_rate,
                "tie_adjusted": self.tie_adjusted, "p_vs_coin": self.p_vs_coin, "p_sign": self.p_sign}


def decompose(pairs: dict[str, tuple[float, float]]) -> Decomposition:
    """``pairs`` maps pair id to (score of reference, score of corrupted figure)."""
    wins = sum(r > c for r, c in pairs.values())
    inversions = sum(r < c for r, c in pairs.values())
    return Decomposition(len(pairs), wins, len(pairs) - wins - inversions, inversions)
