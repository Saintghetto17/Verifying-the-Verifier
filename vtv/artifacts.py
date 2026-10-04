"""Self-contained, atomically written run directories.

::

    runs/<timestamp>__<name>/
      run.json                  config, prompt identity, selected pairs, summary
      prompt/<file>.md          verbatim copy of the prompt used
      samples.jsonl             one flat line per pair (scores, counts, status, cost)
      samples/<pair_dir>/
        pair.json               inputs + defect record (the defect is never sent to the model)
        orig/ fail/
          request.json          request without base64 image
          response.attempt_NN.json
          result.json           validated ledger, counts, computed scores
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DEFAULT_RUNS_ROOT, RunConfig
from .data import Pair
from .prompts import Prompt

SIDES = ("orig", "fail")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n"
    handle, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as target:
            target.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def pair_dirname(pair_id: str) -> str:
    return pair_id.replace("/", "__")


def _slug(value: str) -> str:
    return re.sub(r"[^\w.-]+", "_", value).strip("_") or "run"


class RunStore:
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir.resolve()
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- creation

    @classmethod
    def create(cls, pairs: list[Pair], prompt: Prompt, config: RunConfig, *,
               runs_root: Path = DEFAULT_RUNS_ROOT, name: str | None = None) -> "RunStore":
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        label = name or f"{prompt.version}__{config.model}"
        run_dir = runs_root.resolve() / f"{stamp}__{_slug(label)}"
        suffix = 1
        while run_dir.exists():
            suffix += 1
            run_dir = runs_root.resolve() / f"{stamp}__{_slug(label)}_{suffix}"
        (run_dir / "prompt").mkdir(parents=True)
        shutil.copy2(prompt.path, run_dir / "prompt" / prompt.path.name)
        store = cls(run_dir)
        atomic_write_json(store.run_path, {
            "run_id": run_dir.name,
            "display_name": name or label,
            "status": "running",
            "created_at": now(),
            "updated_at": now(),
            "protocol": config.protocol,
            "config": config.as_dict(),
            "prompt": {"version": prompt.version, "file": f"prompt/{prompt.path.name}", "sha256": prompt.sha256,
                       "mechanism": prompt.meta.get("mechanism"), "family": prompt.meta.get("family"),
                       "hypotheses": prompt.hypotheses},
            "pair_ids": [p.pair_id for p in pairs],
            "summary": {},
        })
        store.index_path.touch()
        for pair in pairs:
            store.write_pair(pair)
        store.refresh_summary()
        return store

    @classmethod
    def open(cls, run_dir: Path) -> "RunStore":
        store = cls(run_dir)
        if not store.run_path.is_file():
            raise FileNotFoundError(f"no run.json in {run_dir}")
        return store

    # ------------------------------------------------------------------- paths

    @property
    def run_path(self) -> Path:
        return self.run_dir / "run.json"

    @property
    def index_path(self) -> Path:
        return self.run_dir / "samples.jsonl"

    def pair_dir(self, pair_id: str) -> Path:
        return self.run_dir / "samples" / pair_dirname(pair_id)

    def side_dir(self, pair_id: str, side: str) -> Path:
        if side not in SIDES:
            raise ValueError(f"unknown side {side!r}")
        return self.pair_dir(pair_id) / side

    # ------------------------------------------------------------------ I/O

    def read_run(self) -> dict[str, Any]:
        return read_json(self.run_path)

    def write_pair(self, pair: Pair) -> None:
        record = pair.record
        atomic_write_json(self.pair_dir(pair.pair_id) / "pair.json", {
            "pair_id": pair.pair_id,
            "subset": pair.subset,
            "caption": pair.caption,
            "text_block": pair.text_block,
            "images": record.get("images"),
            "paper": record.get("paper"),
            "topic": record.get("topic"),
            "figure_type": record.get("figure_type"),
            "defect": record.get("defect"),
        })

    def read_result(self, pair_id: str, side: str) -> dict[str, Any] | None:
        path = self.side_dir(pair_id, side) / "result.json"
        return read_json(path) if path.is_file() else None

    def write_attempt(self, pair_id: str, side: str, attempt: int, raw: dict[str, Any]) -> None:
        atomic_write_json(self.side_dir(pair_id, side) / f"response.attempt_{attempt:02d}.json", raw)

    def write_call(self, pair_id: str, side: str, request: dict[str, Any], result: dict[str, Any]) -> None:
        atomic_write_json(self.side_dir(pair_id, side) / "request.json", request)
        atomic_write_json(self.side_dir(pair_id, side) / "result.json", result)

    def index_records(self) -> list[dict[str, Any]]:
        if not self.index_path.is_file():
            return []
        return [json.loads(line) for line in self.index_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def upsert_index(self, record: dict[str, Any]) -> None:
        with self._lock:
            records = {r["pair_id"]: r for r in self.index_records()}
            records[record["pair_id"]] = record
            order = self.read_run()["pair_ids"]
            lines = [json.dumps(records[pid], ensure_ascii=False, sort_keys=True) for pid in order if pid in records]
            tmp = self.index_path.with_suffix(".jsonl.tmp")
            tmp.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
            os.replace(tmp, self.index_path)
            self._refresh_summary_locked()

    def refresh_summary(self, status: str | None = None) -> dict[str, Any]:
        with self._lock:
            return self._refresh_summary_locked(status)

    def _refresh_summary_locked(self, status: str | None = None) -> dict[str, Any]:
        manifest = self.read_run()
        summary = {"pairs": len(manifest["pair_ids"]), "complete": 0, "partial": 0, "failed": 0,
                   "cost_usd": 0.0, "calls": 0}
        for record in self.index_records():
            if record.get("status") in ("complete", "partial", "failed"):
                summary[record["status"]] += 1
            for side in SIDES:
                item = record.get(side) or {}
                if item.get("status"):
                    summary["calls"] += 1
                    summary["cost_usd"] += float(item.get("cost_usd") or 0.0)
        summary["cost_usd"] = round(summary["cost_usd"], 6)
        manifest["summary"] = summary
        manifest["updated_at"] = now()
        if status:
            manifest["status"] = status
        atomic_write_json(self.run_path, manifest)
        return manifest

    def total_cost(self) -> float:
        return float(self.read_run().get("summary", {}).get("cost_usd") or 0.0)
