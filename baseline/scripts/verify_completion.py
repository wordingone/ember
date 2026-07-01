#!/usr/bin/env python3
"""Fail-closed completion verifier for the Ember ultimate SOTA baseline.

This verifier intentionally treats staging packets as incomplete. PASS is only for
the final /baseline artifact described by state/goals/ember-sota-baseline-goal.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

MANDATORY_FAMILIES = [
    "training_efficiency_sota",
    "data_efficiency_sota",
    "single_4090_ge_1b_foundation_ceiling",
    "architecture_growth_keystone_sota",
    "self_improvement_loop_sota",
    "local_agentic_research_sota",
    "ember_cli_runtime_reproducibility",
    "ember_goal_mode_control",
    "reproducibility_publication_surface",
    "field_level_contribution_threshold",
]

REQUIRED_TOP_LEVEL = [
    "README.md",
    "completion-lock.json",
    "sources.jsonl",
    "anchors.md",
    "claim-map-v0.md",
    "4090-ceiling-v0.md",
    "field-level-threshold-v0.md",
    "contracts",
    "protocols",
    "scripts/verify_completion.py",
    "schemas",
    "receipts",
    "reports/report-v0.md",
    "reports/public-private-parity-v0.md",
]

REQUIRED_SOURCE_IDS = [
    "modded-nanogpt",
    "babylm-2026",
    "mlcommons-algoperf",
    "nvidia-rtx-4090",
    "chinchilla",
    "mle-bench",
    "mlagentbench",
    "ai-scientist",
    "agent-openai-codex",
    "agent-anthropic-claude-code",
    "agent-nvidia-nemo-agent-toolkit",
    "deepseek-deepspec-dspark",
    "deepseek-open-infra-index",
    "sapient-hrm",
    "modded-nanotabpfn",
    "nvidia-cutlass",
    "triton-language",
]

FORBIDDEN_COMPLETION_TERMS = [
    "STAGING ONLY",
    "NOT COMPLETE",
    "OUT_OF_SCOPE_FOR_THIS_BASELINE_RELEASE",
    "OUT_OF_SCOPE",
    "DEFERRED",
    "OPTIONAL",
    "TODO",
    "TBD",
    "OPERATOR_ACCEPTANCE_ASSUMED",
    "USER_WILL_PROBABLY_ACCEPT",
]

CEILING_REQUIRED_PHRASES = [
    "RTX 4090",
    "1B",
    "FLOP",
    "memory",
    "optimizer",
    "activation",
    "precision",
    "quantization",
    "token budget",
    "from scratch",
    "pretraining-equivalent",
    "wall-clock",
    "falsifiable contract",
    "native C++/CUDA/Triton",
    "PyTorch is a reproducible reference path, not the automatic ceiling",
]

SELF_REFERENTIAL_MANIFEST_EXCLUDES = {
    "completion-lock.json",
    "receipts/acceptance-readiness-redteam-2026-06-29.json",
    "receipts/completion-verifier-fail-repaired-goal-2026-06-29.json",
    "receipts/publication-manifest-2026-06-29.json",
    "receipts/publication-surface-validation-2026-06-29.json",
    "receipts/remote-proof-2026-06-29.json",
}

PUBLICATION_MANIFEST_RECEIPT = "receipts/publication-manifest-2026-06-29.json"
ACCEPTANCE_READINESS_RECEIPT = "receipts/acceptance-readiness-redteam-2026-06-29.json"

REQUIRED_4090_ENGINEERING_ARTIFACTS = [
    "engineering/4090-1b/environment.json",
    "engineering/4090-1b/train_1b_4090.py",
    "engineering/4090-1b/configs/from_scratch_1b_4090.json",
    "engineering/4090-1b/configs/pretraining_equivalent_1b_4090.json",
    "engineering/4090-1b/parse_receipts.py",
    "engineering/4090-1b/governed_probe_4090.py",
    "engineering/4090-1b/full_memory_probe_4090.py",
    "engineering/4090-1b/full_shape_block_probe_4090.py",
    "engineering/4090-1b/full_stack_step_probe_4090.py",
    "engineering/4090-1b/full_stack_lm_loss_probe_4090.py",
    "engineering/4090-1b/native_kernel_probe_4090.py",
    "engineering/4090-1b/README.md",
    "scripts/validate_4090_data_governance.py",
    "protocols/4090-data-governance-v0.md",
    "scripts/validate_4090_data_hygiene.py",
    "protocols/4090-data-hygiene-v0.md",
    "scripts/scan_c1_exact_dedup.py",
    "scripts/validate_c1_exact_dedup.py",
    "scripts/validate_c1_data_hygiene_policy.py",
    "scripts/scan_c1_local_heldout_contamination.py",
    "scripts/validate_c1_local_heldout_contamination.py",
]

REQUIRED_ACCEPTANCE_READINESS_ATTACKS = [
    "operator_acceptance_used_as_exit_ramp",
    "stale_local_commit_ref_tree_verifier_or_remote_proof",
    "self_referential_completion_lock_tree_hash",
    "acceptance_requested_before_acceptance_readiness_audit",
]

INCOMPLETE_DELIVERABLE_MARKERS = [
    "MISSING_C1_RECEIPT",
    "NOT_RUN_YET",
    "NOT_IMPORTED",
    "LOCKED_NOT_YET_SCANNED",
    "REQUIRES_ISOLATED_ENV",
    "SOURCE_PINNED_AUTH_AND_DATA_COST_DEFERRED",
    "blocked_or_access_gap_count",
    "known_execution_gaps",
    "gap audit",
    "gap-only",
    "readiness-only",
    "audit-only",
    "not yet scanned",
    "not run",
    "not imported",
    "not scanned",
    "unverified",
    "not full governed",
    "not a full governed",
    "not a near-duplicate scan",
    "not an eval-contamination scan",
    "not an eval contamination scan",
    "not a long-run training receipt",
    "not a dedupe/contamination pass",
    "not a near-duplicate/contamination PASS",
]

INCOMPLETE_MARKER_ALLOWED_CONTEXT = [
    "not overall baseline completion",
    "not overall /baseline completion",
    "overall goal completion still requires",
    "does not create operator acceptance",
    "does not complete the overall baseline",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def load_json(path: Path, failures: list[dict[str, Any]], code: str = "missing_json") -> dict[str, Any]:
    if not path.exists():
        failures.append({"code": code, "path": str(path)})
        return {}
    try:
        return json.loads(read_text(path))
    except Exception as exc:  # pragma: no cover - diagnostic path
        failures.append({"code": "invalid_json", "path": str(path), "error": str(exc)})
        return {}


def load_sources(path: Path, failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not path.exists():
        failures.append({"code": "missing_sources_jsonl", "path": str(path)})
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as fh:
        for line_no, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception as exc:
                failures.append({"code": "malformed_source_row", "line": line_no, "error": str(exc)})
                continue
            row["_line"] = line_no
            rows.append(row)
    return rows


def path_exists(root: Path, rel: str) -> bool:
    return (root / rel).exists()


def build_publication_manifest(root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(root).as_posix()
        if rel in SELF_REFERENTIAL_MANIFEST_EXCLUDES:
            continue
        files.append({"path": rel, "sha256": sha256_file(path), "size_bytes": path.stat().st_size})
    manifest_input = "\n".join(f"{row['sha256']}  {row['path']}" for row in files)
    return {
        "hash_policy": "sha256 over substantive baseline files excluding self-referential lock/proof receipts",
        "excluded_paths": sorted(SELF_REFERENTIAL_MANIFEST_EXCLUDES),
        "manifest_hash": hashlib.sha256(manifest_input.encode("utf-8")).hexdigest(),
        "file_count": len(files),
        "files": files,
    }


def check_required_paths(root: Path, failures: list[dict[str, Any]]) -> None:
    missing = [rel for rel in REQUIRED_TOP_LEVEL if not path_exists(root, rel)]
    if missing:
        failures.append({"code": "missing_required_final_paths", "paths": missing})


def check_publication_manifest(root: Path, lock: dict[str, Any], failures: list[dict[str, Any]]) -> None:
    computed = build_publication_manifest(root)
    receipt = load_json(root / PUBLICATION_MANIFEST_RECEIPT, failures, "publication_manifest_receipt_missing")
    if receipt:
        for field in ("manifest_hash", "hash_policy", "excluded_paths", "files"):
            if field not in receipt:
                failures.append({"code": "publication_manifest_missing_field", "field": field})
        if receipt.get("manifest_hash") != computed["manifest_hash"]:
            failures.append({"code": "publication_manifest_hash_mismatch", "expected": computed["manifest_hash"], "actual": receipt.get("manifest_hash")})
        if receipt.get("hash_policy") != computed["hash_policy"]:
            failures.append({"code": "publication_manifest_policy_mismatch", "expected": computed["hash_policy"], "actual": receipt.get("hash_policy")})
        if receipt.get("excluded_paths") != computed["excluded_paths"]:
            failures.append({"code": "publication_manifest_excludes_mismatch", "expected": computed["excluded_paths"], "actual": receipt.get("excluded_paths")})

    expected = f"publication-manifest-sha256:{computed['manifest_hash']}"
    promotion = lock.get("promotion") if isinstance(lock, dict) else None
    if not isinstance(promotion, dict):
        failures.append({"code": "promotion_missing_or_not_object"})
    else:
        if promotion.get("manifest_hashes") != expected:
            failures.append({"code": "promotion_manifest_hash_mismatch", "expected": expected, "actual": promotion.get("manifest_hashes")})
        if promotion.get("manifest_policy") != computed["hash_policy"]:
            failures.append({"code": "promotion_manifest_policy_mismatch", "expected": computed["hash_policy"], "actual": promotion.get("manifest_policy")})
        if promotion.get("manifest_receipt") != PUBLICATION_MANIFEST_RECEIPT:
            failures.append({"code": "promotion_manifest_receipt_missing_or_wrong", "expected": PUBLICATION_MANIFEST_RECEIPT, "actual": promotion.get("manifest_receipt")})

    for repo_field in ("public_repo", "private_repo"):
        repo = lock.get(repo_field) if isinstance(lock, dict) else None
        if not isinstance(repo, dict):
            continue
        if repo.get("baseline_manifest_hash") != computed["manifest_hash"]:
            failures.append({"code": "repo_baseline_manifest_hash_mismatch", "repo": repo_field, "expected": computed["manifest_hash"], "actual": repo.get("baseline_manifest_hash")})
        if repo.get("artifact_identity_policy") != computed["hash_policy"]:
            failures.append({"code": "repo_artifact_identity_policy_mismatch", "repo": repo_field, "expected": computed["hash_policy"], "actual": repo.get("artifact_identity_policy")})


def check_acceptance_readiness(root: Path, failures: list[dict[str, Any]]) -> None:
    receipt = load_json(root / ACCEPTANCE_READINESS_RECEIPT, failures, "acceptance_readiness_receipt_missing")
    if not receipt:
        return
    if receipt.get("verdict") != "PASS":
        failures.append({"code": "acceptance_readiness_not_pass", "actual": receipt.get("verdict")})
    if receipt.get("acceptance_requested") is not False:
        failures.append({"code": "acceptance_readiness_requested_acceptance", "actual": receipt.get("acceptance_requested")})
    attacks = receipt.get("attacks")
    if not isinstance(attacks, dict):
        failures.append({"code": "acceptance_readiness_attacks_not_object"})
        return
    for attack in REQUIRED_ACCEPTANCE_READINESS_ATTACKS:
        row = attacks.get(attack)
        if not isinstance(row, dict):
            failures.append({"code": "acceptance_readiness_attack_missing", "attack": attack})
            continue
        if row.get("verifier_must_reject") is not True or row.get("verifier_rejects") is not True:
            failures.append({"code": "acceptance_readiness_attack_not_rejected", "attack": attack, "actual": row})



def collect_family_artifacts(entry: dict[str, Any]) -> list[str]:
    rels: list[str] = []
    for field in ("contract_path", "protocol_path", "report_path", "verifier_receipt"):
        value = entry.get(field)
        if isinstance(value, str):
            rels.append(value)
    for field in ("supporting_receipts", "receipts", "artifacts"):
        values = entry.get(field)
        if isinstance(values, list):
            rels.extend(str(value) for value in values if isinstance(value, str))
    return sorted(set(rels))


def marker_is_allowed(text: str, marker: str) -> bool:
    lower = text.lower()
    marker_lower = marker.lower()
    if marker_lower not in lower:
        return False
    return any(allowed in lower for allowed in INCOMPLETE_MARKER_ALLOWED_CONTEXT) and marker_lower in {"not overall baseline completion", "not overall /baseline completion"}


def find_incomplete_markers(text: str) -> list[str]:
    hits: list[str] = []
    lower = text.lower()
    for marker in INCOMPLETE_DELIVERABLE_MARKERS:
        if marker.lower() in lower and not marker_is_allowed(text, marker):
            hits.append(marker)
    return hits


def check_family_internal_completion(root: Path, family: str, entry: dict[str, Any], failures: list[dict[str, Any]]) -> None:
    if entry.get("status") != "BASELINE_COMPLETE":
        return
    for rel in collect_family_artifacts(entry):
        path = root / rel
        if not path.exists() or path.is_dir():
            continue
        if path.suffix.lower() not in {".md", ".json", ".jsonl", ".txt"}:
            continue
        text = read_text(path)
        markers = find_incomplete_markers(text)
        if markers:
            failures.append({
                "code": "family_complete_contains_incomplete_deliverable_marker",
                "family": family,
                "path": rel,
                "markers": sorted(set(markers)),
            })

def check_lock(root: Path, lock: dict[str, Any], failures: list[dict[str, Any]]) -> None:
    if not lock:
        return
    if lock.get("status") != "COMPLETE":
        failures.append({"code": "lock_status_not_complete", "actual": lock.get("status")})
    if lock.get("scope") != "ultimate_sota_theoretical_ceiling_baseline":
        failures.append({"code": "lock_scope_not_ultimate", "actual": lock.get("scope")})

    families = lock.get("mandatory_claim_families")
    if not isinstance(families, dict):
        failures.append({"code": "mandatory_claim_families_not_object"})
        families = {}
    missing_families = [fam for fam in MANDATORY_FAMILIES if fam not in families]
    if missing_families:
        failures.append({"code": "missing_mandatory_claim_families", "families": missing_families})
    for fam in MANDATORY_FAMILIES:
        entry = families.get(fam, {}) if isinstance(families, dict) else {}
        if entry.get("status") != "BASELINE_COMPLETE":
            failures.append({"code": "family_not_baseline_complete", "family": fam, "actual": entry.get("status")})
        else:
            check_family_internal_completion(root, fam, entry, failures)
        for field in ("contract_path", "protocol_path", "report_path", "verifier_receipt", "field_relevance"):
            if not entry.get(field):
                failures.append({"code": "family_missing_lock_field", "family": fam, "field": field})
            elif field.endswith("_path") and not (root / str(entry[field])).exists():
                failures.append({"code": "family_lock_path_missing", "family": fam, "field": field, "path": entry[field]})
        receipt_rel = entry.get("verifier_receipt")
        if receipt_rel:
            receipt_path = root / str(receipt_rel)
            if not receipt_path.exists():
                failures.append({"code": "family_verifier_receipt_missing", "family": fam, "path": receipt_rel})
            else:
                try:
                    receipt = json.loads(read_text(receipt_path))
                except Exception as exc:
                    failures.append({"code": "family_verifier_receipt_invalid_json", "family": fam, "path": receipt_rel, "error": str(exc)})
                else:
                    verdict = str(receipt.get("verdict", ""))
                    if not verdict or verdict.endswith("INCOMPLETE") or verdict == "FAIL":
                        failures.append({"code": "family_verifier_receipt_not_pass", "family": fam, "path": receipt_rel, "verdict": verdict})

    acceptance = lock.get("operator_acceptance")
    if not isinstance(acceptance, dict):
        failures.append({"code": "operator_acceptance_missing_or_not_object"})
    else:
        for field in ("message_id_or_transcript_path", "timestamp_utc", "accepted_artifact_ref", "accepted_completion_lock_sha256"):
            if not acceptance.get(field):
                failures.append({"code": "operator_acceptance_missing_field", "field": field})
        transcript = acceptance.get("message_id_or_transcript_path")
        if transcript and ("ASSUMED" in str(transcript).upper() or "PROBABLY" in str(transcript).upper()):
            failures.append({"code": "operator_acceptance_is_assumed", "value": transcript})

    for repo_field in ("public_repo", "private_repo"):
        repo = lock.get(repo_field)
        if not isinstance(repo, dict):
            failures.append({"code": "repo_proof_missing", "field": repo_field})
            continue
        for field in ("remote_ref_or_pr_url", "commit_sha", "baseline_manifest_hash", "artifact_identity_policy"):
            if not repo.get(field):
                failures.append({"code": "repo_proof_missing_field", "repo": repo_field, "field": field})
        if repo.get("baseline_tree_hash") and not repo.get("baseline_manifest_hash"):
            failures.append({"code": "repo_uses_tree_hash_without_manifest", "repo": repo_field})

    verifier = lock.get("verifier")
    if not isinstance(verifier, dict):
        failures.append({"code": "verifier_lock_missing_or_not_object"})
    else:
        for field in ("command", "script_path", "script_hash", "output_receipt_path"):
            if not verifier.get(field):
                failures.append({"code": "verifier_lock_missing_field", "field": field})
        script_path = verifier.get("script_path")
        if script_path:
            actual_script = root / str(script_path)
            if not actual_script.exists():
                failures.append({"code": "verifier_script_missing", "path": str(script_path)})
            elif verifier.get("script_hash") and verifier.get("script_hash") != sha256_file(actual_script):
                failures.append({"code": "verifier_script_hash_mismatch", "expected": verifier.get("script_hash"), "actual": sha256_file(actual_script)})

    anti = lock.get("anti_cheat")
    if not isinstance(anti, dict):
        failures.append({"code": "anti_cheat_missing"})
    else:
        required_true = [
            "no_staged_only",
            "no_one_trial_only",
            "no_negative_result_only",
            "no_out_of_scope_primary_family",
            "no_proxy_transfer",
            "no_stale_sota",
            "no_missing_theoretical_ceiling",
            "no_local_only_completion",
            "no_assumed_operator_acceptance",
            "no_acceptance_exit_ramp",
            "no_self_referential_artifact_hashes",
        ]
        for key in required_true:
            if anti.get(key) is not True:
                failures.append({"code": "anti_cheat_flag_not_true", "field": key, "actual": anti.get(key)})


def check_sources(rows: list[dict[str, Any]], failures: list[dict[str, Any]]) -> None:
    ids = [row.get("id") for row in rows]
    missing = [source_id for source_id in REQUIRED_SOURCE_IDS if source_id not in ids]
    if missing:
        failures.append({"code": "missing_required_source_ids", "ids": missing})
    for row in rows:
        for field in ("id", "kind", "url", "status"):
            if not row.get(field):
                failures.append({"code": "source_missing_field", "line": row.get("_line"), "id": row.get("id"), "field": field})
        access = row.get("access_date") or row.get("accessed")
        if not access:
            failures.append({"code": "source_missing_access_date", "line": row.get("_line"), "id": row.get("id")})
        elif not re.match(r"^20\d\d-\d\d-\d\d$", str(access)):
            failures.append({"code": "source_access_date_not_iso", "line": row.get("_line"), "id": row.get("id"), "access": access})
        status = str(row.get("status", "")).lower()
        if any(term in status for term in ("deferred", "draft", "needs", "placeholder", "scope_limited_repo_commit_unpinned")):
            failures.append({"code": "source_status_not_completion_ready", "line": row.get("_line"), "id": row.get("id"), "status": row.get("status")})


def check_ceiling(root: Path, failures: list[dict[str, Any]]) -> None:
    path = root / "4090-ceiling-v0.md"
    if not path.exists():
        return
    text = read_text(path)
    missing = [phrase for phrase in CEILING_REQUIRED_PHRASES if phrase.lower() not in text.lower()]
    if missing:
        failures.append({"code": "theoretical_ceiling_missing_required_sections", "path": str(path), "missing_phrases": missing})
    if any(marker.lower() in text.lower() for marker in ("Current verdict: NOT RUN", "Status: DRAFT", "Status: INCOMPLETE", "Current Verdict\n\nINCOMPLETE", "Current verdict: INCOMPLETE")):
        failures.append({"code": "theoretical_ceiling_not_complete", "path": str(path)})
    if "theoretical/comparator baseline only" in text.lower() or "theory-only" in text.lower():
        failures.append({"code": "theoretical_ceiling_theory_only_marker_present", "path": str(path)})
    for rel in REQUIRED_4090_ENGINEERING_ARTIFACTS:
        if not (root / rel).exists():
            failures.append({"code": "theoretical_ceiling_engineering_artifact_missing", "path": rel})


def check_forbidden_terms(root: Path, failures: list[dict[str, Any]]) -> None:
    critical = [
        "README.md",
        "reports/report-v0.md",
        "completion-lock.json",
        "claim-map-v0.md",
        "4090-ceiling-v0.md",
        "field-level-threshold-v0.md",
    ]
    hits = []
    for rel in critical:
        path = root / rel
        if not path.exists():
            continue
        text = read_text(path)
        for term in FORBIDDEN_COMPLETION_TERMS:
            if term in text:
                hits.append({"path": rel, "term": term})
    if hits:
        failures.append({"code": "forbidden_completion_terms_present", "hits": hits})


def check_line_endings(root: Path, failures: list[dict[str, Any]]) -> None:
    mixed = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".md", ".json", ".jsonl", ".py", ".txt", ".yml", ".yaml", ".toml"}:
            continue
        data = path.read_bytes()
        crlf = data.count(b"\r\n")
        lf = data.count(b"\n") - crlf
        cr = data.count(b"\r") - crlf
        if cr or (crlf and lf):
            mixed.append(str(path.relative_to(root)))
    if mixed:
        failures.append({"code": "mixed_line_endings", "paths": mixed})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    failures: list[dict[str, Any]] = []
    if not root.exists():
        failures.append({"code": "root_missing", "root": str(root)})
    else:
        check_required_paths(root, failures)
        lock = load_json(root / "completion-lock.json", failures, "missing_completion_lock")
        check_lock(root, lock, failures)
        check_publication_manifest(root, lock, failures)
        check_acceptance_readiness(root, failures)
        rows = load_sources(root / "sources.jsonl", failures)
        check_sources(rows, failures)
        check_ceiling(root, failures)
        check_forbidden_terms(root, failures)
        check_line_endings(root, failures)

    result = {
        "verdict": "PASS" if not failures else "FAIL",
        "root": str(root),
        "goal": "ultimate_sota_theoretical_ceiling_baseline",
        "checked_at_local_date": date.today().isoformat(),
        "failure_count": len(failures),
        "failures": failures,
        "verifier_sha256": sha256_file(Path(__file__)),
    }
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
