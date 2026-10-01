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
import re
from pathlib import Path
from typing import Any

from issue1947_release_execute import (
    INTEGRITY_PLACEHOLDER,
    MODEL_PREDICTION,
    PATHWAY_ENGAGEMENT,
    ROWS,
    canonical,
    evidence_kind,
    forbid_protected_bytes,
    sha,
    validate_row,
)


class ReleaseRecomputeRefusal(ValueError):
    pass


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_self(value: dict[str, Any], label: str) -> None:
    body = dict(value); claimed = body.pop("self_sha256", None)
    if claimed != sha(canonical(body)):
        raise ReleaseRecomputeRefusal(f"SELF_HASH_DRIFT:{label}")


def recompute(bundle_path: Path, thresholds: dict[str, Any] | None = None, *, bundle_raw: bytes | None = None) -> dict[str, Any]:
    if bundle_raw is None:
        bundle_raw = bundle_path.read_bytes()
    bundle = json.loads(bundle_raw)
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
        row = json.loads(raw); verify_self(row, row_id)
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
        # Derived here from the producer table, not read from the bundle, so a bundle cannot
        # promote its own rows. The bundle's copy is then required to agree, which turns any
        # attempt to do so into a refusal instead of a silent upgrade.
        kind = evidence_kind(row_id)
        if binding.get("evidence_kind") != kind:
            raise ReleaseRecomputeRefusal(f"EVIDENCE_KIND_BINDING_DRIFT:{row_id}")
        results.append({"row_id": row_id, "item_count": len(scores), "mean_score": mean, "threshold": float(threshold), "passed": mean >= float(threshold), "evidence_kind": kind})
    model_rows = [row for row in results if row["evidence_kind"] == MODEL_PREDICTION]
    placeholder_rows = [row for row in results if row["evidence_kind"] == INTEGRITY_PLACEHOLDER]
    pathway_rows = [row for row in results if row["evidence_kind"] == PATHWAY_ENGAGEMENT]
    # An empty model-evidence set fails. all([]) is True, and a bar that passed because there was
    # nothing to check would be the same defect this cure exists to remove, wearing a new
    # mechanism. Placeholder outcomes are reported beside it and never folded into it.
    cert_007 = bool(model_rows) and all(row["passed"] for row in model_rows)
    # Evidence-kind coverage over the protected matrix. Row-id completeness is already enforced
    # upstream (EXECUTION_SPEC_ROW_SET_DRIFT); this asks the different question of what KIND of
    # evidence those complete rows carry. A matrix whose rows are present but whose model-evidence
    # surface is a single row is partial-matrix evidence, which the campaign terminal must refuse --
    # and which is invisible in every other field of this receipt.
    matrix_coverage = len(model_rows) / len(results) if results else 0.0
    terminal_eligible = bool(results) and len(model_rows) == len(results)
    receipt = {
        "schema_version": "ember-issue1947-release-independent-recompute-v1",
        "result": "PASS" if cert_007 else "FAIL",
        "bundle_raw_sha256": sha(bundle_raw),
        "rows": results,
        "model_evidence_row_count": len(model_rows),
        "integrity_placeholder_row_count": len(placeholder_rows),
        "integrity_placeholder_rows_pass": all(row["passed"] for row in placeholder_rows),
        # Checkpoint-derived and deliberately outside the bar.  Reported so the count is visible
        # rather than absent -- an engagement rate that vanished from the receipt would be as
        # misleading as one folded into the bar, in the opposite direction.
        "pathway_engagement_row_count": len(pathway_rows),
        "pathway_engagement_rows_pass": all(row["passed"] for row in pathway_rows),
        "cert_007_basis": (
            "no model-evidence row exists, so the bar is unmet rather than vacuously satisfied"
            if not model_rows else
            f"{len(model_rows)} model-evidence row(s) evaluated; {len(placeholder_rows)} integrity placeholder(s) and {len(pathway_rows)} pathway-engagement row(s) reported separately"
        ),
        "cert_007_all_required_rows_pass": cert_007,
        "cert_009_independent_raw_row_recomputation": True,
        # Reported beside the certificates and folded into neither. cert_007 asks whether the model
        # cleared its floors and cert_009 whether the evaluator recomputed the raw rows; NEITHER asks
        # whether the matrix carries model evidence at all, and a matrix can satisfy both while
        # measuring almost nothing.
        "matrix_model_evidence_coverage": matrix_coverage,
        "terminal_eligible_on_matrix_coverage": terminal_eligible,
        "matrix_coverage_basis": (
            f"{len(model_rows)} of {len(results)} protected matrix rows carry {MODEL_PREDICTION} "
            f"evidence; {len(placeholder_rows)} carry {INTEGRITY_PLACEHOLDER} and "
            f"{len(pathway_rows)} carry {PATHWAY_ENGAGEMENT}. A placeholder row reconciles an "
            "artifact against a gold digest and gives the model no credit, so it cannot stand in "
            "for a model-evidence row when asking whether the matrix is whole."
        ),
        "claim_boundary": "INDEPENDENT_RECOMPUTATION_ONLY; NO ISSUE_OR_GOAL_CREDIT",
    }
    receipt["self_sha256"] = sha(canonical(receipt))
    return receipt


def select_bundle_from_pointer(pointer_file: Path, repo_root: Path) -> tuple[Path, bytes]:
    try:
        pointer = json.loads(pointer_file.read_bytes())
    except FileNotFoundError as exc:
        raise ReleaseRecomputeRefusal("no admitted release bundle pointer") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseRecomputeRefusal("RELEASE_BUNDLE_POINTER_INVALID") from exc
    if not isinstance(pointer, dict) or pointer.get("schema_version") != "ember-issue1947-release-bundle-pointer-v1":
        raise ReleaseRecomputeRefusal("RELEASE_BUNDLE_POINTER_SCHEMA_DRIFT")
    relative = pointer.get("bundle_path")
    expected_sha = pointer.get("bundle_raw_sha256")
    parts = relative.split("/") if isinstance(relative, str) else []
    if (
        len(parts) != 5
        or parts[:3] != ["receipts", "issue1947", "releases"]
        or parts[4] != "release-bundle.json"
        or "\\" in relative or ":" in relative
        or any(part in ("", ".", "..") for part in parts)
        or not isinstance(expected_sha, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_sha) is None
        or parts[3] != expected_sha
    ):
        raise ReleaseRecomputeRefusal("RELEASE_BUNDLE_POINTER_PATH_OR_DIGEST_INVALID")
    root = repo_root.resolve()
    bundle_path = (root / Path(*relative.split("/"))).resolve()
    if not bundle_path.is_relative_to(root):
        raise ReleaseRecomputeRefusal("RELEASE_BUNDLE_POINTER_PATH_OUTSIDE_REPOSITORY")
    try:
        bundle_raw = bundle_path.read_bytes()
    except FileNotFoundError as exc:
        raise ReleaseRecomputeRefusal("RELEASE_BUNDLE_POINTER_TARGET_MISSING") from exc
    except OSError as exc:
        raise ReleaseRecomputeRefusal("RELEASE_BUNDLE_POINTER_TARGET_UNREADABLE") from exc
    if sha(bundle_raw) != expected_sha:
        raise ReleaseRecomputeRefusal("BUNDLE_POINTER_DIGEST_MISMATCH")
    return bundle_path, bundle_raw

def main() -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--bundle", type=Path, help="explicit bundle path for direct audited invocations")
    source.add_argument("--pointer", type=Path, default=Path("receipts/issue1947/release-bundle-pointer.json"))
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--thresholds", type=Path)
    parser.add_argument("--expected-designation-manifest-sha256")
    parser.add_argument("--expected-matrix-self-sha256")
    parser.add_argument("--expected-analysis-self-sha256")
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    if args.receipt.exists():
        raise FileExistsError("RECEIPT_EXISTS_REFUSED")
    repo_root = args.repo_root.resolve()
    if args.bundle is not None:
        bundle_path = args.bundle.resolve()
        bundle_raw = bundle_path.read_bytes()
    else:
        pointer_file = args.pointer if args.pointer.is_absolute() else repo_root / args.pointer
        bundle_path, bundle_raw = select_bundle_from_pointer(pointer_file, repo_root)
    bundle = json.loads(bundle_raw)
    expected = {
        "designation_manifest_raw_sha256": args.expected_designation_manifest_sha256,
        "matrix_self_sha256": args.expected_matrix_self_sha256,
        "analysis_self_sha256": args.expected_analysis_self_sha256,
    }
    for key, value in expected.items():
        if value is not None and bundle.get(key) != value:
            raise ReleaseRecomputeRefusal(f"EXPECTED_IDENTITY_DRIFT:{key}")
    receipt = recompute(bundle_path, load(args.thresholds) if args.thresholds else None, bundle_raw=bundle_raw)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    with args.receipt.open("xb") as stream:
        stream.write(json.dumps(receipt, indent=2, sort_keys=True).encode() + b"\n")
    print(json.dumps({"result": receipt["result"], "self_sha256": receipt["self_sha256"]}, sort_keys=True))
    return 0 if receipt["result"] == "PASS" else 1

if __name__ == "__main__":
    raise SystemExit(main())
