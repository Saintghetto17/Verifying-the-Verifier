"""Turning completed runs into paired comparisons, ensembles and breakdowns.

The ensemble is arithmetic over finished independent runs (Eq. 3): the score
of a figure is the mean of the configurations' scores, and a pair is separated
when the reference's mean exceeds the corrupted figure's mean. No extra model
call is involved.
"""

from __future__ import annotations

import collections
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .artifacts import read_json
from .metrics import Decomposition, decompose, jaccard, mcnemar_exact
from .scoring import EvidenceCounts, faithfulness, overall

AXES = ("faithfulness", "clarity", "compactness", "style", "overall")


@dataclass
class PairScores:
    pair_id: str
    subset: str
    orig: dict[str, Any]
    fail: dict[str, Any]
    meta: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def operators(self) -> list[str]:
        return list((self.meta.get("defect") or {}).get("operators") or [])


Run = dict[str, PairScores]


def _rescored(side: dict[str, Any], config: dict[str, Any], variant: str) -> dict[str, Any]:
    scores = dict(side["scores"])
    counts = side.get("counts")
    if variant != "current" and counts:
        f = faithfulness(EvidenceCounts.from_dict(counts), config.get("tau_min", 0.6), config.get("tau_max", 0.8), variant)
        weights = (config.get("weight_faithfulness", 0.45), config.get("weight_clarity", 0.25),
                   config.get("weight_compactness", 0.15), config.get("weight_style", 0.15))
        scores["faithfulness"] = f
        scores["overall"] = overall(f, scores["clarity"], scores["compactness"], scores["style"], weights)
    return {**scores, "counts": counts}


def load_run(run_dir: Path | str, *, variant: str = "current") -> Run:
    """Completed pairs of one run, keyed by pair id. Partial pairs are dropped."""
    run_dir = Path(run_dir)
    manifest = read_json(run_dir / "run.json")
    config = manifest.get("config", {})
    out: Run = {}
    for line in (run_dir / "samples.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("status") != "complete":
            continue
        meta_path = run_dir / "samples" / record["pair_id"].replace("/", "__") / "pair.json"
        meta = read_json(meta_path) if meta_path.is_file() else {}
        out[record["pair_id"]] = PairScores(record["pair_id"], record.get("subset") or record["pair_id"].split("/")[0],
                                            _rescored(record["orig"], config, variant),
                                            _rescored(record["fail"], config, variant), meta)
    return out


def load_runs(run_dirs: Iterable[Path | str], *, variant: str = "current") -> Run:
    """Merge several runs of the same configuration (e.g. one per subset)."""
    merged: Run = {}
    for run_dir in run_dirs:
        merged.update(load_run(run_dir, variant=variant))
    return merged


def restrict(run: Run, ids: Iterable[str] | None = None, subset: str | None = None) -> Run:
    keep = set(ids) if ids is not None else None
    return {pid: s for pid, s in run.items()
            if (keep is None or pid in keep) and (subset is None or s.subset == subset)}


def common_ids(*runs: Run) -> set[str]:
    ids = set(runs[0])
    for run in runs[1:]:
        ids &= set(run)
    return ids


def ensemble(*runs: Run) -> Run:
    """Mean of each axis over configurations, on pairs completed by all of them."""
    out: Run = {}
    for pid in sorted(common_ids(*runs)):
        first = runs[0][pid]
        sides = {}
        for side in ("orig", "fail"):
            sides[side] = {axis: sum(getattr(r[pid], side)[axis] for r in runs) / len(runs) for axis in AXES}
        out[pid] = PairScores(pid, first.subset, sides["orig"], sides["fail"], first.meta)
    return out


def comparisons(run: Run, axis: str = "faithfulness") -> dict[str, tuple[float, float]]:
    return {pid: (s.orig[axis], s.fail[axis]) for pid, s in run.items()}


def decomposition(run: Run, axis: str = "faithfulness") -> Decomposition:
    return decompose(comparisons(run, axis))


def separated(run: Run, axis: str = "faithfulness") -> set[str]:
    return {pid for pid, (r, c) in comparisons(run, axis).items() if r > c}


def either_rule(*runs: Run) -> set[str]:
    """Asymmetric alternative to averaging: separated if any configuration separates."""
    ids = common_ids(*runs)
    return {pid for pid in ids if any(r[pid].orig["faithfulness"] > r[pid].fail["faithfulness"] for r in runs)}


def refs_at_max(run: Run) -> float:
    """Fraction of reference figures scored at the maximum F = 5 (specificity check)."""
    if not run:
        return math.nan
    return sum(s.orig["faithfulness"] == 5 for s in run.values()) / len(run)


def gain_loss(base: Run, other: Run) -> dict[str, Any]:
    """Pairs ``other`` separates that ``base`` does not (gain) and vice versa (loss)."""
    ids = common_ids(base, other)
    a, b = separated(restrict(base, ids)), separated(restrict(other, ids))
    gained, lost = len(b - a), len(a - b)
    return {"n": len(ids), "gained": gained, "lost": lost, "p_mcnemar": mcnemar_exact(gained, lost)}


def detection_overlap(a: Run, b: Run) -> float:
    """Jaccard overlap of the pairs each configuration separates (on common pairs)."""
    ids = common_ids(a, b)
    return jaccard(separated(restrict(a, ids)), separated(restrict(b, ids)))


def accusation_agreement(a: Run, b: Run) -> dict[str, float]:
    """Agreement of the unsupported-element counter between two configurations.

    For each side separately, the Jaccard overlap of the figures on which each
    configuration records at least one unsupported element (U >= 1). On
    references any accusation is false by construction.
    """
    ids = common_ids(a, b)
    out = {}
    for side in ("orig", "fail"):
        flagged = []
        for run in (a, b):
            flagged.append({pid for pid in ids if (getattr(run[pid], side).get("counts") or {}).get("U", 0) >= 1})
        out[side] = jaccard(*flagged)
    return out


def by_group(run: Run, key: str, axis: str = "faithfulness") -> dict[str, Decomposition]:
    """Decomposition per operator tag, topic or figure type (a pair may count under several tags)."""
    groups: dict[str, dict[str, tuple[float, float]]] = collections.defaultdict(dict)
    for pid, s in run.items():
        if key == "operator":
            labels = s.operators
        elif key == "source_label":
            labels = list((s.meta.get("defect") or {}).get("source_labels") or [])
        else:
            labels = [s.meta.get(key)] if s.meta.get(key) else []
        for label in labels:
            groups[label][pid] = (s.orig[axis], s.fail[axis])
    return {label: decompose(values) for label, values in sorted(groups.items())}
