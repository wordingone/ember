#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Board-facing consumer for the governed nativization motion receipt."""
from __future__ import annotations

import hashlib
import json
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nativization_motion import load_run_import_manifest, _require_hex, sha256_file, _source_commit_is_usable, measure_layer, get_layer_file_globs


RECEIPT_FIELDS = {
    "schema_version",
    "ts",
    "ticket",
    "goal_id",
    "workstream_id",
    "next_executed_outcome",
    "sha_convention",
    "invariant_sha256",
    "map_source_sha",
    "source_commit",
    "run_import_manifest_sha256",
    "run_import_trace_sha256",
    "run_import_trace_producer_sha256",
    "layers",
    "deltas",
    "next_home_candidate",
    "method",
    "limits",
    "predecessor_receipt_path",
    "predecessor_receipt_sha256",
    "predecessor_source_commit",
    "predecessor_trace_producer_sha256",
    "predecessor_method",
}
LAYER_FIELDS = {
    "name",
    "borrowed_deps",
    "borrowed_deps_count",
    "borrowed_loc",
    "owned_loc",
    "borrowed_binaries",
    "critical_path_share",
}
CRITICAL_SHARE_FIELDS = {"creation", "current_rung_training", "growth_run", "evidence"}
DELTA_FIELDS = {"borrowed_deps_delta", "borrowed_loc_delta"}


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
    if set(document) != RECEIPT_FIELDS:
        raise ValueError("motion receipt fields are not closed")
    if document["schema_version"] != "ember-nativization-motion-receipt-v2":
        raise ValueError("motion receipt schema version is not governed")
    manifest, manifest_sha = load_run_import_manifest(
        root, manifest_path, expected_manifest_sha256, None
    )
    if not isinstance(document["ts"], str):
        raise ValueError("motion receipt timestamp is invalid")
    try:
        timestamp = datetime.fromisoformat(document["ts"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("motion receipt timestamp is invalid") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("motion receipt timestamp must be UTC")
    if document["ticket"] != "S5-NATIVIZATION-MOTION" or document["goal_id"] != "EMBER-02" or document["workstream_id"] != "EMBER-02A":
        raise ValueError("motion receipt diagnostic identity mismatch")
    for field in ("run_import_manifest_sha256", "run_import_trace_sha256", "run_import_trace_producer_sha256"):
        _require_hex(document[field], length=64, label=field)
    if document["run_import_manifest_sha256"] != manifest_sha:
        raise ValueError("motion receipt manifest binding mismatch")
    if document["run_import_trace_sha256"] != manifest["trace_sha256"]:
        raise ValueError("motion receipt trace binding mismatch")
    if document["run_import_trace_producer_sha256"] != manifest["producer_sha256"]:
        raise ValueError("motion receipt trace producer binding mismatch")
    source = _require_hex(document["source_commit"], length=40, label="source_commit")
    if source != manifest["source_commit"] or not _source_commit_is_usable(root, source):
        raise ValueError("motion receipt source commit binding mismatch")
    try:
        commit_result = subprocess.run(
            ["git", "show", "-s", "--format=%cI", source],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        commit_timestamp = datetime.fromisoformat(commit_result.stdout.strip().replace("Z", "+00:00"))
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        raise ValueError("motion receipt source commit timestamp is unavailable") from exc
    if timestamp < commit_timestamp:
        raise ValueError("motion receipt timestamp is stale for its source commit")
    invariant = document["invariant_sha256"]
    if invariant != "sha256:unknown":
        _require_hex(invariant, length=64, label="invariant_sha256")
    map_source_sha = document["map_source_sha"]
    if not isinstance(map_source_sha, str) or not map_source_sha.startswith("sha256:"):
        raise ValueError("motion receipt diagnostic hash is invalid")
    _require_hex(map_source_sha[7:], length=64, label="diagnostic hash")
    diagnostic_path = root / "docs" / "design" / "ember-owned-substrate-diagnostic.md"
    if not diagnostic_path.is_file() or map_source_sha != sha256_file(diagnostic_path):
        raise ValueError("motion receipt diagnostic bytes are stale")
    if document["method"] != "phase-rooted-import-graph-v1":
        raise ValueError("motion receipt method is not governed")
    predecessor = None
    predecessor_sha = document["predecessor_receipt_sha256"]
    predecessor_path_value = document["predecessor_receipt_path"]
    predecessor_source = document["predecessor_source_commit"]
    if predecessor_path_value is None or predecessor_sha is None or predecessor_source is None:
        if any(value is not None for value in (predecessor_path_value, predecessor_sha, predecessor_source)):
            raise ValueError("motion receipt predecessor authority is incomplete")
        if document["deltas"] is not None:
            raise ValueError("motion receipt deltas require an explicit predecessor")
    else:
        if not isinstance(predecessor_path_value, str) or not predecessor_path_value.startswith("receipts/nativization-motion/"):
            raise ValueError("motion receipt predecessor path is invalid")
        predecessor_path = (root / predecessor_path_value).resolve()
        try:
            predecessor_path.relative_to(root)
        except ValueError as exc:
            raise ValueError("motion receipt predecessor path escapes repo root") from exc
        predecessor_sha = _require_hex(predecessor_sha, length=64, label="predecessor receipt hash")
        if predecessor_path == receipt:
            raise ValueError("motion receipt predecessor must differ from current receipt")
        predecessor_payload = predecessor_path.read_bytes()
        if hashlib.sha256(predecessor_payload).hexdigest() != predecessor_sha:
            raise ValueError("motion receipt predecessor hash mismatch")
        try:
            predecessor = json.loads(predecessor_payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("motion receipt predecessor is malformed") from exc
        if not isinstance(predecessor, dict) or not isinstance(predecessor.get("layers"), list):
            raise ValueError("motion receipt predecessor is invalid")
        if predecessor.get("source_commit") != predecessor_source:
            raise ValueError("motion receipt predecessor source mismatch")
        if predecessor_source != document["source_commit"] and not _source_commit_is_usable(root, predecessor_source):
            raise ValueError("motion receipt predecessor source is not governed")
        predecessor_producer = _require_hex(document["predecessor_trace_producer_sha256"], length=64, label="predecessor trace producer hash")
        if predecessor_producer != predecessor.get("run_import_trace_producer_sha256"):
            raise ValueError("motion receipt predecessor producer binding mismatch")
        if predecessor_producer != document["run_import_trace_producer_sha256"]:
            raise ValueError("motion receipt predecessor producer differs from current producer")
        if document["predecessor_method"] != predecessor.get("method"):
            raise ValueError("motion receipt predecessor method binding mismatch")
        if document["predecessor_method"] != document["method"]:
            raise ValueError("motion receipt predecessor method differs from current method")
    if not isinstance(document["sha_convention"], str) or not document["sha_convention"]:
        raise ValueError("motion receipt SHA convention is invalid")
    if not isinstance(document["next_executed_outcome"], str) or not document["next_executed_outcome"]:
        raise ValueError("motion receipt outcome identity is invalid")
    if not isinstance(document["limits"], list) or not all(isinstance(item, str) for item in document["limits"]):
        raise ValueError("motion receipt limits are invalid")
    expected_layers = {row["name"]: row["critical_path_share"] for row in manifest["layers"]}
    rows = document["layers"]
    if not isinstance(rows, list) or len(rows) != len(expected_layers):
        raise ValueError("motion receipt layer coverage mismatch")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != LAYER_FIELDS:
            raise ValueError("motion receipt layer fields are not closed")
        name = row["name"]
        if not isinstance(name, str) or name in seen or name not in expected_layers:
            raise ValueError("motion receipt layer identity mismatch")
        seen.add(name)
        source_paths = sorted({
            item["path"]
            for event in manifest["trace"]["events"]
            if event["layer"] == name
            for item in event["layer_reachable"]
        })
        recomputed = measure_layer(
            root, name, get_layer_file_globs(name), expected_layers[name],
            source_commit=manifest["source_commit"], source_paths=source_paths,
        )
        deps = row["borrowed_deps"]
        if not isinstance(deps, list) or deps != sorted(set(deps)) or not all(isinstance(item, str) for item in deps):
            raise ValueError("motion receipt borrowed dependency evidence is invalid")
        if type(row["borrowed_deps_count"]) is not int or row["borrowed_deps_count"] != len(deps):
            raise ValueError("motion receipt borrowed dependency count mismatch")
        if deps != recomputed.borrowed_deps or row["borrowed_deps_count"] != recomputed.borrowed_deps_count:
            raise ValueError("motion receipt borrowed dependency projection is not Git-derived")
        for field in ("borrowed_loc", "owned_loc"):
            if type(row[field]) is not int or row[field] < 0:
                raise ValueError("motion receipt borrowed-weight evidence is invalid")
        if row["borrowed_loc"] != recomputed.borrowed_loc or row["owned_loc"] != recomputed.owned_loc:
            raise ValueError("motion receipt borrowed-weight LOC is not Git-derived")
        binaries = row["borrowed_binaries"]
        if not isinstance(binaries, list) or binaries != sorted(set(binaries)) or not all(isinstance(item, str) for item in binaries):
            raise ValueError("motion receipt borrowed binary evidence is invalid")
        share = row["critical_path_share"]
        if not isinstance(share, dict) or set(share) != CRITICAL_SHARE_FIELDS:
            raise ValueError("motion receipt critical-path evidence is not closed")
        if not all(type(share[field]) is bool for field in ("creation", "current_rung_training", "growth_run")) or not isinstance(share["evidence"], str):
            raise ValueError("motion receipt critical-path evidence is invalid")
        if share != expected_layers[name]:
            raise ValueError("motion receipt critical-path evidence mismatch")
    if seen != set(expected_layers):
        raise ValueError("motion receipt layer coverage mismatch")
    deltas = document["deltas"]
    if deltas is not None:
        if not isinstance(deltas, dict) or set(deltas) != seen:
            raise ValueError("motion receipt predecessor deltas are not closed")
        for value in deltas.values():
            if not isinstance(value, dict) or set(value) != DELTA_FIELDS or not all(type(value[field]) is int for field in DELTA_FIELDS):
                raise ValueError("motion receipt predecessor delta is invalid")
    if predecessor is not None:
        expected_deltas = {}
        prior_rows = {row["name"]: row for row in predecessor["layers"] if isinstance(row, dict) and isinstance(row.get("name"), str)}
        for row in rows:
            prior_row = prior_rows.get(row["name"])
            if prior_row is None:
                raise ValueError("motion receipt predecessor layer coverage mismatch")
            expected_deltas[row["name"]] = {
                "borrowed_deps_delta": row["borrowed_deps_count"] - prior_row["borrowed_deps_count"],
                "borrowed_loc_delta": row["borrowed_loc"] - prior_row["borrowed_loc"],
            }
        if document["deltas"] != expected_deltas:
            raise ValueError("motion receipt predecessor deltas are not recomputed")
    candidate = document["next_home_candidate"]
    if candidate is not None and (not isinstance(candidate, str) or candidate not in seen):
        raise ValueError("motion receipt next-home candidate is invalid")
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
