#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Independently recompute E-RELEASE row and CERT decisions from a redacted bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from issue1947_release_execute import ROWS, canonical, forbid_protected_bytes, sha, validate_row


class ReleaseRecomputeRefusal(ValueError):
    pass


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_self(value: dict[str, Any], label: str) -> None:
    body = dict(value); claimed = body.pop("self_sha256", None)
    if claimed != sha(canonical(body)):
        raise ReleaseRecomputeRefusal(f"SELF_HASH_DRIFT:{label}")


def recompute(bundle_path: Path, thresholds: dict[str, Any] | None = None) -> dict[str, Any]:
    bundle = load(bundle_path)
    verify_self(bundle, "bundle")
    forbid_protected_bytes(bundle)
    if bundle.get("schema_version") != "ember-issue1947-redacted-release-bundle-v1":
        raise ReleaseRecomputeRefusal("BUNDLE_SCHEMA_DRIFT")
    if bundle.get("result") != "COMPLETE" or bundle.get("protected_bytes_present") is not False:
        raise ReleaseRecomputeRefusal("BUNDLE_NOT_COMPLETE_OR_REDACTED")
    bindings = bundle.get("rows")
    if not isinstance(bindings, list) or tuple(row.get("row_id") for row in bindings if isinstance(row, dict)) != ROWS:
        raise ReleaseRecomputeRefusal("MISSING_DUPLICATE_EXTRA_OR_REORDERED_MATRIX_ROW")
    if thresholds is None:
        thresholds = {row["row_id"]: row.get("threshold") for row in bindings}
    if set(thresholds) != set(ROWS):
        raise ReleaseRecomputeRefusal("THRESHOLD_ROW_SET_DRIFT")
    results = []
    for binding in bindings:
        row_id = binding["row_id"]
        relative_path = binding.get("path")
        if relative_path != f"{row_id}.json":
            raise ReleaseRecomputeRefusal(f"ROW_PATH_DRIFT:{row_id}")
        path = bundle_path.parent / relative_path
        raw = path.read_bytes()
        if len(raw) != binding.get("bytes") or sha(raw) != binding.get("raw_sha256"):
            raise ReleaseRecomputeRefusal(f"RAW_ROW_BINDING_DRIFT:{row_id}")
        row = load(path); verify_self(row, row_id)
        if binding.get("self_sha256") != row.get("self_sha256"):
            raise ReleaseRecomputeRefusal(f"ROW_SELF_HASH_BINDING_DRIFT:{row_id}")
        validate_row({key: value for key, value in row.items() if key != "self_sha256"}, row_id)
        scores = [float(item["score"]) for item in row["items"]]
        mean = sum(scores) / len(scores)
        if not math.isfinite(mean):
            raise ReleaseRecomputeRefusal(f"MEAN_SCORE_NONFINITE:{row_id}")
        threshold = thresholds[row_id]
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
            raise ReleaseRecomputeRefusal(f"THRESHOLD_DRIFT:{row_id}")
        if not math.isfinite(float(threshold)):
            raise ReleaseRecomputeRefusal(f"THRESHOLD_NONFINITE:{row_id}")
        results.append({"row_id": row_id, "item_count": len(scores), "mean_score": mean, "threshold": float(threshold), "passed": mean >= float(threshold)})
    cert_007 = all(row["passed"] for row in results)
    receipt = {
        "schema_version": "ember-issue1947-release-independent-recompute-v1",
        "result": "PASS" if cert_007 else "FAIL",
        "bundle_raw_sha256": sha(bundle_path.read_bytes()),
        "rows": results,
        "cert_007_all_required_rows_pass": cert_007,
        "cert_009_independent_raw_row_recomputation": True,
        "claim_boundary": "INDEPENDENT_RECOMPUTATION_ONLY; NO ISSUE_OR_GOAL_CREDIT",
    }
    receipt["self_sha256"] = sha(canonical(receipt))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--thresholds", type=Path)
    parser.add_argument("--expected-designation-manifest-sha256")
    parser.add_argument("--expected-matrix-self-sha256")
    parser.add_argument("--expected-analysis-self-sha256")
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    if args.receipt.exists():
        raise FileExistsError("RECEIPT_EXISTS_REFUSED")
    bundle = load(args.bundle)
    expected = {
        "designation_manifest_raw_sha256": args.expected_designation_manifest_sha256,
        "matrix_self_sha256": args.expected_matrix_self_sha256,
        "analysis_self_sha256": args.expected_analysis_self_sha256,
    }
    for key, value in expected.items():
        if value is not None and bundle.get(key) != value:
            raise ReleaseRecomputeRefusal(f"EXPECTED_IDENTITY_DRIFT:{key}")
    receipt = recompute(args.bundle, load(args.thresholds) if args.thresholds else None)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    with args.receipt.open("xb") as stream:
        stream.write(json.dumps(receipt, indent=2, sort_keys=True).encode() + b"\n")
    print(json.dumps({"result": receipt["result"], "self_sha256": receipt["self_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
