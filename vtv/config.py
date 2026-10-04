"""Run configuration. Every field is stored verbatim in each run's ``run.json``."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = PROJECT_ROOT / "data"
DEFAULT_PROMPTS_ROOT = PROJECT_ROOT / "prompts"
DEFAULT_RUNS_ROOT = PROJECT_ROOT / "runs"

HF_DATASET = "Saintghetto17/verifying-the-verifier"
DEFAULT_MODEL = "google/gemini-3.7-flash"


@dataclass(frozen=True)
class RunConfig:
    """Decoding, retry and scoring parameters of one verification run (Section VI)."""

    model: str = DEFAULT_MODEL
    temperature: float = 0.0
    top_p: float = 1.0
    seed: int = 42
    max_tokens: int = 16384
    reasoning_effort: str = "medium"
    timeout_seconds: int = 300
    # Three network attempts per request; one initial answer plus two retries
    # when the returned JSON is not a valid evidence ledger.
    network_attempts: int = 3
    invalid_response_attempts: int = 3
    # Pairs processed concurrently; the two sides of a pair are always two
    # independent requests.
    workers: int = 10
    max_cost_usd: float | None = None
    # Scoring rule (Eq. 1). Fixed before any verification run.
    tau_min: float = 0.60
    tau_max: float = 0.80
    min_requirements: int = 3
    # Descriptive Overall score (Eq. 2). Separation depends on F alone.
    weight_faithfulness: float = 0.45
    weight_clarity: float = 0.25
    weight_compactness: float = 0.15
    weight_style: float = 0.15
    protocol: str = "blind_single_figure_v2"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RunConfig":
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in value.items() if k in allowed})
