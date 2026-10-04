#!/usr/bin/env python3
"""Assemble the counterfactual benchmark release from its three source corpora.

Sources
-------
* ML  — the Verification-Before-Assembly figure dump (Hugging Face dataset
  ``Saintghetto17/verification-before-assembly``): ``figures/ml_l2_fail`` and
  ``figures/ml_orig`` plus their ``golden/`` counterparts.
* BT  — ``bench_l2_folders`` (zip or directory): 212 biotechnology folders,
  each with the original (``*_orig_*``) and corrupted (``*_l2_fail_*``) page crop.
* B75 — ``bench_final``: 75 cross-domain records (``dataset.jsonl``). Images are
  taken from the folder when present; the 11 ``bt_`` pairs fall back to the
  matching BT folder.

Output layout
-------------
::

    <out>/pairs/<subset>/<local_id>/{orig.png, fail.png}
    <out>/metadata/pairs.jsonl          one record per pair (all subsets)
    <out>/metadata/ml_candidates.jsonl  every ML candidate with its filter outcome
    <out>/metadata/summary.json         counts used in the corpus tables
    <out>/splits/*.txt                  pair-id lists

Usage
-----
    python scripts/build_dataset.py \
        --vba-root ../hf_verification-before-assembly \
        --bt-source ../bench_l2_folders.zip \
        --b75-root ../bench_final \
        --out data
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vtv.taxonomy import OPERATORS, ml_objects, ml_operators, source_operators  # noqa: E402

MIN_TEXT_WORDS = 40
MIN_CAPTION_WORDS = 5
# Size of each text-source stratum in the paper's 201-pair ML subset
# (Section III-B: 134 mentions, 32 mentions + page context, 35 page context).
ML_PAPER_STRATA = {"mentions": 134, "mentions+same_page_context": 32, "same_page_context": 35}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def words(text: str | None) -> int:
    return len((text or "").split())


# --------------------------------------------------------------------------- ML


def collect_ml(vba_root: Path) -> list[dict]:
    figures = vba_root / "figures"
    rows: list[dict] = []
    for fail_root in (figures / "ml_l2_fail", figures / "golden" / "ml_l2_fail"):
        for sidecar in sorted(fail_root.glob("*/*.json")):
            local = f"{sidecar.parent.name}/{sidecar.stem}"
            fail_png = sidecar.with_suffix(".png")
            orig_png = next(
                (p for p in (figures / "ml_orig" / f"{local}.png", figures / "golden" / "ml_orig" / f"{local}.png") if p.is_file()),
                None,
            )
            rows.append({"local": local, "sidecar": json.loads(sidecar.read_text(encoding="utf-8")),
                         "fail_png": fail_png if fail_png.is_file() else None, "orig_png": orig_png})
    return rows


def ml_filter_reason(row: dict) -> str | None:
    gold = row["sidecar"]["gold"]
    if not gold.get("is_corrupted"):
        return "not_marked_corrupted"
    if row["fail_png"] is None or row["orig_png"] is None:
        return "missing_image"
    if row["fail_png"].read_bytes() == row["orig_png"].read_bytes():
        return "marked_but_byte_identical"
    if words(row["sidecar"].get("text_block")) < MIN_TEXT_WORDS:
        return "text_block_under_40_words"
    if words(row["sidecar"].get("caption")) < MIN_CAPTION_WORDS:
        return "caption_under_5_words"
    return None


def approximate_paper_subset(kept: list[dict]) -> set[str]:
    """Deterministic stand-in for the paper's manual review (223 -> 201).

    The manual exclusion list is not available. Within each text-source stratum
    we keep the pairs with the longest source-text blocks (most grounding),
    which reproduces the paper's stratum sizes exactly.
    """
    by_source: dict[str, list[dict]] = collections.defaultdict(list)
    for row in kept:
        by_source[row["sidecar"]["text_block_source"]].append(row)
    selected: set[str] = set()
    for source, rows in by_source.items():
        quota = ML_PAPER_STRATA.get(source, len(rows))
        rows.sort(key=lambda r: (-words(r["sidecar"]["text_block"]), r["local"]))
        selected.update(r["local"] for r in rows[:quota])
    return selected


def ml_records(vba_root: Path, out: Path) -> tuple[list[dict], list[dict]]:
    rows = collect_ml(vba_root)
    candidates: list[dict] = []
    kept: list[dict] = []
    for row in rows:
        reason = ml_filter_reason(row)
        candidates.append({"local": row["local"], "filter": reason})
        if reason is None:
            kept.append(row)
    selected = approximate_paper_subset(kept)
    for item in candidates:
        if item["filter"] is None and item["local"] not in selected:
            item["filter"] = "approximate_manual_review"

    records: list[dict] = []
    for row in kept:
        if row["local"] not in selected:
            continue
        s = row["sidecar"]
        local = row["local"].replace("/", "__")
        description = "; ".join(s["gold"].get("lies") or [s["gold"].get("lie", "")])
        images = copy_pair(out, "ml", local, row["orig_png"].read_bytes(), row["fail_png"].read_bytes())
        records.append({
            "pair_id": f"ml/{local}",
            "subset": "ml",
            "caption": s["caption"],
            "text_block": s["text_block"],
            "text_block_source": s["text_block_source"],
            "paper": {"title": s.get("title"), "source_id": s.get("pdf_id"), "arxiv_id": s.get("arxiv_id"),
                      "figure": s.get("figure_id"), "page": s.get("page")},
            "topic": "machine_learning",
            "figure_type": None,
            "entities": None,
            "defect": {
                "description_ru": description,
                "source_labels": [],
                "operators": ml_operators(description),
                "objects": ml_objects(description),
                "gold_objects": s["gold"].get("objects", []),
            },
            "images": images,
            "images_available": True,
            "flags": {"out_of_region": False, "selection": "approximate_paper_201"},
            "in_paired_run": True,
        })
    return records, candidates


# --------------------------------------------------------------------------- BT


class FolderSource:
    """Read ``bench_l2_folders`` from either a zip archive or a directory."""

    def __init__(self, path: Path):
        self.path = path
        self.zip = zipfile.ZipFile(path) if path.suffix == ".zip" else None
        if self.zip:
            names = [n for n in self.zip.namelist() if not n.startswith("__MACOSX") and "/._" not in n]
            self.prefix = names[0].split("/")[0] + "/"
            self.names = set(names)

    def folders(self) -> list[str]:
        if self.zip:
            return sorted({n[len(self.prefix):].split("/")[0] for n in self.names
                           if n.startswith(self.prefix + "paper_") and n.count("/") >= 2})
        return sorted(p.name for p in self.path.iterdir() if p.is_dir() and p.name.startswith("paper_"))

    def read(self, folder: str, name: str) -> bytes | None:
        if self.zip:
            key = f"{self.prefix}{folder}/{name}"
            return self.zip.read(key) if key in self.names else None
        path = self.path / folder / name
        return path.read_bytes() if path.is_file() else None


def bt_records(source: FolderSource, out: Path) -> list[dict]:
    records: list[dict] = []
    for folder in source.folders():
        meta = json.loads(source.read(folder, "meta.json"))
        orig = source.read(folder, meta["image_orig"])
        fail = source.read(folder, meta["image_l2_fail"])
        if orig is None or fail is None:
            raise SystemExit(f"BT folder {folder} lacks an image")
        out_of_region = not meta.get("visual_diff_verified", True)
        labels = list(meta["corruption"]["type"])
        records.append({
            "pair_id": f"bt/{folder}",
            "subset": "bt",
            "caption": meta["caption"],
            "text_block": meta["text_block"],
            "text_block_source": None,
            "paper": {"title": meta.get("paper_title"), "source_id": meta.get("source_pdf"), "arxiv_id": None,
                      "figure": meta.get("figure"), "page": meta.get("page")},
            "topic": meta.get("topic_primary"),
            "figure_type": None,
            "entities": meta.get("entities"),
            "defect": {
                "description_ru": meta["corruption"].get("lie_ru"),
                "source_labels": labels,
                "operators": source_operators(labels),
                "objects": [],
                "gold_objects": [meta["corruption"].get("object")],
                "diff_fraction": meta["corruption"].get("diff_fraction"),
            },
            "images": copy_pair(out, "bt", folder, orig, fail),
            "images_available": True,
            "flags": {"out_of_region": out_of_region, "selection": "all"},
            # Out-of-region pairs are held out of the billed run (Section III-D).
            "in_paired_run": not out_of_region,
        })
    return records


# -------------------------------------------------------------------------- B75


def b75_records(b75_root: Path, bt_source: FolderSource, out: Path) -> list[dict]:
    records: list[dict] = []
    for line in (b75_root / "dataset.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        folder = b75_root / row["folder"]
        orig_path, fail_path = folder / row["image_orig"], folder / row["image_fail"]
        orig = orig_path.read_bytes() if orig_path.is_file() else None
        fail = fail_path.read_bytes() if fail_path.is_file() else None
        if (orig is None or fail is None) and row["id"].startswith("bt_"):
            bt_folder = row["id"][len("bt_"):]
            meta_raw = bt_source.read(bt_folder, "meta.json")
            if meta_raw:
                meta = json.loads(meta_raw)
                orig = bt_source.read(bt_folder, meta["image_orig"])
                fail = bt_source.read(bt_folder, meta["image_l2_fail"])
        available = orig is not None and fail is not None
        labels = list(row["corruption"].get("types") or [])
        records.append({
            "pair_id": f"b75/{row['id']}",
            "subset": "b75",
            "caption": row["caption"],
            "text_block": row["text_block"],
            "text_block_source": None,
            "paper": {"title": row.get("paper_title"), "source_id": row.get("source_pdf"), "arxiv_id": None,
                      "figure": row.get("figure"), "page": row.get("page")},
            "topic": row.get("topic"),
            "figure_type": row.get("figure_type"),
            "multi_panel": row.get("multi_panel"),
            "entities": row.get("entities"),
            "defect": {
                "description_ru": row["corruption"].get("note_ru"),
                "source_labels": labels,
                "operators": source_operators(labels),
                "objects": [],
                "gold_objects": [],
                "diff_fraction": row["corruption"].get("diff_fraction"),
            },
            "images": copy_pair(out, "b75", row["id"], orig, fail) if available else None,
            "images_available": available,
            "flags": {"out_of_region": False, "selection": "all", "source_corpus": row.get("corpus")},
            "in_paired_run": True,
        })
    return records


# ------------------------------------------------------------------------ utils


def copy_pair(out: Path, subset: str, local: str, orig: bytes, fail: bytes) -> dict:
    directory = out / "pairs" / subset / local
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "orig.png").write_bytes(orig)
    (directory / "fail.png").write_bytes(fail)
    rel = f"pairs/{subset}/{local}"
    return {"orig": f"{rel}/orig.png", "fail": f"{rel}/fail.png",
            "orig_sha256": sha256_bytes(orig), "fail_sha256": sha256_bytes(fail)}


def balanced_sample(records: list[dict], n: int = 100, seed: int = 42) -> list[str]:
    """Operator-balanced sample: round-robin over the ten operator tags.

    Each pair is drawn under its first operator tag; pools are shuffled with a
    fixed seed and exhausted operators are skipped.
    """
    rng = random.Random(seed)
    pools: dict[str, list[str]] = {op: [] for op in OPERATORS}
    for record in sorted(records, key=lambda r: r["pair_id"]):
        pools[record["defect"]["operators"][0]].append(record["pair_id"])
    for pool in pools.values():
        rng.shuffle(pool)
    chosen: list[str] = []
    while len(chosen) < n and any(pools.values()):
        for op in OPERATORS:
            if pools[op] and len(chosen) < n:
                chosen.append(pools[op].pop())
    return sorted(chosen)


def write_lines(path: Path, items: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{item}\n" for item in items), encoding="utf-8")


def summary(records: list[dict], candidates: list[dict]) -> dict:
    out: dict = {"pairs": collections.Counter(r["subset"] for r in records)}
    out["paired_run"] = collections.Counter(r["subset"] for r in records if r["in_paired_run"] and r["images_available"])
    out["images_available"] = collections.Counter(r["subset"] for r in records if r["images_available"])
    out["ml_candidate_filters"] = collections.Counter(c["filter"] or "selected" for c in candidates)
    for subset in ("ml", "bt", "b75"):
        rows = [r for r in records if r["subset"] == subset]
        out[f"{subset}_operators"] = collections.Counter(op for r in rows for op in r["defect"]["operators"])
        out[f"{subset}_source_labels"] = collections.Counter(l for r in rows for l in r["defect"]["source_labels"])
        out[f"{subset}_topics"] = collections.Counter(r["topic"] for r in rows)
    ml = [r for r in records if r["subset"] == "ml"]
    out["ml_objects"] = collections.Counter(o for r in ml for o in r["defect"]["objects"])
    out["ml_text_block_source"] = collections.Counter(r["text_block_source"] for r in ml)
    b75 = [r for r in records if r["subset"] == "b75"]
    out["b75_figure_types"] = collections.Counter(r["figure_type"] for r in b75)
    out["b75_multipanel"] = sum(1 for r in b75 if r.get("multi_panel"))
    out["b75_mean_entities"] = round(sum(len(r["entities"] or []) for r in b75) / max(1, len(b75)), 2)
    return {k: (dict(sorted(v.items(), key=lambda kv: (-kv[1], str(kv[0])))) if isinstance(v, collections.Counter) else v)
            for k, v in out.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--vba-root", type=Path, required=True, help="local copy of the verification-before-assembly dataset")
    parser.add_argument("--bt-source", type=Path, required=True, help="bench_l2_folders.zip or extracted directory")
    parser.add_argument("--b75-root", type=Path, required=True, help="bench_final directory")
    parser.add_argument("--out", type=Path, default=Path("data"))
    parser.add_argument("--clean", action="store_true", help="remove <out>/pairs before building")
    args = parser.parse_args()

    if args.clean and (args.out / "pairs").exists():
        shutil.rmtree(args.out / "pairs")
    bt_source = FolderSource(args.bt_source)
    ml, candidates = ml_records(args.vba_root, args.out)
    bt = bt_records(bt_source, args.out)
    b75 = b75_records(args.b75_root, bt_source, args.out)
    records = ml + bt + b75

    meta_dir = args.out / "metadata"
    meta_dir.mkdir(parents=True, exist_ok=True)
    with (meta_dir / "pairs.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    with (meta_dir / "ml_candidates.jsonl").open("w", encoding="utf-8") as handle:
        for item in sorted(candidates, key=lambda c: c["local"]):
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    splits = args.out / "splits"
    write_lines(splits / "ml.txt", [r["pair_id"] for r in ml])
    write_lines(splits / "bt.txt", [r["pair_id"] for r in bt])
    write_lines(splits / "bt_run.txt", [r["pair_id"] for r in bt if r["in_paired_run"]])
    write_lines(splits / "b75.txt", [r["pair_id"] for r in b75])
    write_lines(splits / "b75_images.txt", [r["pair_id"] for r in b75 if r["images_available"]])
    write_lines(splits / "balanced100.txt", balanced_sample(ml))

    stats = summary(records, candidates)
    (meta_dir / "summary.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: stats[k] for k in ("pairs", "paired_run", "images_available", "ml_candidate_filters")}, indent=1))


if __name__ == "__main__":
    main()
