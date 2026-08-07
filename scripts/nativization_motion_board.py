#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Board-facing consumer for the governed nativization motion receipt."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from nativization_motion import load_run_import_manifest, _require_hex


def consume_motion_receipt(
    repo_root: Path,
    receipt_path: Path,
    expected_receipt_sha256: str,
    manifest_path: Path,
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    root = repo_root.resolve()
    receipt = Path(receipt_path).resolve()
    try:
        receipt.relative_to(root)
    except ValueError as exc:
        raise ValueError("motion receipt must be under repo root") from exc
    expected_receipt = _require_hex(expected_receipt_sha256, length=64, label="receipt hash")
    payload = receipt.read_bytes()
    actual_receipt = hashlib.sha256(payload).hexdigest()
    if actual_receipt != expected_receipt:
        raise ValueError("motion receipt hash mismatch")
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("motion receipt is malformed") from exc
    if not isinstance(document, dict):
        raise ValueError("motion receipt must be an object")
    manifest, manifest_sha = load_run_import_manifest(
        root, manifest_path, expected_manifest_sha256, None
    )
    if document.get("run_import_manifest_sha256") != manifest_sha:
        raise ValueError("motion receipt manifest binding mismatch")
    if document.get("run_import_trace_sha256") != manifest["trace_sha256"]:
        raise ValueError("motion receipt trace binding mismatch")
    if document.get("run_import_trace_producer_sha256") != manifest["producer_sha256"]:
        raise ValueError("motion receipt trace producer binding mismatch")
    if not isinstance(document.get("layers"), list) or len(document["layers"]) != len(manifest["layers"]):
        raise ValueError("motion receipt layer coverage mismatch")
    expected_layers = {row["name"]: row["critical_path_share"] for row in manifest["layers"]}
    for row in document["layers"]:
        if not isinstance(row, dict) or row.get("name") not in expected_layers:
            raise ValueError("motion receipt layer identity mismatch")
        if row.get("critical_path_share") != expected_layers[row["name"]]:
            raise ValueError("motion receipt critical-path evidence mismatch")
    return {
        "schema_version": "ember-nativization-motion-board-v1",
        "decision": "MEASURED_STATIC_MOTION",
        "receipt_sha256": actual_receipt,
        "run_import_manifest_sha256": manifest_sha,
        "run_import_trace_sha256": manifest["trace_sha256"],
        "layer_count": len(expected_layers),
    }


def main(argv: list[str]) -> int:
    if len(argv) != 6:
        print("Usage: nativization_motion_board.py <repo-root> <receipt> <receipt-sha256> <manifest> <manifest-sha256>", file=sys.stderr)
        return 2
    try:
        result = consume_motion_receipt(
            Path(argv[1]), Path(argv[2]), argv[3], Path(argv[4]), argv[5]
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
