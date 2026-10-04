"""Shared fixtures: a tiny synthetic release and a fake verifier client."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vtv.openrouter import NetworkResult  # noqa: E402

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
       b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


def make_record(pair_id: str, subset: str, operators: list[str], images: bool = True) -> dict:
    return {
        "pair_id": pair_id, "subset": subset, "caption": f"Caption of {pair_id}", "text_block": "Encoder feeds decoder.",
        "text_block_source": "mentions", "paper": {"title": "T", "figure": "figure 1"}, "topic": "topic_a",
        "figure_type": "flow", "entities": ["Encoder", "Decoder", "Head"],
        "defect": {"description_ru": "", "source_labels": [], "operators": operators, "objects": []},
        "images": ({"orig": f"pairs/{pair_id}/orig.png", "fail": f"pairs/{pair_id}/fail.png"} if images else None),
        "images_available": images, "flags": {}, "in_paired_run": True,
    }


@pytest.fixture()
def data_root(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    records = [make_record(f"ml/doc_{i}__figure_1", "ml", ["block_permutation" if i % 2 else "element_deletion"])
               for i in range(6)]
    records += [make_record(f"bt/paper_{i}_figure_1", "bt", ["label_text_edit"]) for i in range(4)]
    records += [make_record("b75/paper_9_figure_1", "b75", ["element_deletion"], images=False)]
    for record in records:
        if record["images"]:
            for side in ("orig", "fail"):
                path = root / record["images"][side]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(PNG + side.encode())
    (root / "metadata").mkdir(parents=True)
    (root / "metadata" / "pairs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    splits = root / "splits"
    splits.mkdir()
    (splits / "ml.txt").write_text("".join(r["pair_id"] + "\n" for r in records if r["subset"] == "ml"))
    (splits / "bt_run.txt").write_text("".join(r["pair_id"] + "\n" for r in records if r["subset"] == "bt"))
    (splits / "b75_images.txt").write_text("")
    (splits / "balanced100.txt").write_text("".join(r["pair_id"] + "\n" for r in records[:4]))
    return root


def ledger(confirmed: int = 4, missing: int = 0, unsupported: int = 0, hypotheses: int = 0, bad_relations: int = 0) -> str:
    payload = {
        "requirements": [{"id": f"R{i}", "type": "entity", "requirement": f"r{i}", "text_evidence": "q",
                          "status": "confirmed" if i < confirmed else "missing", "visual_evidence": "v"}
                         for i in range(confirmed + missing)],
        "unsupported": [{"element": f"u{i}", "visual_evidence": "v", "reason": "r"} for i in range(unsupported)],
        "relations": [{"source": "a", "target": "b", "relation": "feeds", "text_evidence": "q",
                       "status": "wrong_direction", "visual_evidence": "v"} for _ in range(bad_relations)],
        "label_bindings": [],
        "axes": {"clarity": 5, "compactness": 3, "style": 5},
        "audit": {"faithfulness": "x", "clarity": "x", "compactness": "x", "style": "x"},
    }
    if hypotheses:
        payload["hypotheses"] = [{"id": f"H{i + 1}", "name": "h", "verdict": "no_trace", "evidence": ""} for i in range(hypotheses)]
    return json.dumps(payload)


class FakeClient:
    """Answers by looking at the image bytes: references are clean, corrupted figures get one accusation."""

    def __init__(self, hypotheses: int = 0, invalid_first: bool = False, fail_unsupported: int = 1):
        self.hypotheses = hypotheses
        self.invalid_first = invalid_first
        self.fail_unsupported = fail_unsupported
        self.calls = 0

    def independent(self) -> "FakeClient":
        return self

    def evaluate(self, messages: list[dict]) -> NetworkResult:
        self.calls += 1
        image = next(p for p in messages[1]["content"] if p["type"] == "image_url")["image_url"]["url"]
        import base64

        is_fail = base64.b64decode(image.split(",", 1)[1]).endswith(b"fail")
        if self.invalid_first and self.calls == 1:
            content = "not json"
        else:
            content = ledger(unsupported=self.fail_unsupported if is_fail else 0, hypotheses=self.hypotheses)
        return NetworkResult(True, {"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                                    "usage": {"cost": 0.001}, "model": "fake"})
