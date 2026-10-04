"""Recreate the paper's tables from completed runs.

The mapping from tables to run directories lives in an experiments file
(see ``experiments/paper.example.json``)::

    {
      "data_root": "data",
      "main":       {"tg": ["runs/<tg ml>", "runs/<tg bt>", "runs/<tg b75>"],
                     "hd": ["runs/<hd ml>", "runs/<hd bt>", "runs/<hd b75>"]},
      "ablation":   {"v01": ["runs/..."], "v02": ["runs/..."], ...},
      "third":      {"split": "balanced100", "candidates": {"v06": ["runs/..."], ...}},
      "halo":       {"split": "balanced100", "config": "hd"},
      "thresholds": {"split": "balanced100", "config": "hd"}
    }

Sections whose runs are absent are skipped. Every number is computed from the
ledgers stored in the runs; nothing is copied from the paper.
"""

from __future__ import annotations

import collections
import json
import math
from pathlib import Path
from typing import Any

from . import analysis as A
from .config import PROJECT_ROOT
from .data import load_records, read_split
from .metrics import Decomposition
from .scoring import U_PENALTY_VARIANTS
from .taxonomy import OPERATOR_NAMES, OPERATORS

SUBSET_NAMES = {"ml": "ML", "bt": "BT", "b75": "B75"}


def pct(x: float, digits: int = 1) -> str:
    return "--" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{100 * x:.{digits}f}"


def pval(p: float) -> str:
    if p >= 0.01:
        return f"{p:.2f}"
    exponent = math.floor(math.log10(p)) if p > 0 else -300
    return f"{p / 10 ** exponent:.1f}e{exponent}"


def table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---:" if i else "---" for i in range(len(headers))) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


class Report:
    def __init__(self, spec: dict[str, Any], base: Path):
        self.spec = spec
        self.base = base
        self.data_root = (base / spec.get("data_root", "data")).resolve()
        self.sections: list[str] = []
        self.results: dict[str, Any] = {}

    def _runs(self, dirs: list[str], variant: str = "current") -> A.Run:
        return A.load_runs([self.base / d for d in dirs], variant=variant)

    def _main(self, variant: str = "current") -> tuple[A.Run, A.Run] | None:
        main = self.spec.get("main") or {}
        if not main.get("tg") or not main.get("hd"):
            return None
        tg, hd = self._runs(main["tg"], variant), self._runs(main["hd"], variant)
        ids = A.common_ids(tg, hd)
        return A.restrict(tg, ids), A.restrict(hd, ids)

    def _config(self, name: str, split: str | None, variant: str = "current") -> A.Run | None:
        main = self._main(variant)
        if main is None:
            return None
        tg, hd = main
        run = {"tg": tg, "hd": hd, "ensemble": A.ensemble(tg, hd)}[name]
        return A.restrict(run, read_split(self.data_root, split)) if split else run

    # ------------------------------------------------------------------ tables

    def corpus(self) -> None:
        records = load_records(self.data_root)
        main = self._main()
        both = collections.Counter(s.subset for s in main[0].values()) if main else {}
        rows = []
        for subset in ("ml", "bt", "b75"):
            rs = [r for r in records if r["subset"] == subset]
            rows.append([SUBSET_NAMES[subset], len(rs), both.get(subset, "--"),
                         sum(r["images_available"] for r in rs), len({r["topic"] for r in rs})])
        rows.append(["Total", len(records), sum(both.values()) if both else "--",
                     sum(r["images_available"] for r in records), ""])
        self.sections.append("## Table I — Corpus\n\n" + table(
            ["Subset", "Pairs", "Both", "Images released", "Topics"], rows))
        self.results["corpus"] = rows

    def main_table(self) -> None:
        main = self._main()
        if main is None:
            return
        tg, hd = main
        ens = A.ensemble(tg, hd)
        rows, out = [], {}
        for subset in ("ml", "bt", "b75", None):
            t, h, e = (A.restrict(r, subset=subset) for r in (tg, hd, ens))
            if not e:
                continue
            dt, dh, de = A.decomposition(t), A.decomposition(h), A.decomposition(e)
            lo, hi = de.psr_ci
            name = SUBSET_NAMES.get(subset, "All")
            rows.append([name, de.n, pct(dt.psr), pct(dh.psr), f"{pct(de.psr)} [{pct(lo)}--{pct(hi)}]", de.ties, de.inversions])
            out[name] = {"tg": dt.as_dict(), "hd": dh.as_dict(), "ensemble": de.as_dict(),
                         "tg_to_ens": A.gain_loss(t, e), "hd_to_ens": A.gain_loss(h, e),
                         "overlap_tg_hd": A.detection_overlap(t, h),
                         "either_rule_psr": len(A.either_rule(t, h)) / len(e),
                         "refs_at_max": {"tg": A.refs_at_max(t), "hd": A.refs_at_max(h)},
                         "tie_adjusted": {"tg": dt.tie_adjusted, "hd": dh.tie_adjusted, "ensemble": de.tie_adjusted}}
        self.sections.append("## Table II — Faithfulness separation by subset\n\n" + table(
            ["Subset", "N", "TG (%)", "HD (%)", "Ensemble (%) [95% Wilson]", "Ties", "Inv."], rows))
        notes = []
        for name, r in out.items():
            notes.append(
                f"- **{name}**: TG→Ens +{r['tg_to_ens']['gained']}/−{r['tg_to_ens']['lost']} "
                f"(McNemar p={pval(r['tg_to_ens']['p_mcnemar'])}); HD→Ens +{r['hd_to_ens']['gained']}/−{r['hd_to_ens']['lost']} "
                f"(p={pval(r['hd_to_ens']['p_mcnemar'])}); Jaccard(TG,HD)={r['overlap_tg_hd']:.2f}; "
                f"either-rule {pct(r['either_rule_psr'])}%; tie-adjusted TG/HD/Ens "
                f"{pct(r['tie_adjusted']['tg'])}/{pct(r['tie_adjusted']['hd'])}/{pct(r['tie_adjusted']['ensemble'])}%; "
                f"refs at F=5 TG/HD {pct(r['refs_at_max']['tg'])}/{pct(r['refs_at_max']['hd'])}%; "
                f"binomial vs 50%: TG p={pval(r['tg']['p_vs_coin'])}, HD p={pval(r['hd']['p_vs_coin'])}, "
                f"Ens p={pval(r['ensemble']['p_vs_coin'])}; sign test Ens p={pval(r['ensemble']['p_sign'])}")
        floor = sorted(pid for pid in tg if tg[pid].orig["faithfulness"] == 1 and hd[pid].orig["faithfulness"] == 1)
        floor_ties = [pid for pid in floor if tg[pid].fail["faithfulness"] == 1 and hd[pid].fail["faithfulness"] == 1]
        notes.append(f"- References at the minimum under both configurations: {len(floor)} "
                     f"({len(floor_ties)} of them tied at the floor): {', '.join(floor) or 'none'}")
        self.results["low_references"] = {"both_min": floor, "tied_at_floor": floor_ties}
        agreement = A.accusation_agreement(tg, hd)
        notes.append(f"- Unsupported-counter agreement (Jaccard of U>=1): references {pct(agreement['orig'], 0)}%, "
                     f"corrupted {pct(agreement['fail'], 0)}%")
        self.sections.append("\n".join(notes))
        self.results["main"] = out
        self.results["accusation_agreement"] = agreement

    def operators(self) -> None:
        main = self._main()
        if main is None:
            return
        tg, hd = main
        ens = A.ensemble(tg, hd)
        rows, out = [], {}
        per_subset = {s: A.by_group(A.restrict(ens, subset=s), "operator") for s in ("ml", "bt", "b75")}
        per_cfg = {name: A.by_group(A.restrict(run, subset="ml"), "operator") for name, run in (("tg", tg), ("hd", hd))}
        for op in OPERATORS:
            cells = [OPERATOR_NAMES[op]]
            for s in ("ml", "bt", "b75"):
                d = per_subset[s].get(op)
                cells.append(f"{pct(d.psr, 0)} ({d.wins}/{d.n})" if d else "--")
            for name in ("tg", "hd"):
                d = per_cfg[name].get(op)
                cells.append(f"{d.wins}/{d.n}" if d else "--")
            rows.append(cells)
            out[op] = {s: per_subset[s][op].as_dict() for s in per_subset if op in per_subset[s]}
        self.sections.append("## Per-operator ensemble separation (Section VII-D)\n\n" + table(
            ["Operator", "ML", "BT", "B75", "ML TG", "ML HD"], rows))
        extra = []
        for subset, key in (("bt", "topic"), ("b75", "topic"), ("b75", "figure_type")):
            groups = A.by_group(A.restrict(ens, subset=subset), key)
            extra.append(f"**{SUBSET_NAMES[subset]} by {key}:** " + "; ".join(
                f"{k} {pct(d.psr, 0)}% ({d.wins}/{d.n})" for k, d in sorted(groups.items(), key=lambda kv: -kv[1].n)))
        self.sections.append("\n\n".join(extra))
        self.results["operators"] = out

    def halo(self) -> None:
        spec = self.spec.get("halo")
        if not spec:
            return
        run = self._config(spec.get("config", "hd"), spec.get("split", "balanced100"))
        if not run:
            return
        groups = {axis: A.by_group(run, "operator", axis) for axis in ("faithfulness", "clarity", "style")}
        rows = [[OPERATOR_NAMES[op]] + [pct(groups[a][op].psr, 0) for a in groups] + [groups["faithfulness"][op].n]
                for op in OPERATORS if op in groups["faithfulness"]]
        self.sections.append(f"## Table III — Separation by axis across operators ({spec.get('config', 'hd')}, "
                             f"{len(run)} pairs)\n\n" + table(["Operator", "Faithfulness (%)", "Clarity (%)", "Style (%)", "n"], rows))
        self.results["halo"] = rows

    def third(self) -> None:
        spec = self.spec.get("third")
        main = self._main()
        if not spec or main is None:
            return
        ids = set(read_split(self.data_root, spec.get("split", "balanced100")))
        tg, hd = (A.restrict(r, ids) for r in main)
        rows, out = [], {}
        pair_psr = A.decomposition(A.ensemble(tg, hd)).psr
        for version, dirs in spec.get("candidates", {}).items():
            cand = A.restrict(self._runs(dirs), ids)
            common = A.common_ids(tg, hd, cand)
            t, h, c = (A.restrict(r, common) for r in (tg, hd, cand))
            alone = A.decomposition(c).psr
            triple = A.decomposition(A.ensemble(t, h, c)).psr
            out[version] = {"n": len(common), "alone": alone, "triple": triple,
                            "pair_tg_hd": A.decomposition(A.ensemble(t, h)).psr,
                            "pair_with_hd": A.decomposition(A.ensemble(h, c)).psr,
                            "overlap_tg": A.detection_overlap(t, c), "overlap_hd": A.detection_overlap(h, c)}
            rows.append([version, len(common), pct(alone, 0), pct(triple, 0), pct(out[version]["overlap_tg"], 0),
                         pct(out[version]["overlap_hd"], 0), pct(out[version]["pair_with_hd"], 0)])
        self.sections.append(f"## Table IV — Candidate third configurations (TG+HD pair: {pct(pair_psr, 0)}%)\n\n" + table(
            ["Third", "n", "Alone (%)", "Triple (%)", "Overlap TG (%)", "Overlap HD (%)", "Pair with HD (%)"], rows))
        self.results["third"] = out

    def ablation(self) -> None:
        spec = self.spec.get("ablation")
        if not spec:
            return
        from .prompts import load_registry
        registry = load_registry()["versions"]
        rows = []
        for version, dirs in sorted(spec.items()):
            run = self._runs(dirs)
            d = A.decomposition(run)
            rows.append([version, registry.get(version, {}).get("mechanism", ""), d.n, pct(d.psr, 0), pct(A.refs_at_max(run), 0)])
        self.sections.append("## Table V — Prompt ablation\n\n" + table(
            ["Version", "Mechanism added", "n", "PSR (%)", "Refs at F=5 (%)"], rows))
        self.results["ablation"] = rows

    def thresholds(self) -> None:
        spec = self.spec.get("thresholds")
        if not spec:
            return
        rows = []
        for variant, label in U_PENALTY_VARIANTS.items():
            run = self._config(spec.get("config", "hd"), spec.get("split", "balanced100"), variant)
            if not run:
                return
            rows.append([label, pct(A.decomposition(run).psr, 0), pct(A.refs_at_max(run), 0)])
        self.sections.append("## Table VI — Sensitivity to the unsupported-element penalty\n\n" + table(
            ["Rule on unsupported elements", "PSR (%)", "Refs at F=5 (%)"], rows))
        self.results["thresholds"] = rows

    def build(self) -> str:
        for step in (self.corpus, self.main_table, self.operators, self.halo, self.third, self.ablation, self.thresholds):
            step()
        return "# Verifying the Verifier — recreated tables\n\n" + "\n\n".join(self.sections) + "\n"


def pair_report(tg_dirs: list[str], hd_dirs: list[str], data_root: str = "data") -> str:
    """Quick report for one TG/HD pair of runs without an experiments file."""
    spec = {"data_root": data_root, "main": {"tg": tg_dirs, "hd": hd_dirs}}
    report = Report(spec, PROJECT_ROOT)
    report.main_table()
    report.operators()
    return "\n\n".join(report.sections) + "\n"


def write_report(spec_path: Path, out_dir: Path) -> Path:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    # Paths in the experiments file are relative to the repository root.
    report = Report(spec, PROJECT_ROOT)
    text = report.build()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tables.md").write_text(text, encoding="utf-8")
    (out_dir / "results.json").write_text(json.dumps(report.results, indent=1, default=str), encoding="utf-8")
    return out_dir / "tables.md"


__all__ = ["Report", "write_report", "pair_report", "Decomposition"]
