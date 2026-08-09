# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""Closed, CPU-only preregistration gate for issue #798.

This carrier deliberately stops before any PPM/model work.  A validated frozen
manifest is necessary but not sufficient: the decisive ``run_measure``
consumer must be explicitly supplied and byte-bound before launch.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "ember-703-ppm-screen-prereg-v1"
_REQUIRED = {
    "schema", "issue", "order_cap", "escape_method", "train_target_bytes",
    "selection", "heldout_manifest_sha256", "shard_ids", "lambda_grid",
    "seed", "raw_byte_custody", "manifest_sha256",
}
_HEX64 = set("0123456789abcdefABCDEF")


class LaunchNotReady(RuntimeError):
    """The frozen prereg is valid but no authoritative consumer is bound."""


def _canonical(value: dict[str, Any]) -> bytes:
    body = dict(value)
    body.pop("manifest_sha256", None)
    return (json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def canonical_manifest_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha(value: Any, label: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(c not in _HEX64 for c in value):
        raise ValueError(f"{label} must be a lowercase/uppercase 64-hex SHA-256")


class ValidatedPrereg(dict):
    def require_launch_ready(self, consumer: str | Path | None = None) -> None:
        if consumer is None:
            raise LaunchNotReady("DECISIVE_CONSUMER_UNBOUND: run_measure entrypoint is absent")
        path = Path(consumer)
        if not path.is_file():
            raise LaunchNotReady("DECISIVE_CONSUMER_UNBOUND: consumer path is not a file")
        text = path.read_text(encoding="utf-8")
        if "def run_measure" not in text or "--confirm-go" not in text:
            raise LaunchNotReady("DECISIVE_CONSUMER_UNBOUND: consumer lacks governed run_measure/confirm-go")


def validate_prereg_manifest(path: str | Path) -> ValidatedPrereg:
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"manifest unreadable or malformed: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("manifest must be an object")
    if set(value) != _REQUIRED:
        raise ValueError("manifest fields are not the closed v1 set")
    if value["schema"] != SCHEMA or value["issue"] != 798:
        raise ValueError("manifest schema/issue mismatch")
    if value["order_cap"] != 8 or value["escape_method"] != "D":
        raise ValueError("frozen PPM order/escape mismatch")
    if value["train_target_bytes"] != 2 * 1024**3 or value["selection"] != "interleaved":
        raise ValueError("frozen 2 GiB interleaved train selection required")
    if value["seed"] != 703:
        raise ValueError("frozen bootstrap seed mismatch")
    _sha(value["heldout_manifest_sha256"], "heldout_manifest_sha256")
    _sha(value["manifest_sha256"], "manifest_sha256")
    if value["manifest_sha256"].lower() != canonical_manifest_sha256(value):
        raise ValueError("manifest_sha256 does not match canonical manifest bytes")
    grid = value["lambda_grid"]
    if not isinstance(grid, list) or not grid or any(not isinstance(x, (int, float)) or isinstance(x, bool) or not 0 < x < 1 for x in grid):
        raise ValueError("lambda_grid must contain finite values in (0,1)")
    if grid != sorted(set(grid)):
        raise ValueError("lambda_grid must be sorted and duplicate-free")
    shards = value["shard_ids"]
    if not isinstance(shards, list) or not shards:
        raise ValueError("shard_ids must be a nonempty list")
    seen: set[str] = set()
    total = 0
    for row in shards:
        if not isinstance(row, dict) or set(row) != {"id", "sha256", "bytes"}:
            raise ValueError("shard rows must use the closed id/sha256/bytes shape")
        sid = row["id"]
        if not isinstance(sid, str) or not sid or sid in seen:
            raise ValueError("shard ids must be unique nonempty strings")
        seen.add(sid)
        _sha(row["sha256"], f"shard {sid} sha256")
        if not isinstance(row["bytes"], int) or isinstance(row["bytes"], bool) or row["bytes"] <= 0:
            raise ValueError(f"shard {sid} bytes must be a positive integer")
        total += row["bytes"]
    if total < value["train_target_bytes"]:
        raise ValueError("shard bytes do not cover frozen train target")
    custody = value["raw_byte_custody"]
    if not isinstance(custody, dict) or set(custody) != {"source_url", "sha256"}:
        raise ValueError("raw_byte_custody must be source_url/sha256")
    if not isinstance(custody["source_url"], str) or not custody["source_url"].startswith("https://"):
        raise ValueError("raw_byte_custody.source_url must be https")
    _sha(custody["sha256"], "raw_byte_custody.sha256")
    return ValidatedPrereg(value)


__all__ = ["LaunchNotReady", "ValidatedPrereg", "canonical_manifest_sha256", "validate_prereg_manifest"]
