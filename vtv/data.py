"""Loading benchmark pairs from the released metadata."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .config import DEFAULT_DATA_ROOT

SUBSETS = ("ml", "bt", "b75")


class DatasetError(ValueError):
    """The local data does not match the release contract."""


@dataclass(frozen=True)
class Pair:
    pair_id: str
    subset: str
    caption: str
    text_block: str
    orig_image: Path | None
    fail_image: Path | None
    record: dict[str, Any] = field(repr=False, compare=False)

    @property
    def images_available(self) -> bool:
        return self.orig_image is not None and self.fail_image is not None

    @property
    def operators(self) -> list[str]:
        return list(self.record["defect"]["operators"])

    def image(self, side: str) -> Path:
        path = {"orig": self.orig_image, "fail": self.fail_image}[side]
        if path is None:
            raise DatasetError(f"{self.pair_id}: images are not released yet")
        return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_records(data_root: Path = DEFAULT_DATA_ROOT) -> list[dict[str, Any]]:
    path = data_root / "metadata" / "pairs.jsonl"
    if not path.is_file():
        raise DatasetError(f"{path} not found; run `python -m vtv download` first")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_pairs(data_root: Path = DEFAULT_DATA_ROOT, *, check_files: bool = True) -> list[Pair]:
    pairs = []
    for record in load_records(data_root):
        images = record.get("images") or {}
        orig = data_root / images["orig"] if images else None
        fail = data_root / images["fail"] if images else None
        if check_files and images and not (orig.is_file() and fail.is_file()):
            raise DatasetError(f"{record['pair_id']}: image files are missing under {data_root}")
        pairs.append(Pair(record["pair_id"], record["subset"], record["caption"], record["text_block"],
                          orig, fail, record))
    if len({p.pair_id for p in pairs}) != len(pairs):
        raise DatasetError("duplicate pair ids in metadata")
    return pairs


def read_split(data_root: Path, name: str) -> list[str]:
    path = Path(name)
    if not path.is_file():
        path = data_root / "splits" / f"{name}.txt"
    if not path.is_file():
        raise DatasetError(f"unknown split {name!r} (looked for {path})")
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def default_split(subset: str) -> str:
    """The pairs that enter a billed paired run for each subset."""
    return {"ml": "ml", "bt": "bt_run", "b75": "b75_images"}[subset]


def select(pairs: Iterable[Pair], *, data_root: Path = DEFAULT_DATA_ROOT, subsets: Iterable[str] = (),
           split: str | None = None, ids: Iterable[str] = (), offset: int = 0, limit: int | None = None,
           shuffle: bool = False, seed: int = 42) -> list[Pair]:
    """Choose pairs before any network call. Explicit ids keep their order."""
    by_id = {p.pair_id: p for p in pairs}
    wanted = list(ids)
    if split:
        wanted.extend(read_split(data_root, split))
    for subset in subsets:
        if subset not in SUBSETS:
            raise DatasetError(f"unknown subset {subset!r}")
        wanted.extend(read_split(data_root, default_split(subset)))
    if not wanted:
        wanted = [pid for subset in SUBSETS for pid in read_split(data_root, default_split(subset))]
    selected, seen = [], set()
    for pid in wanted:
        if pid not in by_id:
            raise DatasetError(f"unknown pair id: {pid}")
        if pid not in seen:
            seen.add(pid)
            selected.append(by_id[pid])
    missing = [p.pair_id for p in selected if not p.images_available]
    if missing:
        raise DatasetError(f"{len(missing)} selected pairs have no released images yet (e.g. {missing[0]})")
    if shuffle:
        random.Random(seed).shuffle(selected)
    if offset < 0 or (limit is not None and limit < 1):
        raise DatasetError("offset must be >= 0 and limit >= 1")
    selected = selected[offset:]
    return selected if limit is None else selected[:limit]
