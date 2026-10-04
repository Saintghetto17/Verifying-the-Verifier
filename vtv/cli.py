"""Command line: ``python -m vtv <command>``."""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import DEFAULT_DATA_ROOT, DEFAULT_MODEL, DEFAULT_RUNS_ROOT, HF_DATASET, PROJECT_ROOT, RunConfig
from .data import DatasetError, load_pairs, load_records, select


def _path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (Path.cwd() / path).resolve()


def _config(args: argparse.Namespace) -> RunConfig:
    return RunConfig(model=args.model, temperature=args.temperature, top_p=args.top_p, seed=args.seed,
                     max_tokens=args.max_tokens, reasoning_effort=args.reasoning_effort, workers=args.workers,
                     max_cost_usd=args.max_cost_usd)


def _selection(args: argparse.Namespace):
    data_root = _path(args.data_root)
    pairs = load_pairs(data_root, check_files=False)
    return select(pairs, data_root=data_root, subsets=args.subset, split=args.split, ids=args.ids,
                  offset=args.offset, limit=args.limit, shuffle=args.shuffle, seed=args.seed)


# ------------------------------------------------------------------- commands


def cmd_download(args: argparse.Namespace) -> int:
    from huggingface_hub import snapshot_download

    target = _path(args.data_root)
    snapshot_download(repo_id=args.repo, repo_type="dataset", local_dir=str(target),
                      allow_patterns=None if args.with_images else ["metadata/*", "splits/*", "README.md"])
    print(f"Dataset installed in {target}")
    return cmd_validate(args)


def cmd_validate(args: argparse.Namespace) -> int:
    data_root = _path(args.data_root)
    records = load_records(data_root)
    by_subset: dict[str, list] = {}
    for record in records:
        by_subset.setdefault(record["subset"], []).append(record)
    missing_files = 0
    for record in records:
        images = record.get("images")
        if images and not all((data_root / images[s]).is_file() for s in ("orig", "fail")):
            missing_files += 1
    for subset, rows in by_subset.items():
        print(f"{subset:>4}: {len(rows):3d} pairs, {sum(r['images_available'] for r in rows):3d} with released images, "
              f"{sum(r['in_paired_run'] and r['images_available'] for r in rows):3d} in the paired run")
    print(f"total: {len(records)} pairs; image files missing locally for {missing_files} released pairs")
    return 0


def cmd_prompts(_args: argparse.Namespace) -> int:
    from .prompts import load_registry

    registry = load_registry()
    aliases = {v: k for k, v in registry["aliases"].items() if k in ("tg", "hd")}
    for version, meta in registry["versions"].items():
        tag = f" [{aliases[version].upper()}]" if version in aliases else ""
        print(f"{version}{tag:6} {meta['family']:<18} {meta['mechanism']}")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    from .prompts import load_prompt, preview

    pair = _selection(args)[0]
    print(preview(load_prompt(args.prompt), pair, args.side))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from .artifacts import RunStore
    from .openrouter import OpenRouterClient
    from .prompts import load_prompt
    from .runner import Runner

    pairs = _selection(args)
    if not pairs:
        raise DatasetError("the selection is empty")
    config = _config(args)
    prompt = load_prompt(args.prompt)
    store = RunStore.create(pairs, prompt, config, runs_root=_path(args.runs_root), name=args.name)
    client = None if args.dry_run else OpenRouterClient(config)
    print(f"Run {store.run_dir.name}: {len(pairs)} pairs, prompt {prompt.version}, model {config.model}")
    Runner(config, prompt, client).run(store, pairs, dry_run=args.dry_run)
    print(f"Run directory: {store.run_dir}")
    print(json.dumps(store.read_run()["summary"]))
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    from .artifacts import RunStore
    from .openrouter import OpenRouterClient
    from .prompts import load_prompt
    from .runner import Runner

    store = RunStore.open(_path(args.run_dir))
    manifest = store.read_run()
    config = RunConfig.from_dict(manifest["config"])
    if args.workers:
        config = RunConfig.from_dict({**config.as_dict(), "workers": args.workers})
    prompt = load_prompt(str(store.run_dir / manifest["prompt"]["file"]))
    if prompt.sha256 != manifest["prompt"]["sha256"]:
        raise ValueError("the stored prompt copy does not match its recorded hash")
    prompt = type(prompt)(manifest["prompt"]["version"], prompt.path, prompt.source, prompt.sha256,
                          {**prompt.meta, "hypotheses": manifest["prompt"].get("hypotheses", 0)})
    data_root = _path(args.data_root)
    pairs = select(load_pairs(data_root, check_files=False), data_root=data_root, ids=manifest["pair_ids"])
    Runner(config, prompt, OpenRouterClient(config)).run(store, pairs)
    print(json.dumps(store.read_run()["summary"]))
    return 0


def cmd_screen(args: argparse.Namespace) -> int:
    """Reference-only screen: fraction of references scored at F = 5 (Section VI)."""
    from .artifacts import RunStore
    from .openrouter import OpenRouterClient
    from .prompts import load_prompt
    from .runner import Runner

    pairs = _selection(args)
    config = _config(args)
    prompt = load_prompt(args.prompt)
    store = RunStore.create(pairs, prompt, config, runs_root=_path(args.runs_root),
                            name=args.name or f"screen__{config.model}")
    runner = Runner(config, prompt, OpenRouterClient(config))
    with ThreadPoolExecutor(max_workers=max(1, config.workers)) as pool:
        results = list(pool.map(lambda p: runner._side(store, p, "orig", False), pairs))
    scored = [r["computed"]["scores"]["faithfulness"] for r in results if r.get("status") == "success"]
    share = sum(f == 5 for f in scored) / len(scored) if scored else 0.0
    verdict = "accept" if scored and share >= args.threshold else "reject"
    print(f"{config.model}: {len(scored)}/{len(pairs)} valid ledgers, references at F=5: {100 * share:.0f}% "
          f"(threshold {100 * args.threshold:.0f}%) -> {verdict}")
    store.refresh_summary(status="screen")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from .report import pair_report

    print(pair_report([str(_path(p)) for p in args.tg], [str(_path(p)) for p in args.hd], str(_path(args.data_root))))
    return 0


def cmd_tables(args: argparse.Namespace) -> int:
    from .report import write_report

    path = write_report(_path(args.experiments), _path(args.out))
    print(path.read_text(encoding="utf-8"))
    print(f"Written: {path} and {path.with_name('results.json')}")
    return 0


def cmd_viewer(args: argparse.Namespace) -> int:
    from .viewer import serve

    serve(port=args.port, runs_root=_path(args.runs_root), data_root=_path(args.data_root))
    return 0


# --------------------------------------------------------------------- parser


def _selection_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    p.add_argument("--subset", action="append", default=[], choices=["ml", "bt", "b75"],
                   help="subset(s) to run; uses the paired-run split of each")
    p.add_argument("--split", help="split name under data/splits (e.g. balanced100) or a path to an id file")
    p.add_argument("--id", dest="ids", action="append", default=[], help="pair id, repeatable")
    p.add_argument("--limit", type=int)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--shuffle", action="store_true")
    p.add_argument("--seed", type=int, default=42)


def _model_args(p: argparse.ArgumentParser, prompt_default: str = "tg") -> None:
    p.add_argument("--prompt", default=prompt_default, help="version (v01..v13), alias (tg, hd, ...) or a .md path")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--top-p", type=float, default=1.0)
    p.add_argument("--max-tokens", type=int, default=16384)
    p.add_argument("--reasoning-effort", default="medium")
    p.add_argument("--workers", type=int, default=10, help="pairs processed in parallel")
    p.add_argument("--max-cost-usd", type=float)
    p.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT))
    p.add_argument("--name", help="human-readable run name")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m vtv", description="Verifying the Verifier benchmark")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("download", help="download the benchmark from Hugging Face into data/")
    p.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    p.add_argument("--repo", default=HF_DATASET)
    p.add_argument("--metadata-only", dest="with_images", action="store_false")
    p.set_defaults(handler=cmd_download)

    p = sub.add_parser("validate", help="check the local dataset")
    p.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    p.set_defaults(handler=cmd_validate)

    sub.add_parser("prompts", help="list prompt versions").set_defaults(handler=cmd_prompts)

    p = sub.add_parser("render", help="print a rendered prompt without calling the model")
    _selection_args(p)
    p.add_argument("--prompt", default="tg")
    p.add_argument("--side", choices=["orig", "fail"], default="orig")
    p.set_defaults(handler=cmd_render)

    p = sub.add_parser("run", help="blind paired run of one prompt configuration")
    _selection_args(p)
    _model_args(p)
    p.add_argument("--dry-run", action="store_true", help="write artifacts without network calls")
    p.set_defaults(handler=cmd_run)

    p = sub.add_parser("resume", help="continue an interrupted run; successful calls are kept")
    p.add_argument("run_dir")
    p.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    p.add_argument("--workers", type=int)
    p.set_defaults(handler=cmd_resume)

    p = sub.add_parser("screen", help="reference-only screen of a candidate verifier model")
    _selection_args(p)
    _model_args(p)
    p.add_argument("--threshold", type=float, default=0.70)
    p.set_defaults(handler=cmd_screen)

    p = sub.add_parser("report", help="paired analysis of one TG and one HD configuration")
    p.add_argument("--tg", nargs="+", required=True, help="TG run directories (one per subset is fine)")
    p.add_argument("--hd", nargs="+", required=True, help="HD run directories")
    p.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    p.set_defaults(handler=cmd_report)

    p = sub.add_parser("tables", help="recreate the paper's tables from an experiments file")
    p.add_argument("--experiments", default="experiments/paper.json")
    p.add_argument("--out", default="reports")
    p.set_defaults(handler=cmd_tables)

    p = sub.add_parser("viewer", help="local read-only HTML viewer for runs")
    p.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT))
    p.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    p.add_argument("--port", type=int, default=8080)
    p.set_defaults(handler=cmd_viewer)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (DatasetError, FileNotFoundError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


__all__ = ["main", "PROJECT_ROOT"]
