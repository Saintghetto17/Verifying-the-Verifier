"""Validation of the structured evidence ledger returned by the verifier.

Every prompt configuration returns the same ledger format; only the way the
evidence is searched for differs. Code then applies one scoring rule to all of
them, which is what makes configurations comparable.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .config import RunConfig
from .scoring import VALID_AXIS_SCORES, EvidenceCounts, faithfulness, overall

REQUIREMENT_STATUSES = {"confirmed", "missing"}
RELATION_STATUSES = {"correct", "missing", "wrong_direction"}
LABEL_STATUSES = {"match", "mismatch"}
HYPOTHESIS_VERDICTS = {"trace_found", "no_trace", "not_testable"}
AXES = ("clarity", "compactness", "style")


class LedgerError(ValueError):
    """The response cannot be used for scoring and should be retried."""


def _load_json(content: str) -> dict[str, Any]:
    text = content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.S)
    if fenced:
        text = fenced.group(1)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise LedgerError(f"response is not JSON: {error.msg}") from error
    if not isinstance(payload, dict):
        raise LedgerError("the root JSON value must be an object")
    return payload


def _list(payload: dict[str, Any], key: str, required: bool = True) -> list[dict[str, Any]]:
    value = payload.get(key, None if required else [])
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise LedgerError(f"'{key}' must be a list of objects")
    return value


def _status(items: list[dict[str, Any]], key: str, allowed: set[str], field: str = "status") -> list[str]:
    statuses = []
    for item in items:
        status = str(item.get(field, "")).strip().lower()
        if status not in allowed:
            raise LedgerError(f"'{key}' item has {field}={item.get(field)!r}; allowed: {sorted(allowed)}")
        statuses.append(status)
    return statuses


def parse_ledger(content: str, config: RunConfig, *, require_hypotheses: int = 0) -> dict[str, Any]:
    """Validate one response and compute its scores.

    Returns the parsed ledger together with the authoritative counts and the
    code-computed Faithfulness and Overall. Raises ``LedgerError`` when the
    response must be retried.
    """
    payload = _load_json(content)
    requirements = _list(payload, "requirements")
    unsupported = _list(payload, "unsupported")
    relations = _list(payload, "relations", required=False)
    labels = _list(payload, "label_bindings", required=False)
    hypotheses = _list(payload, "hypotheses", required=bool(require_hypotheses))

    if len(requirements) < config.min_requirements:
        raise LedgerError(f"at least {config.min_requirements} requirements are needed, got {len(requirements)}")
    for item in requirements:
        if not str(item.get("requirement", "")).strip() or not str(item.get("text_evidence", "")).strip():
            raise LedgerError("every requirement needs 'requirement' and 'text_evidence'")
    req_status = _status(requirements, "requirements", REQUIREMENT_STATUSES)
    rel_status = _status(relations, "relations", RELATION_STATUSES)
    lab_status = _status(labels, "label_bindings", LABEL_STATUSES)
    if require_hypotheses:
        if len(hypotheses) != require_hypotheses:
            raise LedgerError(f"exactly {require_hypotheses} hypotheses are expected, got {len(hypotheses)}")
        _status(hypotheses, "hypotheses", HYPOTHESIS_VERDICTS, field="verdict")

    axes = payload.get("axes")
    if not isinstance(axes, dict) or any(axes.get(name) not in VALID_AXIS_SCORES for name in AXES):
        raise LedgerError("'axes' must give clarity, compactness and style in {1, 3, 5}")
    audit = payload.get("audit")
    if not isinstance(audit, dict):
        raise LedgerError("'audit' must be an object")

    counts = EvidenceCounts(
        P=req_status.count("confirmed"),
        M=req_status.count("missing"),
        U=len(unsupported),
        R_bad=sum(status != "correct" for status in rel_status),
        L_bad=lab_status.count("mismatch"),
    )
    f = faithfulness(counts, config.tau_min, config.tau_max)
    weights = (config.weight_faithfulness, config.weight_clarity, config.weight_compactness, config.weight_style)
    scores = {
        "faithfulness": f,
        "clarity": axes["clarity"],
        "compactness": axes["compactness"],
        "style": axes["style"],
    }
    scores["overall"] = overall(f, axes["clarity"], axes["compactness"], axes["style"], weights)

    warnings: list[str] = []
    if "faithfulness" in axes or "faithfulness" in payload.get("scores", {}):
        warnings.append("model reported a faithfulness value; it is ignored")
    if require_hypotheses:
        found = [h for h in hypotheses if str(h.get("verdict", "")).lower() == "trace_found"]
        if found and counts.defects() == 0 and counts.M == 0:
            warnings.append("a hypothesis reports a trace but the ledger records no defect")

    return {
        "status": "success",
        "ledger": payload,
        "computed": {"counts": counts.as_dict(), "scores": scores},
        "validation_warnings": warnings,
    }
