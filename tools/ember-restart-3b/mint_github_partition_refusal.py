#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Mint and reopen the closed refusal for empty GitHub K connector routes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
from pathlib import Path
from typing import Any


SCHEMA = "ember-github-license-partition-refusal-v1"
REASON = "CONNECTOR_RECEIPT_AND_PAYLOAD_ABSENT"
SLOTS = ("K-train-1", "K-train-2")
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
TOP_KEYS = {
    "schema_version", "result", "reason", "routes", "route_root_sha256",
    "producer_path", "producer_sha256", "source_commit", "model_mediated",
    "borrowed_labels",
}
ROUTE_KEYS = {
    "connector_slot", "custody_path", "child_count", "payload_file_count",
    "connector_receipt_present",
}


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse_or_symlink(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        return bool(path.lstat().st_file_attributes & 0x400)
    except AttributeError:
        return False


def _inspect_empty_route(path: Path, slot: str) -> dict[str, Any]:
    path = Path(path).resolve(strict=True)
    if path.name != slot or not path.is_dir() or _is_reparse_or_symlink(path):
        raise ValueError("K custody identity is invalid")
    children = list(path.iterdir())
    if children:
        raise ValueError("K custody is not empty")
    return {
        "connector_slot": slot,
        "custody_path": str(path),
        "child_count": 0,
        "payload_file_count": 0,
        "connector_receipt_present": False,
    }


def validate_refusal(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file() or _is_reparse_or_symlink(path):
        raise ValueError("K refusal receipt path is invalid")
    receipt = json.loads(path.read_bytes())
    if (
        not isinstance(receipt, dict)
        or set(receipt) != TOP_KEYS
        or receipt.get("schema_version") != SCHEMA
        or receipt.get("result") != "REFUSED"
        or receipt.get("reason") != REASON
        or receipt.get("model_mediated") is not False
        or receipt.get("borrowed_labels") is not False
        or not isinstance(receipt.get("source_commit"), str)
        or HEX40.fullmatch(receipt["source_commit"]) is None
        or receipt.get("producer_path") != "tools/ember-restart-3b/mint_github_partition_refusal.py"
        or not isinstance(receipt.get("producer_sha256"), str)
        or HEX64.fullmatch(receipt["producer_sha256"]) is None
        or receipt["producer_sha256"] != sha256_file(Path(__file__))
    ):
        raise ValueError("K refusal receipt is invalid")
    routes = receipt.get("routes")
    if not isinstance(routes, list) or len(routes) != len(SLOTS):
        raise ValueError("K refusal receipt routes are invalid")
    reopened = []
    for slot, row in zip(SLOTS, routes, strict=True):
        if not isinstance(row, dict) or set(row) != ROUTE_KEYS or row.get("connector_slot") != slot:
            raise ValueError("K refusal receipt route is invalid")
        inspected = _inspect_empty_route(Path(row.get("custody_path", "")), slot)
        if row != inspected:
            raise ValueError("K refusal receipt route changed")
        reopened.append(inspected)
    if receipt.get("route_root_sha256") != sha256_bytes(canonical(reopened)):
        raise ValueError("K refusal receipt root changed")
    return receipt


def mint_refusal(*, custody_roots: list[Path], output: Path, source_commit: str) -> dict[str, Any]:
    if len(custody_roots) != len(SLOTS) or not isinstance(source_commit, str) or HEX40.fullmatch(source_commit) is None:
        raise ValueError("K refusal plan identity is invalid")
    output = Path(output).absolute()
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    routes = [_inspect_empty_route(path, slot) for path, slot in zip(custody_roots, SLOTS, strict=True)]
    receipt = {
        "schema_version": SCHEMA,
        "result": "REFUSED",
        "reason": REASON,
        "routes": routes,
        "route_root_sha256": sha256_bytes(canonical(routes)),
        "producer_path": "tools/ember-restart-3b/mint_github_partition_refusal.py",
        "producer_sha256": sha256_file(Path(__file__)),
        "source_commit": source_commit,
        "model_mediated": False,
        "borrowed_labels": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    if _is_reparse_or_symlink(output.parent):
        raise ValueError("K refusal output parent is reparsed")
    staging = output.parent / f".{output.name}.staging-{secrets.token_hex(8)}"
    try:
        with staging.open("xb") as handle:
            handle.write(canonical(receipt) + b"\n")
        validate_refusal(staging)
        if output.exists():
            raise FileExistsError(f"output raced into existence: {output}")
        staging.rename(output)
        return validate_refusal(output)
    except Exception:
        staging.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k-train-1", type=Path, required=True)
    parser.add_argument("--k-train-2", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    receipt = mint_refusal(
        custody_roots=[args.k_train_1, args.k_train_2],
        output=args.output,
        source_commit=args.source_commit,
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
