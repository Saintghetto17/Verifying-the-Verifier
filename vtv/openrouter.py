"""Minimal OpenRouter client. It knows nothing about the dataset or the metrics."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import requests
from dotenv import load_dotenv

from .config import PROJECT_ROOT, RunConfig

API_URL = "https://openrouter.ai/api/v1/chat/completions"
RETRY_STATUSES = {408, 409, 429, 500, 502, 503, 504}


class OpenRouterError(RuntimeError):
    """The key is missing or the response has no usable message."""


@dataclass
class NetworkResult:
    ok: bool
    raw: dict[str, Any]
    error: str | None = None


class OpenRouterClient:
    def __init__(self, config: RunConfig, api_key: str | None = None):
        load_dotenv(PROJECT_ROOT / ".env")
        self.config = config
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.session = requests.Session()

    def payload(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "seed": self.config.seed,
            "max_tokens": self.config.max_tokens,
            "reasoning": {"effort": self.config.reasoning_effort},
            "response_format": {"type": "json_object"},
            "usage": {"include": True},
            "messages": messages,
        }

    def independent(self) -> "OpenRouterClient":
        """A client with its own HTTP session, so parallel requests share nothing."""
        return OpenRouterClient(self.config, api_key=self.api_key)

    def evaluate(self, messages: list[dict[str, Any]]) -> NetworkResult:
        if not self.api_key:
            raise OpenRouterError("set OPENROUTER_API_KEY in .env before a live run")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        last_raw: dict[str, Any] = {}
        last_error = "unknown OpenRouter error"
        for attempt in range(1, self.config.network_attempts + 1):
            try:
                response = self.session.post(API_URL, headers=headers, json=self.payload(messages),
                                             timeout=self.config.timeout_seconds)
                try:
                    raw = response.json()
                except ValueError:
                    raw = {"response_text": response.text}
                raw["_http_status"] = response.status_code
                raw["_network_attempt"] = attempt
                last_raw = raw
                if response.ok and "error" not in raw:
                    return NetworkResult(True, raw)
                last_error = f"HTTP {response.status_code}: {raw.get('error')}"
                if response.ok is False and response.status_code not in RETRY_STATUSES:
                    break
            except requests.RequestException as error:
                last_error = f"network error: {error}"
                last_raw = {"_network_attempt": attempt, "_network_error": str(error)}
            if attempt < self.config.network_attempts:
                time.sleep((2, 6, 18)[min(attempt - 1, 2)])
        return NetworkResult(False, last_raw, last_error)


def extract_message(raw: dict[str, Any]) -> tuple[str, Any, dict[str, Any]]:
    """Return the content string, any provider reasoning, and response metadata."""
    try:
        choice = raw["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as error:
        raise OpenRouterError("response has no choices[0].message") from error
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise OpenRouterError(f"empty content (finish_reason={choice.get('finish_reason')})")
    metadata = {
        "generation_id": raw.get("id"),
        "returned_model": raw.get("model"),
        "provider": raw.get("provider"),
        "finish_reason": choice.get("finish_reason"),
        "usage": raw.get("usage", {}),
    }
    return content, message.get("reasoning"), metadata


def response_cost(raw: dict[str, Any]) -> float:
    usage = raw.get("usage") or {}
    return float(usage.get("cost") or 0.0) if isinstance(usage, dict) else 0.0
