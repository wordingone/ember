#!/usr/bin/env python3
# goal_id: EMBER-01
# workstream_id: EMBER-01A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail closed when measured restart receipts lack custody or verifier trust."""
from __future__ import annotations
import argparse, hashlib, json, re, sys
from pathlib import Path

CAPABILITIES = {"text", "image", "audio", "reasoning", "tool"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")

def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))

def validate(manifest_path: Path, registry_path: Path) -> list[str]:
    try:
        manifest, registry = read_json(manifest_path), read_json(registry_path)
    except (OSError, json.JSONDecodeError) as exc:
        return ["INPUT_READ: " + str(exc)]
    if not isinstance(manifest, dict) or not isinstance(registry, dict): return ["INPUT_OBJECT"]
    trusted = registry.get("trusted_verifier_sha256")
    if not isinstance(trusted, list) or any(not isinstance(item, str) or not HEX64.fullmatch(item) for item in trusted): return ["TRUSTED_VERIFIER_REGISTRY"]
    records = manifest.get("measured_receipts")
    if not isinstance(records, list): return ["MEASURED_RECEIPTS_NOT_LIST"]
    errors: list[str] = []; seen: set[str] = set(); root = manifest_path.parent.resolve()
    for record in records:
        if not isinstance(record, dict): errors.append("MEASURED_RECEIPT_OBJECT"); continue
        capability = record.get("capability")
        if capability not in CAPABILITIES: errors.append("CAPABILITY_INVALID"); continue
        if capability in seen: errors.append("CAPABILITY_DUPLICATE: " + capability); continue
        seen.add(capability)
        if not isinstance(record.get("benchmark_id"), str) or not record["benchmark_id"].strip(): errors.append("BENCHMARK_ID: " + capability)
        receipt_name = record.get("receipt_path")
        if not isinstance(receipt_name, str) or not receipt_name: errors.append("RECEIPT_PATH: " + capability); continue
        receipt_path = (root / receipt_name).resolve()
        try: receipt_path.relative_to(root)
        except ValueError: errors.append("RECEIPT_PATH_OUTSIDE_MANIFEST: " + capability); continue
        try:
            receipt_bytes = receipt_path.read_bytes(); receipt = json.loads(receipt_bytes.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc: errors.append("RECEIPT_READ: " + capability + ": " + str(exc)); continue
        if not isinstance(receipt, dict): errors.append("RECEIPT_OBJECT: " + capability); continue
        if record.get("receipt_sha256") != hashlib.sha256(receipt_bytes).hexdigest(): errors.append("RECEIPT_SHA256: " + capability)
        checkpoint = record.get("subject_checkpoint_sha256")
        if not isinstance(checkpoint, str) or not HEX64.fullmatch(checkpoint): errors.append("SUBJECT_CHECKPOINT_SHA256: " + capability)
        elif receipt.get("subject_checkpoint_sha256") != checkpoint: errors.append("RECEIPT_CHECKPOINT_BINDING: " + capability)
        if receipt.get("capability") != capability or receipt.get("result") != "MEASURED": errors.append("RECEIPT_MEASURED_BINDING: " + capability)
        if receipt.get("verifier_sha256") not in trusted: errors.append("UNTRUSTED_VERIFIER: " + capability)
    missing = sorted(CAPABILITIES - seen)
    if missing: errors.append("MISSING_MEASURED_CAPABILITIES: " + ", ".join(missing))
    return errors

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--receipt-manifest", required=True, type=Path); parser.add_argument("--trusted-verifier-registry", required=True, type=Path); args = parser.parse_args()
    errors = validate(args.receipt_manifest, args.trusted_verifier_registry)
    if errors: print("\n".join(errors), file=sys.stderr); return 2
    print("EMBER_RESTART_MEASURED_RECEIPTS: VALID"); return 0

if __name__ == "__main__": raise SystemExit(main())
