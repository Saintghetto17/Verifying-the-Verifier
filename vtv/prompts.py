"""Prompt registry and rendering of the multimodal request.

A prompt is a Markdown file containing the markers ``<caption>``, ``<text>`` and
``<image>``. The renderer walks the file left to right and emits text parts
and exactly one image part. The registry (``prompts/registry.json``) maps
version identifiers (``v01`` ... ``v13``) and aliases (``tg``, ``hd`` ...) to
files and records what each version adds.
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import DEFAULT_PROMPTS_ROOT, PROJECT_ROOT
from .data import Pair, sha256_file

MARKER_RE = re.compile(r"(<caption>|<text>|<image>)")
SYSTEM_MESSAGE = (
    "You are a verifier of scientific figures. Follow the user's instructions and "
    "return exactly one JSON object without Markdown fences."
)


class PromptError(ValueError):
    """The prompt cannot be turned into a request."""


@dataclass(frozen=True)
class Prompt:
    version: str
    path: Path
    source: str
    sha256: str
    meta: dict[str, Any]

    @property
    def hypotheses(self) -> int:
        return int(self.meta.get("hypotheses", 0))


def load_registry(root: Path = DEFAULT_PROMPTS_ROOT) -> dict[str, Any]:
    return json.loads((root / "registry.json").read_text(encoding="utf-8"))


def resolve_version(name: str, root: Path = DEFAULT_PROMPTS_ROOT) -> str:
    registry = load_registry(root)
    key = name.lower()
    key = registry["aliases"].get(key, key)
    if key not in registry["versions"]:
        known = sorted(registry["versions"]) + sorted(registry["aliases"])
        raise PromptError(f"unknown prompt {name!r}; known: {', '.join(known)}")
    return key


def load_prompt(name: str, root: Path = DEFAULT_PROMPTS_ROOT) -> Prompt:
    path = Path(name)
    if path.suffix == ".md" and path.is_file():
        source = path.read_text(encoding="utf-8")
        meta = {"file": path.name, "mechanism": "custom prompt", "hypotheses": 8 if "H8" in source else 0}
        version = path.stem
    else:
        version = resolve_version(name, root)
        meta = load_registry(root)["versions"][version]
        path = root / meta["file"]
        source = path.read_text(encoding="utf-8")
    if source.count("<image>") != 1:
        raise PromptError(f"{path.name}: the prompt must contain exactly one <image> marker")
    return Prompt(version, path.resolve(), source, hashlib.sha256(source.encode("utf-8")).hexdigest(), meta)


def _data_url(path: Path) -> str:
    media_type, _ = mimetypes.guess_type(path.name)
    if media_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise PromptError(f"unsupported image format: {path}")
    return f"data:{media_type};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _parts(prompt: Prompt, pair: Pair, image_part: dict[str, Any]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for chunk in MARKER_RE.split(prompt.source):
        if not chunk:
            continue
        if chunk == "<caption>":
            parts.append({"type": "text", "text": pair.caption})
        elif chunk == "<text>":
            parts.append({"type": "text", "text": pair.text_block})
        elif chunk == "<image>":
            parts.append(image_part)
        else:
            parts.append({"type": "text", "text": chunk})
    return parts


def build_messages(prompt: Prompt, pair: Pair, side: str) -> list[dict[str, Any]]:
    """The request sees one image, the caption and the source text. Never the pair, never the label."""
    image = {"type": "image_url", "image_url": {"url": _data_url(pair.image(side))}}
    return [{"role": "system", "content": SYSTEM_MESSAGE}, {"role": "user", "content": _parts(prompt, pair, image)}]


def safe_messages(prompt: Prompt, pair: Pair, side: str) -> list[dict[str, Any]]:
    """Artifact copy of the request: image replaced by its path and hash, no base64."""
    path = pair.image(side).resolve()
    try:
        shown = str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        shown = str(path)
    image = {"type": "image_url", "image": {"path": shown, "bytes": path.stat().st_size, "sha256": sha256_file(path)}}
    return [{"role": "system", "content": SYSTEM_MESSAGE}, {"role": "user", "content": _parts(prompt, pair, image)}]


def preview(prompt: Prompt, pair: Pair, side: str = "orig") -> str:
    return (prompt.source.replace("<caption>", pair.caption).replace("<text>", pair.text_block)
            .replace("<image>", f"[IMAGE: {pair.image(side).name}]"))
