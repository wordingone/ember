# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bind two unchanged full custody runs without loading their giant JSON bodies."""

from __future__ import annotations
import codecs

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping


EXPECTED_AUTHORITY = {
    "goal_id": "EMBER-01",
    "workstream_id": "EMBER-01B",
    "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
}
HASH_FIELDS = (
    "root_spec_sha256",
    "benchmark_registry_sha256",
    "issue_census_sha256",
    "canonical_root_census_sha256",
    "canonical_manifest_sha256",
)
IDENTITY_FIELDS = (
    "authority",
    "execution_id",
    "source_commit",
    *HASH_FIELDS,
    "summary",
    "benchmark_validation_errors",
    "issue_validation_errors",
    "contradiction_count",
    "transient_contradictions",
)
CANONICAL_IDENTITY_FIELDS = tuple(field for field in IDENTITY_FIELDS if field != "execution_id")
MAX_IDENTITY_PREFIX_BYTES = 256 * 1024
EXECUTION_SENTINEL = b"0" * 32


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
def normalized_receipt_sha256(path: Path, execution_id: str, chunk_size: int = 8 * 1024 * 1024) -> str:
    marker = b'"execution_id": "' + execution_id.encode("ascii") + b'"'
    with path.open("rb") as handle:
        prefix = handle.read(MAX_IDENTITY_PREFIX_BYTES + 1)
        if prefix.count(marker) != 1:
            raise ValueError(f"execution_id marker is not unique in receipt prefix: {path.name}")
        marker_start = prefix.index(marker)
        value_start = marker_start + len(b'"execution_id": "')
        value_end = value_start + 32
        digest = hashlib.sha256()
        digest.update(prefix[:value_start])
        digest.update(EXECUTION_SENTINEL)
        digest.update(prefix[value_end:])
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()




def _validate_identity(identity: Any) -> dict[str, Any]:
    if not isinstance(identity, dict):
        raise ValueError("run_identity must be an object")
    missing = [field for field in IDENTITY_FIELDS if field not in identity]
    if missing:
        raise ValueError(f"run_identity missing fields: {','.join(missing)}")
    if identity["authority"] != EXPECTED_AUTHORITY:
        raise ValueError("run_identity authority mismatch")
    if not isinstance(identity["execution_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", identity["execution_id"]):
        raise ValueError("execution_id must be exactly 32 lowercase hex")

    if not re.fullmatch(r"[0-9a-f]{40}", identity["source_commit"] if isinstance(identity["source_commit"], str) else ""):
        raise ValueError("source_commit must be exactly 40 lowercase hex")
    for field in HASH_FIELDS:
        value = identity[field]
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError(f"{field} must be exactly 64 lowercase hex")
    summary = identity["summary"]
    if not isinstance(summary, dict) or not summary:
        raise ValueError("summary must be a non-empty object")
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in summary.values()):
        raise ValueError("summary counts must be nonnegative integers")
    for field in ("benchmark_validation_errors", "issue_validation_errors", "transient_contradictions"):
        if not isinstance(identity[field], list):
            raise ValueError(f"{field} must be an array")
    contradiction_count = identity["contradiction_count"]
    if not isinstance(contradiction_count, int) or isinstance(contradiction_count, bool) or contradiction_count < 0:
        raise ValueError("contradiction_count must be a nonnegative integer")
    return identity


def read_receipt_identity(receipt: Path) -> dict[str, Any]:
    with receipt.open("rb") as handle:
        prefix = handle.read(MAX_IDENTITY_PREFIX_BYTES + 1)
    try:
        text = codecs.getincrementaldecoder("utf-8")("strict").decode(prefix, final=False)
    except UnicodeDecodeError as exc:
        raise ValueError(f"full receipt prefix is not UTF-8: {receipt.name}") from exc
    match = re.match(r'\A\{\s*"run_identity"\s*:\s*', text)
    if match is None:
        raise ValueError(f"run_identity must be the first full receipt field: {receipt.name}")
    try:
        identity, _ = json.JSONDecoder().raw_decode(text, match.end())
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid bounded run_identity: {receipt.name}") from exc
    return _validate_identity(identity)


def load_sidecar(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != "ember-01-custody-run-sidecar-v1":
        raise ValueError(f"invalid run sidecar: {path.name}")
    receipt_name = payload.get("receipt_name")
    if (
        not isinstance(receipt_name, str)
        or not receipt_name
        or receipt_name in {".", ".."}
        or Path(receipt_name).is_absolute()
        or Path(receipt_name).name != receipt_name
        or "/" in receipt_name
        or "\\" in receipt_name
    ):
        raise ValueError(f"invalid receipt_name: {path.name}")
    receipt_hash = payload.get("receipt_sha256")
    if not isinstance(receipt_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", receipt_hash):
        raise ValueError(f"invalid receipt_sha256: {path.name}")
    receipt_size = payload.get("receipt_size_bytes")
    if not isinstance(receipt_size, int) or isinstance(receipt_size, bool) or receipt_size < 0:
        raise ValueError(f"invalid receipt_size_bytes: {path.name}")
    receipt = path.parent / receipt_name
    if not receipt.is_file():
        raise ValueError(f"full receipt missing: {path.name}")
    if receipt.is_symlink():
        raise ValueError(f"full receipt symlink is not allowed: {path.name}")
    if receipt.resolve().parent != path.resolve().parent:
        raise ValueError(f"full receipt escapes sidecar directory: {path.name}")
    if receipt.stat().st_size != receipt_size:
        raise ValueError(f"full receipt size mismatch: {path.name}")
    if sha256_file(receipt) != receipt_hash:
        raise ValueError(f"full receipt hash mismatch: {path.name}")
    identity = _validate_identity(payload.get("run_identity"))
    if read_receipt_identity(receipt) != identity:
        raise ValueError(f"full receipt identity mismatch: {path.name}")
    if identity["benchmark_validation_errors"] or identity["issue_validation_errors"]:
        raise ValueError(f"validation errors present: {path.name}")
    if identity["transient_contradictions"]:
        raise ValueError(f"transient snapshot contradiction present: {path.name}")
    return {
        **payload,
        "run_identity": identity,
        "_sidecar_resolved": str(path.resolve()),
        "_receipt_resolved": str(receipt.resolve()),
        "_normalized_receipt_sha256": normalized_receipt_sha256(receipt, identity["execution_id"]),
    }


def build_compact_receipt(first: Mapping[str, Any], second: Mapping[str, Any], publication_sha: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40}", publication_sha):
        raise ValueError("publication SHA must be exactly 40 lowercase hex")
    if first.get("_sidecar_resolved") == second.get("_sidecar_resolved"):
        raise ValueError("two distinct run sidecars are required")
    if first.get("_receipt_resolved") == second.get("_receipt_resolved"):
        raise ValueError("two distinct full receipts are required")
    first_identity = _validate_identity(first.get("run_identity"))
    if first.get("receipt_sha256") == second.get("receipt_sha256"):
        raise ValueError("distinct execution receipts must have different byte hashes")
    second_identity = _validate_identity(second.get("run_identity"))
    if first_identity["execution_id"] == second_identity["execution_id"]:
        raise ValueError("two distinct execution IDs are required")
    for field in CANONICAL_IDENTITY_FIELDS:
        if first_identity[field] != second_identity[field]:
            raise ValueError(f"run identity mismatch: {field}")
    if first.get("_normalized_receipt_sha256") != second.get("_normalized_receipt_sha256"):
        raise ValueError("normalized receipt bytes mismatch")
    return {
        "schema": "ember-01-custody-compact-receipt-v1",
        "authority": first_identity["authority"],
        "publication_sha": publication_sha,
        "source_commit": first_identity["source_commit"],
        "canonical_root_census_sha256": first_identity["canonical_root_census_sha256"],
        "canonical_manifest_sha256": first_identity["canonical_manifest_sha256"],
        "root_spec_sha256": first_identity["root_spec_sha256"],
        "benchmark_registry_sha256": first_identity["benchmark_registry_sha256"],
        "issue_census_sha256": first_identity["issue_census_sha256"],
        "summary": first_identity["summary"],
        "contradiction_count": first_identity["contradiction_count"],
        "canonical_output_byte_identical": True,
        "canonical_receipt_sha256": first["_normalized_receipt_sha256"],
        "full_receipts": [
            {
                "name": row["receipt_name"],
                "sha256": row["receipt_sha256"],
                "size_bytes": row["receipt_size_bytes"],
                "execution_id": row["run_identity"]["execution_id"],
            }
            for row in (first, second)
        ],
    }


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-one-sidecar", required=True)
    parser.add_argument("--run-two-sidecar", required=True)
    parser.add_argument("--publication-sha", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        first = load_sidecar(Path(args.run_one_sidecar))
        second = load_sidecar(Path(args.run_two_sidecar))
        payload = build_compact_receipt(first, second, args.publication_sha)
        write_json_atomic(Path(args.output), payload)
    except Exception as exc:
        print(f"EMBER_01_COMPACT_RECEIPT FAIL: {exc}")
        return 1
    print(f"EMBER_01_COMPACT_RECEIPT PASS: canonical={payload['canonical_manifest_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
