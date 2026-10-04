"""Blind paired runner.

For every pair the reference (``orig``) and the corrupted figure (``fail``) are
scored by two independent requests with identical text inputs. Neither request
sees the other image, the defect record, or which side it is evaluating.
Pairs are processed ``config.workers`` at a time.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol

from .artifacts import SIDES, RunStore, now
from .config import RunConfig
from .data import Pair
from .ledger import LedgerError, parse_ledger
from .openrouter import NetworkResult, OpenRouterError, extract_message, response_cost
from .prompts import Prompt, build_messages, safe_messages
from .scoring import outcome

FAILED = {"network_error", "invalid_response", "budget_exhausted"}


class Client(Protocol):
    def evaluate(self, messages: list[dict[str, Any]]) -> NetworkResult: ...


class Runner:
    def __init__(self, config: RunConfig, prompt: Prompt, client: Any | None = None):
        self.config = config
        self.prompt = prompt
        self.client = client

    def _client(self) -> Any:
        independent = getattr(self.client, "independent", None)
        return independent() if callable(independent) else self.client

    def _side(self, store: RunStore, pair: Pair, side: str, dry_run: bool) -> dict[str, Any]:
        previous = store.read_result(pair.pair_id, side)
        if previous and previous.get("status") == "success":
            return previous
        request = {"created_at": now(), "model": self.config.model, "prompt_version": self.prompt.version,
                   "parameters": self.config.as_dict(), "messages": safe_messages(self.prompt, pair, side)}
        if dry_run:
            result = {"status": "dry_run", "computed": None, "cost_usd": 0.0}
            store.write_call(pair.pair_id, side, request, result)
            return result
        if self.config.max_cost_usd is not None and store.total_cost() >= self.config.max_cost_usd:
            result = {"status": "budget_exhausted", "computed": None, "cost_usd": 0.0}
            store.write_call(pair.pair_id, side, request, result)
            return result
        client = self._client()
        if client is None:
            raise RuntimeError("a live run needs an OpenRouter client")

        messages = build_messages(self.prompt, pair, side)
        errors: list[str] = []
        cost = 0.0
        for attempt in range(1, self.config.invalid_response_attempts + 1):
            network = client.evaluate(messages)
            cost += response_cost(network.raw)
            store.write_attempt(pair.pair_id, side, attempt, network.raw)
            if not network.ok:
                result = {"status": "network_error", "error": network.error, "validation_errors": errors,
                          "computed": None, "cost_usd": cost, "attempts": attempt}
                store.write_call(pair.pair_id, side, request, result)
                return result
            try:
                content, reasoning, metadata = extract_message(network.raw)
                parsed = parse_ledger(content, self.config, require_hypotheses=self.prompt.hypotheses)
            except (OpenRouterError, LedgerError) as error:
                errors.append(str(error))
                continue
            result = {**parsed, "provider_reasoning": reasoning, "provider_metadata": metadata,
                      "validation_errors": errors, "cost_usd": cost, "attempts": attempt}
            store.write_call(pair.pair_id, side, request, result)
            return result
        result = {"status": "invalid_response", "validation_errors": errors, "computed": None,
                  "cost_usd": cost, "attempts": self.config.invalid_response_attempts}
        store.write_call(pair.pair_id, side, request, result)
        return result

    @staticmethod
    def index_record(pair: Pair, results: dict[str, dict[str, Any]]) -> dict[str, Any]:
        def side(value: dict[str, Any]) -> dict[str, Any]:
            computed = value.get("computed") or {}
            return {"status": value.get("status"), "counts": computed.get("counts"),
                    "scores": computed.get("scores"), "cost_usd": value.get("cost_usd", 0.0)}

        orig, fail = results["orig"], results["fail"]
        if orig.get("status") == "success" and fail.get("status") == "success":
            o, f = orig["computed"]["scores"], fail["computed"]["scores"]
            comparison = {axis: outcome(o[axis], f[axis]) for axis in o}
            status = "complete"
        elif orig.get("status") == fail.get("status") == "dry_run":
            comparison, status = None, "dry_run"
        else:
            comparison = None
            status = "failed" if orig.get("status") in FAILED and fail.get("status") in FAILED else "partial"
        return {"pair_id": pair.pair_id, "subset": pair.subset, "status": status,
                "orig": side(orig), "fail": side(fail), "comparison": comparison}

    def run_pair(self, store: RunStore, pair: Pair, dry_run: bool) -> dict[str, Any]:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {s: executor.submit(self._side, store, pair, s, dry_run) for s in SIDES}
            results = {s: futures[s].result() for s in SIDES}
        record = self.index_record(pair, results)
        store.upsert_index(record)
        return record

    def run(self, store: RunStore, pairs: list[Pair], *, dry_run: bool = False, progress: bool = True) -> RunStore:
        done = 0
        with ThreadPoolExecutor(max_workers=max(1, self.config.workers)) as executor:
            for record in executor.map(lambda p: self.run_pair(store, p, dry_run), pairs):
                done += 1
                if progress:
                    f = record["comparison"]["faithfulness"] if record["comparison"] else record["status"]
                    print(f"[{done}/{len(pairs)}] {record['pair_id']}: {f}", flush=True)
        if dry_run:
            final = "dry_run"
        else:
            summary = store.read_run()["summary"]
            final = "complete" if summary["complete"] == summary["pairs"] else "partial"
        store.refresh_summary(status=final)
        return store
