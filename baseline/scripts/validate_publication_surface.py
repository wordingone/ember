#!/usr/bin/env python3
"""Validate the reproducibility/publication surface baseline family."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_REPORT_TEXT = [
    "Status: BASELINE_COMPLETE for `reproducibility_publication_surface`",
    "PUBLICATION_SURFACE_BASELINE_COMPLETE",
    "remote proof receipt",
    "operator acceptance remains separate",
]

REQUIRED_PARITY_TEXT = [
    "PUBLICATION_SURFACE_BASELINE_COMPLETE",
    "Source ledger",
    "Line endings",
    "Remote proof",
    "Overall goal completion still requires strict verifier PASS and explicit operator acceptance.",
]

REQUIRED_SHIPPING_TEXT = [
    "A staging branch is not a completion surface.",
    "public repo exposes the reviewed `/baseline` subtree on default `master`",
    "private backup repo exposes the same reviewed `/baseline` subtree on default `master`",
    "Branch existence, local commits, in-session promises, private-only proof, or unmerged PRs cannot satisfy completion.",
]

REQUIRED_LOCK_SOURCES = {"mlcommons-algoperf", "agent-openai-codex", "agent-anthropic-claude-code"}

REQUIRED_FILES = [
    "README.md",
    "completion-lock.json",
    "sources.jsonl",
    "4090-ceiling-v0.md",
    "field-level-threshold-v0.md",
    "contracts/reproducibility-publication-surface.md",
    "contracts/baseline-shipping-discipline.md",
    "reports/report-v0.md",
    "reports/public-private-parity-v0.md",
    "scripts/verify_completion.py",
    "scripts/validate_publication_surface.py",
    "receipts/source-ledger-validation-2026-06-29.json",
    "receipts/line-endings-validation-2026-06-29.json",
    "receipts/remote-proof-2026-06-29.json",
    "receipts/publication-manifest-2026-06-29.json",
]

FORBIDDEN_DOC_TERMS = ["STAGING ONLY", "NOT COMPLETE"]



def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def require_text(path: Path, needles: list[str], failures: list[dict[str, Any]], label: str) -> None:
    if not path.exists():
        failures.append({"code": f"{label}_missing", "path": str(path)})
        return
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    for term in FORBIDDEN_DOC_TERMS:
        if term in text:
            failures.append({"code": f"{label}_forbidden_term", "term": term})
    for needle in needles:
        if needle not in text:
            failures.append({"code": f"{label}_missing_required_text", "needle": needle})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    failures: list[dict[str, Any]] = []
    contract_path = root / "contracts" / "reproducibility-publication-surface.md"
    shipping_contract_path = root / "contracts" / "baseline-shipping-discipline.md"
    parity_path = root / "reports" / "public-private-parity-v0.md"
    report_path = root / "reports" / "report-v0.md"
    lock_path = root / "completion-lock.json"

    for rel in REQUIRED_FILES:
        if not (root / rel).exists():
            failures.append({"code": "required_file_missing", "path": rel})

    require_text(contract_path, REQUIRED_REPORT_TEXT, failures, "contract")
    require_text(shipping_contract_path, REQUIRED_SHIPPING_TEXT, failures, "shipping_contract")
    require_text(parity_path, REQUIRED_PARITY_TEXT, failures, "parity_report")
    require_text(report_path, ["OVERALL INCOMPLETE PENDING OPERATOR ACCEPTANCE", "Publication-surface validation receipt"], failures, "main_report")
    require_text(root / "README.md", ["OVERALL INCOMPLETE PENDING OPERATOR ACCEPTANCE", "validate_publication_surface.py"], failures, "readme")

    source_receipt = read_json(root / "receipts" / "source-ledger-validation-2026-06-29.json") if (root / "receipts" / "source-ledger-validation-2026-06-29.json").exists() else {}
    if source_receipt.get("verdict") != "PASS" or source_receipt.get("source_count", 0) < 22:
        failures.append({"code": "source_receipt_not_pass", "receipt": source_receipt})

    line_receipt = read_json(root / "receipts" / "line-endings-validation-2026-06-29.json") if (root / "receipts" / "line-endings-validation-2026-06-29.json").exists() else {}
    if line_receipt.get("verdict") != "PASS":
        failures.append({"code": "line_endings_receipt_not_pass", "receipt": line_receipt})

    manifest_receipt = read_json(root / "receipts" / "publication-manifest-2026-06-29.json") if (root / "receipts" / "publication-manifest-2026-06-29.json").exists() else {}
    manifest_hash = manifest_receipt.get("manifest_hash")
    manifest_policy = manifest_receipt.get("hash_policy")
    if not manifest_hash or not manifest_policy:
        failures.append({"code": "publication_manifest_receipt_incomplete", "receipt": manifest_receipt})

    remote_receipt = read_json(root / "receipts" / "remote-proof-2026-06-29.json") if (root / "receipts" / "remote-proof-2026-06-29.json").exists() else {}
    if remote_receipt.get("verdict") != "PASS":
        failures.append({"code": "remote_receipt_not_pass", "receipt": remote_receipt})
    else:
        for key in ("public", "private"):
            repo = remote_receipt.get(key)
            if not isinstance(repo, dict) or not repo.get("commit_sha") or not repo.get("baseline_present"):
                failures.append({"code": "remote_receipt_repo_incomplete", "repo": key, "value": repo})
                continue
            if repo.get("baseline_manifest_hash") != manifest_hash:
                failures.append({"code": "remote_receipt_manifest_hash_mismatch", "repo": key, "expected": manifest_hash, "actual": repo.get("baseline_manifest_hash")})
            if repo.get("artifact_identity_policy") != manifest_policy:
                failures.append({"code": "remote_receipt_manifest_policy_mismatch", "repo": key, "expected": manifest_policy, "actual": repo.get("artifact_identity_policy")})
            final_override = remote_receipt.get("human_final_branch_override_receipt")
            if not final_override and repo.get("ref") != "refs/heads/master":
                failures.append({"code": "remote_receipt_not_default_master", "repo": key, "expected": "refs/heads/master", "actual": repo.get("ref"), "override": final_override})

    lock = read_json(lock_path) if lock_path.exists() else {}
    family = lock.get("mandatory_claim_families", {}).get("reproducibility_publication_surface")
    if not isinstance(family, dict):
        failures.append({"code": "lock_family_missing"})
    else:
        expected = {
            "status": "BASELINE_COMPLETE",
            "contract_path": "contracts/reproducibility-publication-surface.md",
            "report_path": "reports/public-private-parity-v0.md",
            "verifier_receipt": "receipts/publication-surface-validation-2026-06-29.json",
        }
        for field, value in expected.items():
            if family.get(field) != value:
                failures.append({"code": "lock_field_mismatch", "field": field, "expected": value, "actual": family.get(field)})
        for source_id in REQUIRED_LOCK_SOURCES:
            if source_id not in family.get("source_rows", []):
                failures.append({"code": "lock_missing_source_row", "id": source_id})

    line = lock.get("line_endings") if isinstance(lock, dict) else None
    if not isinstance(line, dict) or line.get("verdict") != "PASS":
        failures.append({"code": "lock_line_endings_not_pass", "actual": line})
    promotion = lock.get("promotion") if isinstance(lock, dict) else None
    if not isinstance(promotion, dict) or promotion.get("remote_proof_receipt") != "receipts/remote-proof-2026-06-29.json":
        failures.append({"code": "lock_remote_proof_receipt_missing", "actual": promotion})
    if isinstance(promotion, dict):
        expected_manifest = f"publication-manifest-sha256:{manifest_hash}"
        if promotion.get("manifest_hashes") != expected_manifest:
            failures.append({"code": "lock_manifest_hash_mismatch", "expected": expected_manifest, "actual": promotion.get("manifest_hashes")})
        if promotion.get("manifest_policy") != manifest_policy:
            failures.append({"code": "lock_manifest_policy_mismatch", "expected": manifest_policy, "actual": promotion.get("manifest_policy")})
        if promotion.get("manifest_receipt") != "receipts/publication-manifest-2026-06-29.json":
            failures.append({"code": "lock_manifest_receipt_missing", "actual": promotion.get("manifest_receipt")})
    if lock.get("operator_acceptance") is not None:
        failures.append({"code": "operator_acceptance_must_remain_external"})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "PUBLICATION_SURFACE_BASELINE_COMPLETE" if not failures else "PUBLICATION_SURFACE_BASELINE_INCOMPLETE",
        "failure_count": len(failures),
        "failures": failures,
        "contract_path": "contracts/reproducibility-publication-surface.md",
        "shipping_contract_path": "contracts/baseline-shipping-discipline.md",
        "report_path": "reports/public-private-parity-v0.md",
        "completion_limit": "This validates only the reproducibility_publication_surface family. It does not create operator acceptance or complete the overall baseline.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())