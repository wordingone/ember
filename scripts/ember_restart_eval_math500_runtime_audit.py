#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Audit Math-500 frozen references and exact scorer custody without predictions."""

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _rows(data: bytes) -> int:
    try:
        parsed = json.loads(data.decode("utf-8"))
        values = parsed if isinstance(parsed, list) else [parsed]
    except (UnicodeDecodeError, json.JSONDecodeError):
        values = [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]
    identifiers: set[str] = set()
    for value in values:
        identifier = value.get("unique_id") if isinstance(value, dict) and isinstance(value.get("unique_id"), str) and value["unique_id"] else value.get("id") if isinstance(value, dict) else None
        if not isinstance(value, dict) or not isinstance(identifier, str) or not identifier or identifier in identifiers or not isinstance(value.get("answer"), str) or not value["answer"]:
            raise ValueError("Math-500 references require unique ids and answers")
        identifiers.add(identifier)
    if not identifiers:
        raise ValueError("Math-500 references must be non-empty")
    return len(identifiers)


def audit(*, custody_bytes: bytes, reference_bytes: bytes, scorer_bytes: bytes) -> dict[str, object]:
    try:
        custody = json.loads(custody_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Math custody must be UTF-8 JSON") from error
    math = custody.get("mathematics") if isinstance(custody, dict) else None
    frozen = math.get("frozen_math500") if isinstance(math, dict) else None
    if not isinstance(frozen, dict) or custody.get("schema_version") != "ember-restart-benchmark-custody-v1" or math.get("target_execution_permitted") is not False:
        raise ValueError("Math-500 custody is not fail-closed")
    split_sha = frozen.get("split_sha256")
    revision = frozen.get("revision")
    scorer_path = frozen.get("scoring_adapter_path")
    scorer_sha = digest(scorer_bytes)
    if not isinstance(split_sha, str) or digest(reference_bytes) != split_sha or frozen.get("artifact_sha256") is None or not isinstance(revision, str) or not revision:
        raise ValueError("Math-500 references do not match frozen split custody")
    count = _rows(reference_bytes)
    if count != frozen.get("rows") or scorer_path != "scripts/ember_restart_eval_math_exact.py" or frozen.get("scoring_adapter_sha256") != scorer_sha:
        raise ValueError("Math-500 scorer/row custody mismatch")
    expected_protocol = digest(f"math-500:{revision}:{split_sha}:{frozen.get('license_sha256')}:{scorer_sha}".encode())
    if frozen.get("protocol_sha256") != expected_protocol:
        raise ValueError("Math-500 protocol is not derived from exact custody")
    return {"schema_version": "ember-restart-math500-runtime-audit-v1", "result": "PREFLIGHT_ONLY", "claim_status": "FROZEN_MATH500_RUNTIME_CUSTODY", "benchmark_id": "math-500", "benchmark_version": revision, "split_sha256": split_sha, "references_sha256": split_sha, "protocol_sha256": frozen["protocol_sha256"], "scoring_adapter_sha256": scorer_sha, "sample_count": count, "custody_manifest_sha256": digest(custody_bytes), "target_execution_permitted": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--custody-manifest", required=True, type=Path)
    parser.add_argument("--references", required=True, type=Path)
    parser.add_argument("--scoring-adapter", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must not pre-exist")
    try:
        custody_bytes = args.custody_manifest.read_bytes()
        reference_bytes = args.references.read_bytes()
        scorer_bytes = args.scoring_adapter.read_bytes()
        payload = audit(custody_bytes=custody_bytes, reference_bytes=reference_bytes, scorer_bytes=scorer_bytes)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.output.parent, prefix=args.output.name + ".", suffix=".tmp", delete=False) as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, args.output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
