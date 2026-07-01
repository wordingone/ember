#!/usr/bin/env python3
"""Validate C1 data-hygiene gap audit.

This validator intentionally accepts only an explicit blocking-gap audit. It does
not permit adjacent source-pin or task-heldout receipts to become a C1 dedupe or
contamination PASS.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPECTED_VERDICT = "C1_DATA_HYGIENE_AUDIT_READY_WITH_BLOCKING_GAPS"
REQUIRED_GAPS = {
    "corpus_wide_near_duplicate_or_minhash_scan",
    "eval_suite_contamination_scan",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    failures: list[dict[str, Any]] = []
    receipt_path = root / "receipts/4090-data-hygiene-audit-2026-06-30.json"
    protocol_path = root / "protocols/4090-data-hygiene-v0.md"
    receipt = read_json(receipt_path) if receipt_path.exists() else {}
    if receipt.get("verdict") != EXPECTED_VERDICT:
        failures.append({"code": "hygiene_audit_bad_verdict", "actual": receipt.get("verdict")})
    if not protocol_path.exists() or "Status: GAP AUDIT, NOT COMPLETION" not in protocol_path.read_text(encoding="utf-8-sig", errors="replace"):
        failures.append({"code": "protocol_missing_gap_audit_guard"})
    audited = receipt.get("audited_sources", {})
    for key in ("corpus_assembly", "token_shards", "tokenizer_freeze", "byte_stability", "task_fold_duplicate_discipline", "policy_thresholds", "policy_thresholds_validation", "local_heldout_16gram_contamination_scan", "local_heldout_16gram_contamination_validation", "eval_text_inventory_normalized_span_scan", "eval_text_inventory_normalized_span_validation", "near_duplicate_minhash_sample_scan", "near_duplicate_minhash_sample_validation", "near_duplicate_sample_remediation", "near_duplicate_sample_remediation_validation", "near_duplicate_targeted_expansion", "near_duplicate_targeted_expansion_validation", "near_duplicate_targeted_exclusion_manifest", "near_duplicate_targeted_exclusion_manifest_validation", "targeted_filtered_corpus_view", "targeted_filtered_corpus_view_validation", "targeted_filtered_near_duplicate_sample", "targeted_filtered_near_duplicate_sample_validation", "targeted_filtered_challenge_remediation", "targeted_filtered_challenge_remediation_validation", "near_duplicate_cumulative_exclusion_manifest_v2", "near_duplicate_cumulative_exclusion_manifest_v2_validation", "cumulative_filtered_corpus_view_v2", "cumulative_filtered_corpus_view_v2_validation", "cumulative_filtered_near_duplicate_sample_v2", "cumulative_filtered_near_duplicate_sample_v2_validation", "cumulative_filtered_challenge_remediation_v3", "cumulative_filtered_challenge_remediation_v3_validation", "near_duplicate_cumulative_exclusion_manifest_v3", "near_duplicate_cumulative_exclusion_manifest_v3_validation", "cumulative_filtered_corpus_view_v3", "cumulative_filtered_corpus_view_v3_validation", "cumulative_filtered_near_duplicate_sample_v3", "cumulative_filtered_near_duplicate_sample_v3_validation", "cumulative_filtered_challenge_remediation_v4", "cumulative_filtered_challenge_remediation_v4_validation", "near_duplicate_cumulative_exclusion_manifest_v4", "near_duplicate_cumulative_exclusion_manifest_v4_validation", "cumulative_filtered_corpus_view_v4", "cumulative_filtered_corpus_view_v4_validation", "cumulative_filtered_near_duplicate_sample_v4", "cumulative_filtered_near_duplicate_sample_v4_validation", "cumulative_filtered_lsh_bucket_census_v4", "cumulative_filtered_lsh_bucket_census_v4_validation", "cumulative_filtered_lsh_bucket_census_v4_band4", "cumulative_filtered_lsh_bucket_census_v4_band4_validation", "cumulative_filtered_lsh_bucket_census_v4_band8", "cumulative_filtered_lsh_bucket_census_v4_band8_validation", "cumulative_filtered_lsh_bucket_census_v4_band12", "cumulative_filtered_lsh_bucket_census_v4_band12_validation", "cumulative_filtered_lsh_bucket_census_v4_band16", "cumulative_filtered_lsh_bucket_census_v4_band16_validation", "cumulative_filtered_lsh_bucket_census_v4_band20", "cumulative_filtered_lsh_bucket_census_v4_band20_validation", "cumulative_filtered_lsh_bucket_census_v4_band24", "cumulative_filtered_lsh_bucket_census_v4_band24_validation", "cumulative_filtered_lsh_bucket_census_v4_band28", "cumulative_filtered_lsh_bucket_census_v4_band28_validation", "cumulative_filtered_lsh_bucket_census_v4_band32", "cumulative_filtered_lsh_bucket_census_v4_band32_validation", "cumulative_filtered_lsh_bucket_census_v4_band60", "cumulative_filtered_lsh_bucket_census_v4_band60_validation", "cumulative_filtered_lsh_bucket_census_v4_band56", "cumulative_filtered_lsh_bucket_census_v4_band56_validation", "cumulative_filtered_lsh_bucket_census_v4_band52", "cumulative_filtered_lsh_bucket_census_v4_band52_validation", "cumulative_filtered_lsh_bucket_census_v4_band48", "cumulative_filtered_lsh_bucket_census_v4_band48_validation", "cumulative_filtered_lsh_bucket_census_v4_band44", "cumulative_filtered_lsh_bucket_census_v4_band44_validation", "cumulative_filtered_lsh_bucket_census_v4_band40", "cumulative_filtered_lsh_bucket_census_v4_band40_validation", "cumulative_filtered_lsh_bucket_census_v4_band36", "cumulative_filtered_lsh_bucket_census_v4_band36_validation", "cumulative_filtered_lsh_candidate_index_v4_band48", "cumulative_filtered_lsh_candidate_index_v4_band48_validation", "cumulative_filtered_lsh_candidate_index_v4_band48_fragment", "cumulative_filtered_lsh_candidate_index_v4_band48_adjudication_partial25", "near_duplicate_cumulative_exclusion_manifest_v5", "near_duplicate_cumulative_exclusion_manifest_v5_validation", "near_duplicate_cumulative_exclusion_manifest_v5_fragment", "cumulative_filtered_corpus_view_v5", "cumulative_filtered_corpus_view_v5_validation", "cumulative_filtered_lsh_candidate_index_v5_band48", "cumulative_filtered_lsh_candidate_index_v5_band48_validation", "cumulative_filtered_lsh_candidate_index_v5_band48_fragment", "cumulative_filtered_lsh_candidate_index_v5_band48_adjudication_partial25", "cumulative_filtered_lsh_candidate_index_v5_band48_adjudication_partial25_validation", "cumulative_filtered_lsh_candidate_index_v5_band48_adjudication_partial25_remediation", "near_duplicate_cumulative_exclusion_manifest_v6", "near_duplicate_cumulative_exclusion_manifest_v6_validation", "near_duplicate_cumulative_exclusion_manifest_v6_fragment", "cumulative_filtered_corpus_view_v6", "cumulative_filtered_corpus_view_v6_validation", "cumulative_filtered_lsh_candidate_index_v6_band48", "cumulative_filtered_lsh_candidate_index_v6_band48_validation", "cumulative_filtered_lsh_candidate_index_v6_band48_fragment", "cumulative_filtered_lsh_candidate_index_v6_band48_adjudication_partial25", "cumulative_filtered_lsh_candidate_index_v6_band48_adjudication_partial25_validation", "cumulative_filtered_lsh_candidate_index_v6_band48_adjudication_partial25_remediation", "near_duplicate_cumulative_exclusion_manifest_v7", "near_duplicate_cumulative_exclusion_manifest_v7_validation", "near_duplicate_cumulative_exclusion_manifest_v7_fragment", "cumulative_filtered_corpus_view_v7", "cumulative_filtered_corpus_view_v7_validation", "cumulative_filtered_lsh_candidate_index_v7_band48", "cumulative_filtered_lsh_candidate_index_v7_band48_validation", "cumulative_filtered_lsh_candidate_index_v7_band48_fragment", "cumulative_filtered_lsh_candidate_index_v7_band48_adjudication_partial25", "cumulative_filtered_lsh_candidate_index_v7_band48_adjudication_partial25_validation", "cumulative_filtered_lsh_candidate_index_v7_band48_adjudication_partial25_remediation", "near_duplicate_cumulative_exclusion_manifest_v8", "near_duplicate_cumulative_exclusion_manifest_v8_validation", "near_duplicate_cumulative_exclusion_manifest_v8_fragment", "cumulative_filtered_corpus_view_v8", "cumulative_filtered_corpus_view_v8_validation", "cumulative_filtered_lsh_candidate_index_v8_band48", "cumulative_filtered_lsh_candidate_index_v8_band48_validation", "cumulative_filtered_lsh_candidate_index_v8_band48_fragment", "cumulative_filtered_lsh_candidate_index_v8_band48_adjudication_partial25_skip0", "cumulative_filtered_lsh_candidate_index_v8_band48_adjudication_partial25_skip0_validation", "cumulative_filtered_lsh_candidate_index_v8_band48_adjudication_partial25_skip25", "cumulative_filtered_lsh_candidate_index_v8_band48_adjudication_partial25_skip25_validation", "cumulative_filtered_lsh_candidate_index_v8_band48_adjudication_window50_remediation", "near_duplicate_cumulative_exclusion_manifest_v9", "near_duplicate_cumulative_exclusion_manifest_v9_validation", "near_duplicate_cumulative_exclusion_manifest_v9_fragment", "cumulative_filtered_corpus_view_v9", "cumulative_filtered_corpus_view_v9_validation", "cumulative_filtered_lsh_candidate_index_v9_band48", "cumulative_filtered_lsh_candidate_index_v9_band48_validation", "cumulative_filtered_lsh_candidate_index_v9_band48_fragment", "cumulative_filtered_lsh_candidate_index_v9_band48_adjudication_partial25_skip0", "cumulative_filtered_lsh_candidate_index_v9_band48_adjudication_partial25_skip0_validation", "cumulative_filtered_lsh_candidate_index_v9_band48_adjudication_partial25_skip25", "cumulative_filtered_lsh_candidate_index_v9_band48_adjudication_partial25_skip25_validation", "cumulative_filtered_lsh_candidate_index_v9_band48_adjudication_partial25_skip50", "cumulative_filtered_lsh_candidate_index_v9_band48_adjudication_partial25_skip50_validation", "cumulative_filtered_lsh_candidate_index_v9_band48_adjudication_partial25_skip75", "cumulative_filtered_lsh_candidate_index_v9_band48_adjudication_partial25_skip75_validation", "cumulative_filtered_lsh_candidate_index_v9_band48_adjudication_window100_remediation", "near_duplicate_cumulative_exclusion_manifest_v10", "near_duplicate_cumulative_exclusion_manifest_v10_validation", "near_duplicate_cumulative_exclusion_manifest_v10_fragment", "cumulative_filtered_corpus_view_v10", "cumulative_filtered_corpus_view_v10_validation", "cumulative_filtered_lsh_candidate_index_v10_band48", "cumulative_filtered_lsh_candidate_index_v10_band48_validation", "cumulative_filtered_lsh_candidate_index_v10_band48_fragment", "cumulative_filtered_lsh_candidate_index_v10_band48_adjudication_partial25_skip0", "cumulative_filtered_lsh_candidate_index_v10_band48_adjudication_partial25_skip0_validation", "cumulative_filtered_lsh_candidate_index_v10_band48_adjudication_partial25_skip25", "cumulative_filtered_lsh_candidate_index_v10_band48_adjudication_partial25_skip25_validation", "cumulative_filtered_lsh_candidate_index_v10_band48_adjudication_partial25_skip50", "cumulative_filtered_lsh_candidate_index_v10_band48_adjudication_partial25_skip50_validation", "cumulative_filtered_lsh_candidate_index_v10_band48_adjudication_partial25_skip75", "cumulative_filtered_lsh_candidate_index_v10_band48_adjudication_partial25_skip75_validation", "cumulative_filtered_lsh_candidate_index_v10_band48_adjudication_partial25_skip100", "cumulative_filtered_lsh_candidate_index_v10_band48_adjudication_partial25_skip100_validation", "cumulative_filtered_lsh_candidate_index_v10_band48_adjudication_window125_remediation", "near_duplicate_cumulative_exclusion_manifest_v11", "near_duplicate_cumulative_exclusion_manifest_v11_validation", "near_duplicate_cumulative_exclusion_manifest_v11_fragment", "cumulative_filtered_corpus_view_v11", "cumulative_filtered_corpus_view_v11_validation", "cumulative_filtered_lsh_candidate_index_v11_band48", "cumulative_filtered_lsh_candidate_index_v11_band48_validation", "cumulative_filtered_lsh_candidate_index_v11_band48_fragment", "cumulative_filtered_lsh_candidate_index_v11_band48_adjudication_partial25_skip0", "cumulative_filtered_lsh_candidate_index_v11_band48_adjudication_partial25_skip0_validation", "cumulative_filtered_lsh_candidate_index_v11_band48_adjudication_partial25_skip25", "cumulative_filtered_lsh_candidate_index_v11_band48_adjudication_partial25_skip25_validation", "cumulative_filtered_lsh_candidate_index_v11_band48_adjudication_partial25_skip50", "cumulative_filtered_lsh_candidate_index_v11_band48_adjudication_partial25_skip50_validation", "cumulative_filtered_lsh_candidate_index_v11_band48_adjudication_partial25_skip75", "cumulative_filtered_lsh_candidate_index_v11_band48_adjudication_partial25_skip75_validation", "cumulative_filtered_lsh_candidate_index_v11_band48_adjudication_partial25_skip100", "cumulative_filtered_lsh_candidate_index_v11_band48_adjudication_partial25_skip100_validation", "cumulative_filtered_lsh_candidate_index_v11_band48_adjudication_partial25_skip125", "cumulative_filtered_lsh_candidate_index_v11_band48_adjudication_partial25_skip125_validation", "cumulative_filtered_lsh_candidate_index_v11_band48_adjudication_window150_remediation", "near_duplicate_cumulative_exclusion_manifest_v12", "near_duplicate_cumulative_exclusion_manifest_v12_validation", "near_duplicate_cumulative_exclusion_manifest_v12_fragment", "cumulative_filtered_corpus_view_v12", "cumulative_filtered_corpus_view_v12_validation", "cumulative_filtered_lsh_candidate_index_v12_band48", "cumulative_filtered_lsh_candidate_index_v12_band48_validation", "cumulative_filtered_lsh_candidate_index_v12_band48_fragment", "cumulative_filtered_lsh_candidate_index_v12_band48_adjudication_partial25_skip0", "cumulative_filtered_lsh_candidate_index_v12_band48_adjudication_partial25_skip0_validation", "cumulative_filtered_lsh_candidate_index_v12_band48_adjudication_partial25_skip25", "cumulative_filtered_lsh_candidate_index_v12_band48_adjudication_partial25_skip25_validation", "cumulative_filtered_lsh_candidate_index_v12_band48_adjudication_partial25_skip50", "cumulative_filtered_lsh_candidate_index_v12_band48_adjudication_partial25_skip50_validation", "cumulative_filtered_lsh_candidate_index_v12_band48_adjudication_partial25_skip75", "cumulative_filtered_lsh_candidate_index_v12_band48_adjudication_partial25_skip75_validation", "cumulative_filtered_lsh_candidate_index_v12_band48_adjudication_partial25_skip100", "cumulative_filtered_lsh_candidate_index_v12_band48_adjudication_partial25_skip100_validation", "cumulative_filtered_lsh_candidate_index_v12_band48_adjudication_partial25_skip125", "cumulative_filtered_lsh_candidate_index_v12_band48_adjudication_partial25_skip125_validation", "cumulative_filtered_lsh_candidate_index_v12_band48_adjudication_partial25_skip150", "cumulative_filtered_lsh_candidate_index_v12_band48_adjudication_partial25_skip150_validation", "cumulative_filtered_lsh_candidate_index_v12_band48_adjudication_window175_remediation", "near_duplicate_cumulative_exclusion_manifest_v13", "near_duplicate_cumulative_exclusion_manifest_v13_validation", "near_duplicate_cumulative_exclusion_manifest_v13_fragment", "cumulative_filtered_corpus_view_v13", "cumulative_filtered_corpus_view_v13_validation", "cumulative_filtered_lsh_candidate_index_v13_band48", "cumulative_filtered_lsh_candidate_index_v13_band48_validation", "cumulative_filtered_lsh_candidate_index_v13_band48_fragment", "cumulative_filtered_lsh_candidate_index_v13_band48_adjudication_partial25_skip0", "cumulative_filtered_lsh_candidate_index_v13_band48_adjudication_partial25_skip0_validation", "cumulative_filtered_lsh_candidate_index_v13_band48_adjudication_partial25_skip25", "cumulative_filtered_lsh_candidate_index_v13_band48_adjudication_partial25_skip25_validation", "cumulative_filtered_lsh_candidate_index_v13_band48_adjudication_partial25_skip50", "cumulative_filtered_lsh_candidate_index_v13_band48_adjudication_partial25_skip50_validation", "cumulative_filtered_lsh_candidate_index_v13_band48_adjudication_partial25_skip75", "cumulative_filtered_lsh_candidate_index_v13_band48_adjudication_partial25_skip75_validation", "cumulative_filtered_lsh_candidate_index_v13_band48_adjudication_partial25_skip100", "cumulative_filtered_lsh_candidate_index_v13_band48_adjudication_partial25_skip100_validation", "cumulative_filtered_lsh_candidate_index_v13_band48_adjudication_partial25_skip125", "cumulative_filtered_lsh_candidate_index_v13_band48_adjudication_partial25_skip125_validation", "cumulative_filtered_lsh_candidate_index_v13_band48_adjudication_partial25_skip150", "cumulative_filtered_lsh_candidate_index_v13_band48_adjudication_partial25_skip150_validation", "cumulative_filtered_lsh_candidate_index_v13_band48_adjudication_partial25_skip175", "cumulative_filtered_lsh_candidate_index_v13_band48_adjudication_partial25_skip175_validation", "cumulative_filtered_lsh_candidate_index_v13_band48_adjudication_window200_remediation", "near_duplicate_cumulative_exclusion_manifest_v14", "near_duplicate_cumulative_exclusion_manifest_v14_validation", "near_duplicate_cumulative_exclusion_manifest_v14_fragment", "cumulative_filtered_corpus_view_v14", "cumulative_filtered_corpus_view_v14_validation", "cumulative_filtered_lsh_candidate_index_v14_band48", "cumulative_filtered_lsh_candidate_index_v14_band48_validation", "cumulative_filtered_lsh_candidate_index_v14_band48_fragment", "cumulative_filtered_lsh_candidate_index_v14_band48_adjudication_partial25_skip0", "cumulative_filtered_lsh_candidate_index_v14_band48_adjudication_partial25_skip0_validation", "cumulative_filtered_lsh_candidate_index_v14_band48_adjudication_partial25_skip25", "cumulative_filtered_lsh_candidate_index_v14_band48_adjudication_partial25_skip25_validation", "cumulative_filtered_lsh_candidate_index_v14_band48_adjudication_partial25_skip50", "cumulative_filtered_lsh_candidate_index_v14_band48_adjudication_partial25_skip50_validation", "cumulative_filtered_lsh_candidate_index_v14_band48_adjudication_partial25_skip75", "cumulative_filtered_lsh_candidate_index_v14_band48_adjudication_partial25_skip75_validation", "cumulative_filtered_lsh_candidate_index_v14_band48_adjudication_partial25_skip100", "cumulative_filtered_lsh_candidate_index_v14_band48_adjudication_partial25_skip100_validation", "cumulative_filtered_lsh_candidate_index_v14_band48_adjudication_partial25_skip125", "cumulative_filtered_lsh_candidate_index_v14_band48_adjudication_partial25_skip125_validation", "cumulative_filtered_lsh_candidate_index_v14_band48_adjudication_partial25_skip150", "cumulative_filtered_lsh_candidate_index_v14_band48_adjudication_partial25_skip150_validation", "cumulative_filtered_lsh_candidate_index_v14_band48_adjudication_partial25_skip175", "cumulative_filtered_lsh_candidate_index_v14_band48_adjudication_partial25_skip175_validation", "cumulative_filtered_lsh_candidate_index_v14_band48_adjudication_partial25_skip200", "cumulative_filtered_lsh_candidate_index_v14_band48_adjudication_partial25_skip200_validation", "cumulative_filtered_lsh_candidate_index_v14_band48_adjudication_window225_remediation", "near_duplicate_cumulative_exclusion_manifest_v15", "near_duplicate_cumulative_exclusion_manifest_v15_validation", "near_duplicate_cumulative_exclusion_manifest_v15_fragment", "cumulative_filtered_corpus_view_v15", "cumulative_filtered_corpus_view_v15_validation"):
        row = audited.get(key, {})
        if not row.get("repo_path") or not row.get("sha256"):
            failures.append({"code": "audited_source_missing_pin", "key": key, "row": row})
    positive = receipt.get("positive_evidence", {})
    if positive.get("byte_stability_dedup_views_match") is not True:
        failures.append({"code": "byte_stability_dedup_views_not_matched", "actual": positive.get("byte_stability_dedup_views_match")})
    if positive.get("task_fold_duplicate_episode_srcs") != 0:
        failures.append({"code": "task_fold_duplicate_episode_srcs_nonzero", "actual": positive.get("task_fold_duplicate_episode_srcs")})
    exact = positive.get("corpus_wide_exact_document_dedupe", {})
    if exact.get("verdict") != "C1_EXACT_DEDUPE_VALIDATED" or exact.get("duplicate_documents") != 0:
        failures.append({"code": "exact_document_dedupe_not_validated", "actual": exact})
    policy = positive.get("policy_thresholds", {})
    if policy.get("verdict") != "C1_DATA_HYGIENE_POLICY_THRESHOLDS_VALIDATED":
        failures.append({"code": "policy_thresholds_not_validated", "actual": policy})
    local_contam = positive.get("local_heldout_exact_32gram_contamination", {})
    if local_contam.get("verdict") != "C1_LOCAL_HELDOUT_CONTAMINATION_VALIDATED" or local_contam.get("exact_32_token_hits") != 0:
        failures.append({"code": "local_heldout_contamination_not_validated", "actual": local_contam})
    local_16 = positive.get("local_heldout_exact_16gram_contamination", {})
    if local_16.get("verdict") != "C1_LOCAL_HELDOUT_16GRAM_CONTAMINATION_VALIDATED" or local_16.get("exact_16_token_hits") != 0:
        failures.append({"code": "local_heldout_16gram_contamination_not_validated", "actual": local_16})
    eval_inventory = positive.get("available_eval_text_normalized_span_local_surface_scan", {})
    if eval_inventory.get("verdict") != "C1_EVAL_TEXT_INVENTORY_VALIDATED_WITH_BLOCKING_FULL_SUITE_GAP" or eval_inventory.get("exact_normalized_span_hits") != 0:
        failures.append({"code": "eval_text_inventory_not_validated", "actual": eval_inventory})
    if eval_inventory.get("blocks_full_eval_suite_pass") is not True or "not full external" not in str(eval_inventory.get("scope_limit", "")):
        failures.append({"code": "eval_text_inventory_missing_noncompletion_guard", "actual": eval_inventory})
    near_sample = positive.get("near_duplicate_minhash_bounded_sample", {})
    if near_sample.get("validation_verdict") != "C1_NEAR_DUPLICATE_SAMPLE_VALIDATED":
        failures.append({"code": "near_duplicate_sample_not_validated", "actual": near_sample})
    if near_sample.get("verdict") != "C1_NEAR_DUPLICATE_SAMPLE_CANDIDATES_FOUND":
        failures.append({"code": "near_duplicate_sample_verdict_unexpected", "actual": near_sample.get("verdict")})
    if near_sample.get("sampled_documents", 0) < 50000 or near_sample.get("documents_seen") != 4236458:
        failures.append({"code": "near_duplicate_sample_scope_mismatch", "actual": near_sample})
    if near_sample.get("crossing_pair_count", 0) < 1 or near_sample.get("max_exact_jaccard_observed", 0) < 0.8:
        failures.append({"code": "near_duplicate_sample_problem_not_recorded", "actual": near_sample})
    if "full corpus remediation" not in str(near_sample.get("scope_limit", "")):
        failures.append({"code": "near_duplicate_sample_missing_noncompletion_guard", "actual": near_sample.get("scope_limit")})
    sample_remediation = positive.get("near_duplicate_sample_remediation", {})
    if sample_remediation.get("verdict") != "C1_NEAR_DUPLICATE_SAMPLE_REMEDIATION_VALIDATED":
        failures.append({"code": "near_duplicate_sample_remediation_not_validated", "actual": sample_remediation})
    if sample_remediation.get("sample_exclusion_document_count", 0) < 1 or sample_remediation.get("sample_exclusion_token_floor", 0) < 1:
        failures.append({"code": "near_duplicate_sample_remediation_empty", "actual": sample_remediation})
    if "full-corpus exclusion materialization" not in str(sample_remediation.get("scope_limit", "")):
        failures.append({"code": "near_duplicate_sample_remediation_missing_noncompletion_guard", "actual": sample_remediation.get("scope_limit")})
    targeted_expansion = positive.get("near_duplicate_targeted_expansion", {})
    if targeted_expansion.get("verdict") != "C1_NEAR_DUPLICATE_TARGETED_EXPANSION_VALIDATED":
        failures.append({"code": "near_duplicate_targeted_expansion_not_validated", "actual": targeted_expansion})
    if targeted_expansion.get("documents_seen") != 4236458 or targeted_expansion.get("expanded_exclusion_document_count", 0) < sample_remediation.get("sample_exclusion_document_count", 0):
        failures.append({"code": "near_duplicate_targeted_expansion_scope_mismatch", "actual": targeted_expansion})
    if targeted_expansion.get("missing_sample_exclusions") not in ([], None):
        failures.append({"code": "near_duplicate_targeted_expansion_missing_sample_exclusions", "actual": targeted_expansion.get("missing_sample_exclusions")})
    if "all-pairs near-duplicate scan" not in str(targeted_expansion.get("scope_limit", "")):
        failures.append({"code": "near_duplicate_targeted_expansion_missing_noncompletion_guard", "actual": targeted_expansion.get("scope_limit")})
    targeted_manifest = positive.get("near_duplicate_targeted_exclusion_manifest", {})
    if targeted_manifest.get("verdict") != "C1_NEAR_DUPLICATE_TARGETED_EXCLUSION_MANIFEST_VALIDATED":
        failures.append({"code": "near_duplicate_targeted_exclusion_manifest_not_validated", "actual": targeted_manifest})
    if targeted_manifest.get("exclusion_document_count") != targeted_expansion.get("expanded_exclusion_document_count") or targeted_manifest.get("exclusion_token_floor") != targeted_expansion.get("expanded_exclusion_token_floor"):
        failures.append({"code": "near_duplicate_targeted_exclusion_manifest_scope_mismatch", "actual": targeted_manifest, "targeted_expansion": targeted_expansion})
    if "not an all-pairs near-duplicate PASS" not in str(targeted_manifest.get("scope_limit", "")):
        failures.append({"code": "near_duplicate_targeted_exclusion_manifest_missing_noncompletion_guard", "actual": targeted_manifest.get("scope_limit")})
    filtered_view = positive.get("targeted_filtered_corpus_view", {})
    if filtered_view.get("verdict") != "C1_TARGETED_FILTERED_CORPUS_VIEW_VALIDATED":
        failures.append({"code": "targeted_filtered_corpus_view_not_validated", "actual": filtered_view})
    if filtered_view.get("excluded_document_count") != targeted_manifest.get("exclusion_document_count") or filtered_view.get("excluded_token_floor") != targeted_manifest.get("exclusion_token_floor"):
        failures.append({"code": "targeted_filtered_corpus_view_scope_mismatch", "actual": filtered_view, "targeted_manifest": targeted_manifest})
    if filtered_view.get("binary_shards_rewritten") is not False or "not an all-pairs near-duplicate PASS" not in str(filtered_view.get("scope_limit", "")):
        failures.append({"code": "targeted_filtered_corpus_view_noncompletion_guard_missing", "actual": filtered_view})
    challenge = positive.get("targeted_filtered_near_duplicate_challenge_sample", {})
    if challenge.get("verdict") != "C1_TARGETED_FILTERED_NEAR_DUPLICATE_SAMPLE_VALIDATED":
        failures.append({"code": "targeted_filtered_near_duplicate_challenge_not_validated", "actual": challenge})
    if challenge.get("documents_seen") != 4236458 or challenge.get("sampled_documents", 0) < 50000:
        failures.append({"code": "targeted_filtered_near_duplicate_challenge_scope_mismatch", "actual": challenge})
    if challenge.get("sampled_excluded_document_count") != 0 or challenge.get("excluded_document_count") != targeted_manifest.get("exclusion_document_count"):
        failures.append({"code": "targeted_filtered_near_duplicate_challenge_exclusion_mismatch", "actual": challenge, "targeted_manifest": targeted_manifest})
    if challenge.get("crossing_pair_count", 0) < 1 or challenge.get("max_exact_jaccard_observed", 0) < 0.8:
        failures.append({"code": "targeted_filtered_near_duplicate_challenge_problem_not_recorded", "actual": challenge})
    if "all-pairs near-duplicate scan/remediation" not in str(challenge.get("scope_limit", "")):
        failures.append({"code": "targeted_filtered_near_duplicate_challenge_missing_noncompletion_guard", "actual": challenge.get("scope_limit")})
    challenge_remediation = positive.get("targeted_filtered_challenge_remediation", {})
    if challenge_remediation.get("verdict") != "C1_TARGETED_FILTERED_CHALLENGE_REMEDIATION_VALIDATED":
        failures.append({"code": "targeted_filtered_challenge_remediation_not_validated", "actual": challenge_remediation})
    if challenge_remediation.get("input_crossing_pair_count") != challenge.get("crossing_pair_count"):
        failures.append({"code": "targeted_filtered_challenge_remediation_input_mismatch", "actual": challenge_remediation, "challenge": challenge})
    if challenge_remediation.get("challenge_exclusion_document_count", 0) < 1 or challenge_remediation.get("challenge_exclusion_token_floor", 0) < 1:
        failures.append({"code": "targeted_filtered_challenge_remediation_empty", "actual": challenge_remediation})
    if challenge_remediation.get("existing_targeted_manifest_overlap_count") != 0:
        failures.append({"code": "targeted_filtered_challenge_remediation_overlap", "actual": challenge_remediation})
    if "all-pairs/full-corpus PASS remains required" not in str(challenge_remediation.get("scope_limit", "")):
        failures.append({"code": "targeted_filtered_challenge_remediation_missing_noncompletion_guard", "actual": challenge_remediation.get("scope_limit")})
    cumulative_manifest = positive.get("near_duplicate_cumulative_exclusion_manifest_v2", {})
    if cumulative_manifest.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V2_VALIDATED":
        failures.append({"code": "near_duplicate_cumulative_manifest_v2_not_validated", "actual": cumulative_manifest})
    if cumulative_manifest.get("exclusion_document_count") != 1693 or cumulative_manifest.get("exclusion_token_floor") != 2988224 or cumulative_manifest.get("source_overlap_count") != 0:
        failures.append({"code": "near_duplicate_cumulative_manifest_v2_scope_mismatch", "actual": cumulative_manifest})
    cumulative_view = positive.get("cumulative_filtered_corpus_view_v2", {})
    if cumulative_view.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V2_VALIDATED":
        failures.append({"code": "cumulative_filtered_view_v2_not_validated", "actual": cumulative_view})
    if cumulative_view.get("excluded_document_count") != 1693 or cumulative_view.get("remaining_document_count") != 4234765 or cumulative_view.get("binary_shards_rewritten") is not False:
        failures.append({"code": "cumulative_filtered_view_v2_scope_mismatch", "actual": cumulative_view})
    cumulative_challenge = positive.get("cumulative_filtered_near_duplicate_challenge_sample_v2", {})
    if cumulative_challenge.get("verdict") != "C1_CUMULATIVE_FILTERED_NEAR_DUPLICATE_SAMPLE_V2_VALIDATED":
        failures.append({"code": "cumulative_filtered_challenge_v2_not_validated", "actual": cumulative_challenge})
    if cumulative_challenge.get("sampled_documents", 0) < 50000 or cumulative_challenge.get("sampled_excluded_document_count") != 0:
        failures.append({"code": "cumulative_filtered_challenge_v2_scope_mismatch", "actual": cumulative_challenge})
    if cumulative_challenge.get("crossing_pair_count", 0) < 1 or cumulative_challenge.get("max_exact_jaccard_observed", 0) < 0.8:
        failures.append({"code": "cumulative_filtered_challenge_v2_problem_not_recorded", "actual": cumulative_challenge})
    if "all-pairs near-duplicate scan/remediation" not in str(cumulative_challenge.get("scope_limit", "")):
        failures.append({"code": "cumulative_filtered_challenge_v2_missing_noncompletion_guard", "actual": cumulative_challenge.get("scope_limit")})
    remediation_v3 = positive.get("cumulative_filtered_challenge_remediation_v3", {})
    if remediation_v3.get("verdict") != "C1_CUMULATIVE_FILTERED_CHALLENGE_REMEDIATION_V3_VALIDATED":
        failures.append({"code": "cumulative_filtered_challenge_remediation_v3_not_validated", "actual": remediation_v3})
    if remediation_v3.get("input_crossing_pair_count") != cumulative_challenge.get("crossing_pair_count") or remediation_v3.get("challenge_exclusion_document_count") != 16 or remediation_v3.get("existing_targeted_manifest_overlap_count") != 0:
        failures.append({"code": "cumulative_filtered_challenge_remediation_v3_scope_mismatch", "actual": remediation_v3, "challenge_v2": cumulative_challenge})
    if "all-pairs/full-corpus PASS remains required" not in str(remediation_v3.get("scope_limit", "")):
        failures.append({"code": "cumulative_filtered_challenge_remediation_v3_missing_noncompletion_guard", "actual": remediation_v3.get("scope_limit")})
    cumulative_manifest_v3 = positive.get("near_duplicate_cumulative_exclusion_manifest_v3", {})
    if cumulative_manifest_v3.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V3_VALIDATED":
        failures.append({"code": "near_duplicate_cumulative_manifest_v3_not_validated", "actual": cumulative_manifest_v3})
    if cumulative_manifest_v3.get("exclusion_document_count") != 1709 or cumulative_manifest_v3.get("exclusion_token_floor") != 3012037 or cumulative_manifest_v3.get("source_overlap_count") != 0:
        failures.append({"code": "near_duplicate_cumulative_manifest_v3_scope_mismatch", "actual": cumulative_manifest_v3})
    cumulative_view_v3 = positive.get("cumulative_filtered_corpus_view_v3", {})
    if cumulative_view_v3.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V3_VALIDATED":
        failures.append({"code": "cumulative_filtered_view_v3_not_validated", "actual": cumulative_view_v3})
    if cumulative_view_v3.get("excluded_document_count") != 1709 or cumulative_view_v3.get("remaining_document_count") != 4234749 or cumulative_view_v3.get("binary_shards_rewritten") is not False:
        failures.append({"code": "cumulative_filtered_view_v3_scope_mismatch", "actual": cumulative_view_v3})
    cumulative_challenge_v3 = positive.get("cumulative_filtered_near_duplicate_challenge_sample_v3", {})
    if cumulative_challenge_v3.get("verdict") != "C1_CUMULATIVE_FILTERED_NEAR_DUPLICATE_SAMPLE_V3_VALIDATED":
        failures.append({"code": "cumulative_filtered_challenge_v3_not_validated", "actual": cumulative_challenge_v3})
    if cumulative_challenge_v3.get("sampled_documents", 0) < 50000 or cumulative_challenge_v3.get("sampled_excluded_document_count") != 0 or cumulative_challenge_v3.get("excluded_document_count") != 1709:
        failures.append({"code": "cumulative_filtered_challenge_v3_scope_mismatch", "actual": cumulative_challenge_v3})
    if cumulative_challenge_v3.get("crossing_pair_count") != 10 or cumulative_challenge_v3.get("max_exact_jaccard_observed", 0) < 0.8:
        failures.append({"code": "cumulative_filtered_challenge_v3_problem_not_recorded", "actual": cumulative_challenge_v3})
    if "not an all-pairs near-duplicate PASS" not in str(cumulative_challenge_v3.get("scope_limit", "")):
        failures.append({"code": "cumulative_filtered_challenge_v3_missing_noncompletion_guard", "actual": cumulative_challenge_v3.get("scope_limit")})
    remediation_v4 = positive.get("cumulative_filtered_challenge_remediation_v4", {})
    if remediation_v4.get("verdict") != "C1_CUMULATIVE_FILTERED_CHALLENGE_REMEDIATION_V4_VALIDATED":
        failures.append({"code": "cumulative_filtered_challenge_remediation_v4_not_validated", "actual": remediation_v4})
    if remediation_v4.get("input_crossing_pair_count") != cumulative_challenge_v3.get("crossing_pair_count") or remediation_v4.get("challenge_exclusion_document_count") != 10 or remediation_v4.get("existing_targeted_manifest_overlap_count") != 0:
        failures.append({"code": "cumulative_filtered_challenge_remediation_v4_scope_mismatch", "actual": remediation_v4, "challenge_v3": cumulative_challenge_v3})
    if "all-pairs/full-corpus PASS remains required" not in str(remediation_v4.get("scope_limit", "")):
        failures.append({"code": "cumulative_filtered_challenge_remediation_v4_missing_noncompletion_guard", "actual": remediation_v4.get("scope_limit")})
    cumulative_manifest_v4 = positive.get("near_duplicate_cumulative_exclusion_manifest_v4", {})
    if cumulative_manifest_v4.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V4_VALIDATED":
        failures.append({"code": "near_duplicate_cumulative_manifest_v4_not_validated", "actual": cumulative_manifest_v4})
    if cumulative_manifest_v4.get("exclusion_document_count") != 1719 or cumulative_manifest_v4.get("exclusion_token_floor") != 3026203 or cumulative_manifest_v4.get("source_overlap_count") != 0:
        failures.append({"code": "near_duplicate_cumulative_manifest_v4_scope_mismatch", "actual": cumulative_manifest_v4})
    cumulative_view_v4 = positive.get("cumulative_filtered_corpus_view_v4", {})
    if cumulative_view_v4.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V4_VALIDATED":
        failures.append({"code": "cumulative_filtered_view_v4_not_validated", "actual": cumulative_view_v4})
    if cumulative_view_v4.get("excluded_document_count") != 1719 or cumulative_view_v4.get("remaining_document_count") != 4234739 or cumulative_view_v4.get("binary_shards_rewritten") is not False:
        failures.append({"code": "cumulative_filtered_view_v4_scope_mismatch", "actual": cumulative_view_v4})
    cumulative_manifest_v5 = positive.get("near_duplicate_cumulative_exclusion_manifest_v5", {})
    if cumulative_manifest_v5.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V5_VALIDATED":
        failures.append({"code": "near_duplicate_cumulative_manifest_v5_not_validated", "actual": cumulative_manifest_v5})
    if cumulative_manifest_v5.get("materialization_verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V5_READY_NOT_COMPLETION":
        failures.append({"code": "near_duplicate_cumulative_manifest_v5_bad_materialization", "actual": cumulative_manifest_v5})
    if cumulative_manifest_v5.get("exclusion_document_count") != 1733 or cumulative_manifest_v5.get("exclusion_token_floor") != 3039393 or cumulative_manifest_v5.get("source_overlap_count") != 0:
        failures.append({"code": "near_duplicate_cumulative_manifest_v5_scope_mismatch", "actual": cumulative_manifest_v5})
    if "not a full band-48 remediation" not in str(cumulative_manifest_v5.get("scope_limit", "")) or "not an all-pairs near-duplicate PASS" not in str(cumulative_manifest_v5.get("scope_limit", "")):
        failures.append({"code": "near_duplicate_cumulative_manifest_v5_missing_noncompletion_guard", "actual": cumulative_manifest_v5.get("scope_limit")})
    cumulative_view_v5 = positive.get("cumulative_filtered_corpus_view_v5", {})
    if cumulative_view_v5.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V5_VALIDATED":
        failures.append({"code": "cumulative_filtered_view_v5_not_validated", "actual": cumulative_view_v5})
    if cumulative_view_v5.get("materialization_verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V5_READY_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_view_v5_bad_materialization", "actual": cumulative_view_v5})
    if cumulative_view_v5.get("excluded_document_count") != 1733 or cumulative_view_v5.get("excluded_token_floor") != 3039393 or cumulative_view_v5.get("remaining_document_count") != 4234725 or cumulative_view_v5.get("remaining_content_token_floor") != 6974829365 or cumulative_view_v5.get("binary_shards_rewritten") is not False:
        failures.append({"code": "cumulative_filtered_view_v5_scope_mismatch", "actual": cumulative_view_v5})
    if "not an all-pairs near-duplicate PASS" not in str(cumulative_view_v5.get("scope_limit", "")) or "not overall baseline completion" not in str(cumulative_view_v5.get("scope_limit", "")):
        failures.append({"code": "cumulative_filtered_view_v5_missing_noncompletion_guard", "actual": cumulative_view_v5.get("scope_limit")})
    lsh_candidate_index_v5_band48 = positive.get("cumulative_filtered_lsh_candidate_index_v5_band48", {})
    if lsh_candidate_index_v5_band48.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V5_VALIDATED":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v5_band48_not_validated", "actual": lsh_candidate_index_v5_band48})
    if lsh_candidate_index_v5_band48.get("materialization_verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V5_MATERIALIZED_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v5_band48_bad_materialization", "actual": lsh_candidate_index_v5_band48})
    if lsh_candidate_index_v5_band48.get("band_starts_materialized") != [48] or lsh_candidate_index_v5_band48.get("collision_bucket_count") != 28278:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v5_band48_scope_invalid", "actual": lsh_candidate_index_v5_band48})
    if lsh_candidate_index_v5_band48.get("candidate_pair_upper_bound_before_deduplication") != 20991648 or lsh_candidate_index_v5_band48.get("max_bucket_size") != 5741:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v5_band48_counts_invalid", "actual": lsh_candidate_index_v5_band48})
    partial_adjudication_v5_band48 = positive.get("cumulative_filtered_lsh_candidate_index_v5_band48_adjudication_partial25", {})
    if partial_adjudication_v5_band48.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V5_EXACT_ADJUDICATION_VALIDATED":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v5_band48_partial_adjudication_not_validated", "actual": partial_adjudication_v5_band48})
    if partial_adjudication_v5_band48.get("adjudication_verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V5_EXACT_ADJUDICATION_CROSSINGS_FOUND_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v5_band48_partial_adjudication_bad_verdict", "actual": partial_adjudication_v5_band48})
    if partial_adjudication_v5_band48.get("index_rows_adjudicated") != 25 or partial_adjudication_v5_band48.get("crossing_pair_count") != 18:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v5_band48_partial_adjudication_counts_invalid", "actual": partial_adjudication_v5_band48})
    if partial_adjudication_v5_band48.get("max_exact_jaccard_observed") != 0.975309 or partial_adjudication_v5_band48.get("candidate_pair_count") != 84:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v5_band48_partial_adjudication_metrics_invalid", "actual": partial_adjudication_v5_band48})
    partial_remediation_v5_band48 = positive.get("cumulative_filtered_lsh_candidate_index_v5_band48_adjudication_partial25_remediation", {})
    if partial_remediation_v5_band48.get("verdict") != "C1_LSH_CANDIDATE_ADJUDICATION_V5_REMEDIATION_PACKET_READY_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v5_band48_partial_remediation_bad_verdict", "actual": partial_remediation_v5_band48})
    if partial_remediation_v5_band48.get("remediation_exclusion_document_count") != 9 or partial_remediation_v5_band48.get("cluster_count") != 4:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v5_band48_partial_remediation_counts_invalid", "actual": partial_remediation_v5_band48})
    if partial_remediation_v5_band48.get("existing_cumulative_v5_manifest_overlap_count") != 0:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v5_band48_partial_remediation_overlap", "actual": partial_remediation_v5_band48})
    cumulative_manifest_v6 = positive.get("near_duplicate_cumulative_exclusion_manifest_v6", {})
    if cumulative_manifest_v6.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V6_VALIDATED":
        failures.append({"code": "near_duplicate_cumulative_manifest_v6_not_validated", "actual": cumulative_manifest_v6})
    if cumulative_manifest_v6.get("materialization_verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V6_READY_NOT_COMPLETION":
        failures.append({"code": "near_duplicate_cumulative_manifest_v6_bad_materialization", "actual": cumulative_manifest_v6})
    if cumulative_manifest_v6.get("exclusion_document_count") != 1742 or cumulative_manifest_v6.get("exclusion_token_floor") != 3050833 or cumulative_manifest_v6.get("source_overlap_count") != 0:
        failures.append({"code": "near_duplicate_cumulative_manifest_v6_scope_mismatch", "actual": cumulative_manifest_v6})
    cumulative_view_v6 = positive.get("cumulative_filtered_corpus_view_v6", {})
    if cumulative_view_v6.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V6_VALIDATED":
        failures.append({"code": "cumulative_filtered_view_v6_not_validated", "actual": cumulative_view_v6})
    if cumulative_view_v6.get("materialization_verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V6_READY_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_view_v6_bad_materialization", "actual": cumulative_view_v6})
    if cumulative_view_v6.get("excluded_document_count") != 1742 or cumulative_view_v6.get("excluded_token_floor") != 3050833 or cumulative_view_v6.get("remaining_document_count") != 4234716 or cumulative_view_v6.get("remaining_content_token_floor") != 6974817925 or cumulative_view_v6.get("binary_shards_rewritten") is not False:
        failures.append({"code": "cumulative_filtered_view_v6_scope_mismatch", "actual": cumulative_view_v6})
    lsh_candidate_index_v6_band48 = positive.get("cumulative_filtered_lsh_candidate_index_v6_band48", {})
    if lsh_candidate_index_v6_band48.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V6_VALIDATED":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v6_band48_not_validated", "actual": lsh_candidate_index_v6_band48})
    if lsh_candidate_index_v6_band48.get("materialization_verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V6_MATERIALIZED_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v6_band48_bad_materialization", "actual": lsh_candidate_index_v6_band48})
    if lsh_candidate_index_v6_band48.get("band_starts_materialized") != [48] or lsh_candidate_index_v6_band48.get("collision_bucket_count") != 28274:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v6_band48_scope_invalid", "actual": lsh_candidate_index_v6_band48})
    if lsh_candidate_index_v6_band48.get("candidate_pair_upper_bound_before_deduplication") != 20991630 or lsh_candidate_index_v6_band48.get("max_bucket_size") != 5741:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v6_band48_counts_invalid", "actual": lsh_candidate_index_v6_band48})
    partial_adjudication_v6_band48 = positive.get("cumulative_filtered_lsh_candidate_index_v6_band48_adjudication_partial25", {})
    if partial_adjudication_v6_band48.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V6_EXACT_ADJUDICATION_VALIDATED":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v6_band48_partial_adjudication_not_validated", "actual": partial_adjudication_v6_band48})
    if partial_adjudication_v6_band48.get("adjudication_verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V6_EXACT_ADJUDICATION_CROSSINGS_FOUND_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v6_band48_partial_adjudication_bad_verdict", "actual": partial_adjudication_v6_band48})
    if partial_adjudication_v6_band48.get("index_rows_adjudicated") != 25 or partial_adjudication_v6_band48.get("crossing_pair_count") != 3:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v6_band48_partial_adjudication_counts_invalid", "actual": partial_adjudication_v6_band48})
    if partial_adjudication_v6_band48.get("max_exact_jaccard_observed") != 0.978495 or partial_adjudication_v6_band48.get("candidate_pair_count") != 70:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v6_band48_partial_adjudication_metrics_invalid", "actual": partial_adjudication_v6_band48})
    partial_remediation_v6_band48 = positive.get("cumulative_filtered_lsh_candidate_index_v6_band48_adjudication_partial25_remediation", {})
    if partial_remediation_v6_band48.get("verdict") != "C1_LSH_CANDIDATE_ADJUDICATION_V6_REMEDIATION_PACKET_READY_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v6_band48_partial_remediation_bad_verdict", "actual": partial_remediation_v6_band48})
    if partial_remediation_v6_band48.get("remediation_exclusion_document_count") != 3 or partial_remediation_v6_band48.get("cluster_count") != 3:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v6_band48_partial_remediation_counts_invalid", "actual": partial_remediation_v6_band48})
    if partial_remediation_v6_band48.get("existing_cumulative_v6_manifest_overlap_count") != 0:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v6_band48_partial_remediation_overlap", "actual": partial_remediation_v6_band48})
    cumulative_manifest_v7 = positive.get("near_duplicate_cumulative_exclusion_manifest_v7", {})
    if cumulative_manifest_v7.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V7_VALIDATED":
        failures.append({"code": "near_duplicate_cumulative_manifest_v7_not_validated", "actual": cumulative_manifest_v7})
    if cumulative_manifest_v7.get("materialization_verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V7_READY_NOT_COMPLETION":
        failures.append({"code": "near_duplicate_cumulative_manifest_v7_bad_materialization", "actual": cumulative_manifest_v7})
    if cumulative_manifest_v7.get("exclusion_document_count") != 1745 or cumulative_manifest_v7.get("exclusion_token_floor") != 3055337 or cumulative_manifest_v7.get("source_overlap_count") != 0:
        failures.append({"code": "near_duplicate_cumulative_manifest_v7_scope_mismatch", "actual": cumulative_manifest_v7})
    cumulative_view_v7 = positive.get("cumulative_filtered_corpus_view_v7", {})
    if cumulative_view_v7.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V7_VALIDATED":
        failures.append({"code": "cumulative_filtered_view_v7_not_validated", "actual": cumulative_view_v7})
    if cumulative_view_v7.get("materialization_verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V7_READY_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_view_v7_bad_materialization", "actual": cumulative_view_v7})
    if cumulative_view_v7.get("excluded_document_count") != 1745 or cumulative_view_v7.get("excluded_token_floor") != 3055337 or cumulative_view_v7.get("remaining_document_count") != 4234713 or cumulative_view_v7.get("remaining_content_token_floor") != 6974813421 or cumulative_view_v7.get("binary_shards_rewritten") is not False:
        failures.append({"code": "cumulative_filtered_view_v7_scope_mismatch", "actual": cumulative_view_v7})
    lsh_candidate_index_v7_band48 = positive.get("cumulative_filtered_lsh_candidate_index_v7_band48", {})
    if lsh_candidate_index_v7_band48.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V7_VALIDATED":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v7_band48_not_validated", "actual": lsh_candidate_index_v7_band48})
    if lsh_candidate_index_v7_band48.get("materialization_verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V7_MATERIALIZED_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v7_band48_bad_materialization", "actual": lsh_candidate_index_v7_band48})
    if lsh_candidate_index_v7_band48.get("band_starts_materialized") != [48] or lsh_candidate_index_v7_band48.get("collision_bucket_count") != 28271:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v7_band48_scope_invalid", "actual": lsh_candidate_index_v7_band48})
    if lsh_candidate_index_v7_band48.get("candidate_pair_upper_bound_before_deduplication") != 20991627 or lsh_candidate_index_v7_band48.get("max_bucket_size") != 5741:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v7_band48_counts_invalid", "actual": lsh_candidate_index_v7_band48})
    partial_adjudication_v7_band48 = positive.get("cumulative_filtered_lsh_candidate_index_v7_band48_adjudication_partial25", {})
    if partial_adjudication_v7_band48.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V7_EXACT_ADJUDICATION_VALIDATED":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v7_band48_partial_adjudication_not_validated", "actual": partial_adjudication_v7_band48})
    if partial_adjudication_v7_band48.get("adjudication_verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V7_EXACT_ADJUDICATION_CROSSINGS_FOUND_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v7_band48_partial_adjudication_bad_verdict", "actual": partial_adjudication_v7_band48})
    if partial_adjudication_v7_band48.get("index_rows_adjudicated") != 25 or partial_adjudication_v7_band48.get("crossing_pair_count") != 3:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v7_band48_partial_adjudication_counts_invalid", "actual": partial_adjudication_v7_band48})
    if partial_adjudication_v7_band48.get("max_exact_jaccard_observed") != 0.952118 or partial_adjudication_v7_band48.get("candidate_pair_count") != 72:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v7_band48_partial_adjudication_metrics_invalid", "actual": partial_adjudication_v7_band48})
    partial_remediation_v7_band48 = positive.get("cumulative_filtered_lsh_candidate_index_v7_band48_adjudication_partial25_remediation", {})
    if partial_remediation_v7_band48.get("verdict") != "C1_LSH_CANDIDATE_ADJUDICATION_V7_REMEDIATION_PACKET_READY_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v7_band48_partial_remediation_bad_verdict", "actual": partial_remediation_v7_band48})
    if partial_remediation_v7_band48.get("remediation_exclusion_document_count") != 2 or partial_remediation_v7_band48.get("cluster_count") != 1:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v7_band48_partial_remediation_counts_invalid", "actual": partial_remediation_v7_band48})
    if partial_remediation_v7_band48.get("existing_cumulative_v7_manifest_overlap_count") != 0:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v7_band48_partial_remediation_overlap", "actual": partial_remediation_v7_band48})
    cumulative_manifest_v8 = positive.get("near_duplicate_cumulative_exclusion_manifest_v8", {})
    if cumulative_manifest_v8.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V8_VALIDATED":
        failures.append({"code": "near_duplicate_cumulative_manifest_v8_not_validated", "actual": cumulative_manifest_v8})
    if cumulative_manifest_v8.get("materialization_verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V8_READY_NOT_COMPLETION":
        failures.append({"code": "near_duplicate_cumulative_manifest_v8_bad_materialization", "actual": cumulative_manifest_v8})
    if cumulative_manifest_v8.get("exclusion_document_count") != 1747 or cumulative_manifest_v8.get("exclusion_token_floor") != 3058613 or cumulative_manifest_v8.get("source_overlap_count") != 0:
        failures.append({"code": "near_duplicate_cumulative_manifest_v8_scope_mismatch", "actual": cumulative_manifest_v8})
    cumulative_view_v8 = positive.get("cumulative_filtered_corpus_view_v8", {})
    if cumulative_view_v8.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V8_VALIDATED":
        failures.append({"code": "cumulative_filtered_view_v8_not_validated", "actual": cumulative_view_v8})
    if cumulative_view_v8.get("materialization_verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V8_READY_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_view_v8_bad_materialization", "actual": cumulative_view_v8})
    if cumulative_view_v8.get("excluded_document_count") != 1747 or cumulative_view_v8.get("excluded_token_floor") != 3058613 or cumulative_view_v8.get("remaining_document_count") != 4234711 or cumulative_view_v8.get("remaining_content_token_floor") != 6974810145 or cumulative_view_v8.get("binary_shards_rewritten") is not False:
        failures.append({"code": "cumulative_filtered_view_v8_scope_mismatch", "actual": cumulative_view_v8})
    lsh_candidate_index_v8_band48 = positive.get("cumulative_filtered_lsh_candidate_index_v8_band48", {})
    if lsh_candidate_index_v8_band48.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V8_VALIDATED":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v8_band48_not_validated", "actual": lsh_candidate_index_v8_band48})
    if lsh_candidate_index_v8_band48.get("materialization_verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V8_MATERIALIZED_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v8_band48_bad_materialization", "actual": lsh_candidate_index_v8_band48})
    if lsh_candidate_index_v8_band48.get("band_starts_materialized") != [48] or lsh_candidate_index_v8_band48.get("collision_bucket_count") != 28270:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v8_band48_scope_invalid", "actual": lsh_candidate_index_v8_band48})
    if lsh_candidate_index_v8_band48.get("candidate_pair_upper_bound_before_deduplication") != 20991624 or lsh_candidate_index_v8_band48.get("max_bucket_size") != 5741:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v8_band48_counts_invalid", "actual": lsh_candidate_index_v8_band48})
    partial_adjudication_v8_skip0 = positive.get("cumulative_filtered_lsh_candidate_index_v8_band48_adjudication_partial25_skip0", {})
    if partial_adjudication_v8_skip0.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V8_EXACT_ADJUDICATION_VALIDATED" or partial_adjudication_v8_skip0.get("index_row_start_offset") != 0 or partial_adjudication_v8_skip0.get("index_row_end_exclusive") != 25 or partial_adjudication_v8_skip0.get("crossing_pair_count") != 1 or partial_adjudication_v8_skip0.get("max_exact_jaccard_observed") != 0.985401:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v8_skip0_invalid", "actual": partial_adjudication_v8_skip0})
    partial_adjudication_v8_skip25 = positive.get("cumulative_filtered_lsh_candidate_index_v8_band48_adjudication_partial25_skip25", {})
    if partial_adjudication_v8_skip25.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V8_EXACT_ADJUDICATION_VALIDATED" or partial_adjudication_v8_skip25.get("index_row_start_offset") != 25 or partial_adjudication_v8_skip25.get("index_row_end_exclusive") != 50 or partial_adjudication_v8_skip25.get("crossing_pair_count") != 22 or partial_adjudication_v8_skip25.get("max_exact_jaccard_observed") != 0.985562:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v8_skip25_invalid", "actual": partial_adjudication_v8_skip25})
    remediation_v8_window50 = positive.get("cumulative_filtered_lsh_candidate_index_v8_band48_adjudication_window50_remediation", {})
    if remediation_v8_window50.get("verdict") != "C1_LSH_CANDIDATE_ADJUDICATION_V8_REMEDIATION_PACKET_READY_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v8_window50_remediation_bad_verdict", "actual": remediation_v8_window50})
    if remediation_v8_window50.get("index_rows_adjudicated") != 50 or remediation_v8_window50.get("input_crossing_pair_count") != 23 or remediation_v8_window50.get("remediation_exclusion_document_count") != 19 or remediation_v8_window50.get("cluster_count") != 14:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v8_window50_remediation_counts_invalid", "actual": remediation_v8_window50})
    if remediation_v8_window50.get("existing_cumulative_v8_manifest_overlap_count") != 0:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v8_window50_remediation_overlap", "actual": remediation_v8_window50})
    cumulative_manifest_v9 = positive.get("near_duplicate_cumulative_exclusion_manifest_v9", {})
    if cumulative_manifest_v9.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V9_VALIDATED":
        failures.append({"code": "near_duplicate_cumulative_manifest_v9_not_validated", "actual": cumulative_manifest_v9})
    if cumulative_manifest_v9.get("materialization_verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V9_READY_NOT_COMPLETION":
        failures.append({"code": "near_duplicate_cumulative_manifest_v9_bad_materialization", "actual": cumulative_manifest_v9})
    if cumulative_manifest_v9.get("exclusion_document_count") != 1766 or cumulative_manifest_v9.get("exclusion_token_floor") != 3087096 or cumulative_manifest_v9.get("source_overlap_count") != 0:
        failures.append({"code": "near_duplicate_cumulative_manifest_v9_scope_mismatch", "actual": cumulative_manifest_v9})
    cumulative_view_v9 = positive.get("cumulative_filtered_corpus_view_v9", {})
    if cumulative_view_v9.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V9_VALIDATED":
        failures.append({"code": "cumulative_filtered_view_v9_not_validated", "actual": cumulative_view_v9})
    if cumulative_view_v9.get("materialization_verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V9_READY_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_view_v9_bad_materialization", "actual": cumulative_view_v9})
    if cumulative_view_v9.get("excluded_document_count") != 1766 or cumulative_view_v9.get("excluded_token_floor") != 3087096 or cumulative_view_v9.get("remaining_document_count") != 4234692 or cumulative_view_v9.get("remaining_content_token_floor") != 6974781662 or cumulative_view_v9.get("binary_shards_rewritten") is not False:
        failures.append({"code": "cumulative_filtered_view_v9_scope_mismatch", "actual": cumulative_view_v9})
    candidate_index_v9 = positive.get("cumulative_filtered_lsh_candidate_index_v9_band48", {})
    if candidate_index_v9.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V9_VALIDATED":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v9_not_validated", "actual": candidate_index_v9})
    if candidate_index_v9.get("index_row_count") != 28258 or candidate_index_v9.get("collision_bucket_count") != 28258 or candidate_index_v9.get("collision_document_memberships") != 113496 or candidate_index_v9.get("candidate_pair_upper_bound_before_deduplication") != 20991589:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v9_counts_invalid", "actual": candidate_index_v9})
    expected_v9_windows = {0: (0, 25, 70, 0, 0.799622), 25: (25, 50, 119, 8, 0.947971), 50: (50, 75, 478, 50, 0.988074), 75: (75, 100, 90, 36, 0.988072)}
    for skip, expected in expected_v9_windows.items():
        row = positive.get(f"cumulative_filtered_lsh_candidate_index_v9_band48_adjudication_partial25_skip{skip}", {})
        start, end, pairs, crossings, max_j = expected
        if row.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V9_EXACT_ADJUDICATION_VALIDATED" or row.get("index_row_start_offset") != start or row.get("index_row_end_exclusive") != end or row.get("candidate_pair_count") != pairs or row.get("crossing_pair_count") != crossings or row.get("max_exact_jaccard_observed") != max_j:
            failures.append({"code": "cumulative_filtered_lsh_candidate_index_v9_window_invalid", "skip": skip, "actual": row})
    remediation_v9_window100 = positive.get("cumulative_filtered_lsh_candidate_index_v9_band48_adjudication_window100_remediation", {})
    if remediation_v9_window100.get("verdict") != "C1_LSH_CANDIDATE_ADJUDICATION_V9_REMEDIATION_PACKET_READY_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v9_window100_remediation_bad_verdict", "actual": remediation_v9_window100})
    if remediation_v9_window100.get("index_rows_adjudicated") != 100 or remediation_v9_window100.get("input_crossing_pair_count") != 94 or remediation_v9_window100.get("remediation_exclusion_document_count") != 48 or remediation_v9_window100.get("cluster_count") != 30 or remediation_v9_window100.get("existing_cumulative_v9_manifest_overlap_count") != 0:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v9_window100_remediation_counts_invalid", "actual": remediation_v9_window100})
    cumulative_manifest_v10 = positive.get("near_duplicate_cumulative_exclusion_manifest_v10", {})
    if cumulative_manifest_v10.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V10_VALIDATED" or cumulative_manifest_v10.get("materialization_verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V10_READY_NOT_COMPLETION":
        failures.append({"code": "near_duplicate_cumulative_manifest_v10_not_validated", "actual": cumulative_manifest_v10})
    if cumulative_manifest_v10.get("exclusion_document_count") != 1814 or cumulative_manifest_v10.get("exclusion_token_floor") != 3155898 or cumulative_manifest_v10.get("source_overlap_count") != 0:
        failures.append({"code": "near_duplicate_cumulative_manifest_v10_scope_mismatch", "actual": cumulative_manifest_v10})
    cumulative_view_v10 = positive.get("cumulative_filtered_corpus_view_v10", {})
    if cumulative_view_v10.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V10_VALIDATED" or cumulative_view_v10.get("materialization_verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V10_READY_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_view_v10_not_validated", "actual": cumulative_view_v10})
    if cumulative_view_v10.get("excluded_document_count") != 1814 or cumulative_view_v10.get("excluded_token_floor") != 3155898 or cumulative_view_v10.get("remaining_document_count") != 4234644 or cumulative_view_v10.get("remaining_content_token_floor") != 6974712860 or cumulative_view_v10.get("binary_shards_rewritten") is not False:
        failures.append({"code": "cumulative_filtered_view_v10_scope_mismatch", "actual": cumulative_view_v10})
    candidate_index_v10 = positive.get("cumulative_filtered_lsh_candidate_index_v10_band48", {})
    if candidate_index_v10.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V10_VALIDATED":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v10_not_validated", "actual": candidate_index_v10})
    if candidate_index_v10.get("index_row_count") != 28236 or candidate_index_v10.get("collision_bucket_count") != 28236 or candidate_index_v10.get("collision_document_memberships") != 113426 or candidate_index_v10.get("candidate_pair_upper_bound_before_deduplication") != 20991240:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v10_counts_invalid", "actual": candidate_index_v10})
    expected_v10_windows = {0: (0, 25, 70, 0, 0.799622), 25: (25, 50, 106, 0, 0.795349), 50: (50, 75, 222, 16, 0.985433), 75: (75, 100, 182, 15, 0.979626), 100: (100, 125, 125, 28, 0.997024)}
    for skip, expected in expected_v10_windows.items():
        row = positive.get(f"cumulative_filtered_lsh_candidate_index_v10_band48_adjudication_partial25_skip{skip}", {})
        start, end, pairs, crossings, max_j = expected
        if row.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V10_EXACT_ADJUDICATION_VALIDATED" or row.get("index_row_start_offset") != start or row.get("index_row_end_exclusive") != end or row.get("candidate_pair_count") != pairs or row.get("crossing_pair_count") != crossings or row.get("max_exact_jaccard_observed") != max_j:
            failures.append({"code": "cumulative_filtered_lsh_candidate_index_v10_window_invalid", "skip": skip, "actual": row})
    remediation_v10_window125 = positive.get("cumulative_filtered_lsh_candidate_index_v10_band48_adjudication_window125_remediation", {})
    if remediation_v10_window125.get("verdict") != "C1_LSH_CANDIDATE_ADJUDICATION_V10_REMEDIATION_PACKET_READY_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v10_window125_remediation_bad_verdict", "actual": remediation_v10_window125})
    if remediation_v10_window125.get("index_rows_adjudicated") != 125 or remediation_v10_window125.get("input_crossing_pair_count") != 59 or remediation_v10_window125.get("remediation_exclusion_document_count") != 40 or remediation_v10_window125.get("cluster_count") != 25 or remediation_v10_window125.get("existing_cumulative_v10_manifest_overlap_count") != 0:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v10_window125_remediation_counts_invalid", "actual": remediation_v10_window125})
    cumulative_manifest_v11 = positive.get("near_duplicate_cumulative_exclusion_manifest_v11", {})
    if cumulative_manifest_v11.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V11_VALIDATED" or cumulative_manifest_v11.get("materialization_verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V11_READY_NOT_COMPLETION":
        failures.append({"code": "near_duplicate_cumulative_manifest_v11_not_validated", "actual": cumulative_manifest_v11})
    if cumulative_manifest_v11.get("exclusion_document_count") != 1854 or cumulative_manifest_v11.get("exclusion_token_floor") != 3221182 or cumulative_manifest_v11.get("source_overlap_count") != 0:
        failures.append({"code": "near_duplicate_cumulative_manifest_v11_scope_mismatch", "actual": cumulative_manifest_v11})
    cumulative_view_v11 = positive.get("cumulative_filtered_corpus_view_v11", {})
    if cumulative_view_v11.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V11_VALIDATED" or cumulative_view_v11.get("materialization_verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V11_READY_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_view_v11_not_validated", "actual": cumulative_view_v11})
    if cumulative_view_v11.get("excluded_document_count") != 1854 or cumulative_view_v11.get("excluded_token_floor") != 3221182 or cumulative_view_v11.get("remaining_document_count") != 4234604 or cumulative_view_v11.get("remaining_content_token_floor") != 6974647576 or cumulative_view_v11.get("binary_shards_rewritten") is not False:
        failures.append({"code": "cumulative_filtered_view_v11_scope_mismatch", "actual": cumulative_view_v11})
    candidate_index_v11 = positive.get("cumulative_filtered_lsh_candidate_index_v11_band48", {})
    if candidate_index_v11.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V11_VALIDATED":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v11_not_validated", "actual": candidate_index_v11})
    if candidate_index_v11.get("index_row_count") != 28220 or candidate_index_v11.get("collision_bucket_count") != 28220 or candidate_index_v11.get("collision_document_memberships") != 113370 or candidate_index_v11.get("candidate_pair_upper_bound_before_deduplication") != 20991071:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v11_counts_invalid", "actual": candidate_index_v11})
    expected_v11_windows = {0: (0, 25, 70, 0, 0.799622), 25: (25, 50, 106, 0, 0.795349), 50: (50, 75, 135, 0, 0.797549), 75: (75, 100, 207, 0, 0.789764), 100: (100, 125, 758357, 41, 0.997024), 125: (125, 150, 900, 15, 0.991576)}
    for skip, expected in expected_v11_windows.items():
        row = positive.get(f"cumulative_filtered_lsh_candidate_index_v11_band48_adjudication_partial25_skip{skip}", {})
        start, end, pairs, crossings, max_j = expected
        if row.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V11_EXACT_ADJUDICATION_VALIDATED" or row.get("index_row_start_offset") != start or row.get("index_row_end_exclusive") != end or row.get("candidate_pair_count") != pairs or row.get("crossing_pair_count") != crossings or row.get("max_exact_jaccard_observed") != max_j:
            failures.append({"code": "cumulative_filtered_lsh_candidate_index_v11_window_invalid", "skip": skip, "actual": row})
    remediation_v11_window150 = positive.get("cumulative_filtered_lsh_candidate_index_v11_band48_adjudication_window150_remediation", {})
    if remediation_v11_window150.get("verdict") != "C1_LSH_CANDIDATE_ADJUDICATION_V11_REMEDIATION_PACKET_READY_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v11_window150_remediation_bad_verdict", "actual": remediation_v11_window150})
    if remediation_v11_window150.get("index_rows_adjudicated") != 150 or remediation_v11_window150.get("input_crossing_pair_count") != 56 or remediation_v11_window150.get("remediation_exclusion_document_count") != 38 or remediation_v11_window150.get("cluster_count") != 33 or remediation_v11_window150.get("existing_cumulative_v11_manifest_overlap_count") != 0:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v11_window150_remediation_counts_invalid", "actual": remediation_v11_window150})
    cumulative_manifest_v12 = positive.get("near_duplicate_cumulative_exclusion_manifest_v12", {})
    if cumulative_manifest_v12.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V12_VALIDATED" or cumulative_manifest_v12.get("materialization_verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V12_READY_NOT_COMPLETION":
        failures.append({"code": "near_duplicate_cumulative_manifest_v12_not_validated", "actual": cumulative_manifest_v12})
    if cumulative_manifest_v12.get("exclusion_document_count") != 1892 or cumulative_manifest_v12.get("exclusion_token_floor") != 3250574 or cumulative_manifest_v12.get("source_overlap_count") != 0:
        failures.append({"code": "near_duplicate_cumulative_manifest_v12_scope_mismatch", "actual": cumulative_manifest_v12})
    cumulative_view_v12 = positive.get("cumulative_filtered_corpus_view_v12", {})
    if cumulative_view_v12.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V12_VALIDATED" or cumulative_view_v12.get("materialization_verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V12_READY_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_view_v12_not_validated", "actual": cumulative_view_v12})
    if cumulative_view_v12.get("excluded_document_count") != 1892 or cumulative_view_v12.get("excluded_token_floor") != 3250574 or cumulative_view_v12.get("remaining_document_count") != 4234566 or cumulative_view_v12.get("remaining_content_token_floor") != 6974618184 or cumulative_view_v12.get("binary_shards_rewritten") is not False:
        failures.append({"code": "cumulative_filtered_view_v12_scope_mismatch", "actual": cumulative_view_v12})
    candidate_index_v12 = positive.get("cumulative_filtered_lsh_candidate_index_v12_band48", {})
    if candidate_index_v12.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V12_VALIDATED":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v12_not_validated", "actual": candidate_index_v12})
    if candidate_index_v12.get("index_row_count") != 28206 or candidate_index_v12.get("collision_bucket_count") != 28206 or candidate_index_v12.get("collision_document_memberships") != 113318 or candidate_index_v12.get("candidate_pair_upper_bound_before_deduplication") != 20966617:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v12_counts_invalid", "actual": candidate_index_v12})
    expected_v12_windows = {0: (0, 25, 70, 0, 0.799622), 25: (25, 50, 106, 0, 0.795349), 50: (50, 75, 135, 0, 0.797549), 75: (75, 100, 207, 0, 0.789764), 100: (100, 125, 733927, 14, 0.970588), 125: (125, 150, 1045, 8, 0.972816), 150: (150, 175, 51, 14, 0.979872)}
    for skip, expected in expected_v12_windows.items():
        row = positive.get(f"cumulative_filtered_lsh_candidate_index_v12_band48_adjudication_partial25_skip{skip}", {})
        start, end, pairs, crossings, max_j = expected
        if row.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V12_EXACT_ADJUDICATION_VALIDATED" or row.get("index_row_start_offset") != start or row.get("index_row_end_exclusive") != end or row.get("candidate_pair_count") != pairs or row.get("crossing_pair_count") != crossings or row.get("max_exact_jaccard_observed") != max_j:
            failures.append({"code": "cumulative_filtered_lsh_candidate_index_v12_window_invalid", "skip": skip, "actual": row})
    remediation_v12_window175 = positive.get("cumulative_filtered_lsh_candidate_index_v12_band48_adjudication_window175_remediation", {})
    if remediation_v12_window175.get("verdict") != "C1_LSH_CANDIDATE_ADJUDICATION_V12_REMEDIATION_PACKET_READY_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v12_window175_remediation_bad_verdict", "actual": remediation_v12_window175})
    if remediation_v12_window175.get("index_rows_adjudicated") != 175 or remediation_v12_window175.get("input_crossing_pair_count") != 36 or remediation_v12_window175.get("remediation_exclusion_document_count") != 32 or remediation_v12_window175.get("cluster_count") != 28 or remediation_v12_window175.get("existing_cumulative_v12_manifest_overlap_count") != 0:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v12_window175_remediation_counts_invalid", "actual": remediation_v12_window175})
    cumulative_manifest_v13 = positive.get("near_duplicate_cumulative_exclusion_manifest_v13", {})
    if cumulative_manifest_v13.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V13_VALIDATED" or cumulative_manifest_v13.get("materialization_verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V13_READY_NOT_COMPLETION":
        failures.append({"code": "near_duplicate_cumulative_manifest_v13_not_validated", "actual": cumulative_manifest_v13})
    if cumulative_manifest_v13.get("exclusion_document_count") != 1924 or cumulative_manifest_v13.get("exclusion_token_floor") != 3295935 or cumulative_manifest_v13.get("source_overlap_count") != 0:
        failures.append({"code": "near_duplicate_cumulative_manifest_v13_scope_mismatch", "actual": cumulative_manifest_v13})
    cumulative_view_v13 = positive.get("cumulative_filtered_corpus_view_v13", {})
    if cumulative_view_v13.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V13_VALIDATED" or cumulative_view_v13.get("materialization_verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V13_READY_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_view_v13_not_validated", "actual": cumulative_view_v13})
    if cumulative_view_v13.get("excluded_document_count") != 1924 or cumulative_view_v13.get("excluded_token_floor") != 3295935 or cumulative_view_v13.get("remaining_document_count") != 4234534 or cumulative_view_v13.get("remaining_content_token_floor") != 6974572823 or cumulative_view_v13.get("binary_shards_rewritten") is not False:
        failures.append({"code": "cumulative_filtered_view_v13_scope_mismatch", "actual": cumulative_view_v13})
    candidate_index_v13 = positive.get("cumulative_filtered_lsh_candidate_index_v13_band48", {})
    if candidate_index_v13.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V13_VALIDATED":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v13_not_validated", "actual": candidate_index_v13})
    if candidate_index_v13.get("index_row_count") != 28187 or candidate_index_v13.get("collision_bucket_count") != 28187 or candidate_index_v13.get("collision_document_memberships") != 113267 or candidate_index_v13.get("candidate_pair_upper_bound_before_deduplication") != 20960528:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v13_counts_invalid", "actual": candidate_index_v13})
    expected_v13_windows = {0: (0, 25, 70, 0, 0.799622), 25: (25, 50, 106, 0, 0.795349), 50: (50, 75, 135, 0, 0.797549), 75: (75, 100, 207, 0, 0.789764), 100: (100, 125, 728699, 0, 0.799472), 125: (125, 150, 217, 0, 0.796676), 150: (150, 175, 80, 17, 0.972644), 175: (175, 200, 77, 44, 0.976217)}
    for skip, expected in expected_v13_windows.items():
        row = positive.get(f"cumulative_filtered_lsh_candidate_index_v13_band48_adjudication_partial25_skip{skip}", {})
        start, end, pairs, crossings, max_j = expected
        if row.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V13_EXACT_ADJUDICATION_VALIDATED" or row.get("index_row_start_offset") != start or row.get("index_row_end_exclusive") != end or row.get("candidate_pair_count") != pairs or row.get("crossing_pair_count") != crossings or row.get("max_exact_jaccard_observed") != max_j:
            failures.append({"code": "cumulative_filtered_lsh_candidate_index_v13_window_invalid", "skip": skip, "actual": row})
    remediation_v13_window200 = positive.get("cumulative_filtered_lsh_candidate_index_v13_band48_adjudication_window200_remediation", {})
    if remediation_v13_window200.get("verdict") != "C1_LSH_CANDIDATE_ADJUDICATION_V13_REMEDIATION_PACKET_READY_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v13_window200_remediation_bad_verdict", "actual": remediation_v13_window200})
    if remediation_v13_window200.get("index_rows_adjudicated") != 200 or remediation_v13_window200.get("input_crossing_pair_count") != 61 or remediation_v13_window200.get("remediation_exclusion_document_count") != 28 or remediation_v13_window200.get("cluster_count") != 17 or remediation_v13_window200.get("existing_cumulative_v13_manifest_overlap_count") != 0:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v13_window200_remediation_counts_invalid", "actual": remediation_v13_window200})
    cumulative_manifest_v14 = positive.get("near_duplicate_cumulative_exclusion_manifest_v14", {})
    if cumulative_manifest_v14.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V14_VALIDATED" or cumulative_manifest_v14.get("materialization_verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V14_READY_NOT_COMPLETION":
        failures.append({"code": "near_duplicate_cumulative_manifest_v14_not_validated", "actual": cumulative_manifest_v14})
    if cumulative_manifest_v14.get("exclusion_document_count") != 1952 or cumulative_manifest_v14.get("exclusion_token_floor") != 3329164 or cumulative_manifest_v14.get("source_overlap_count") != 0:
        failures.append({"code": "near_duplicate_cumulative_manifest_v14_scope_mismatch", "actual": cumulative_manifest_v14})
    cumulative_view_v14 = positive.get("cumulative_filtered_corpus_view_v14", {})
    if cumulative_view_v14.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V14_VALIDATED" or cumulative_view_v14.get("materialization_verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V14_READY_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_view_v14_not_validated", "actual": cumulative_view_v14})
    if cumulative_view_v14.get("excluded_document_count") != 1952 or cumulative_view_v14.get("excluded_token_floor") != 3329164 or cumulative_view_v14.get("remaining_document_count") != 4234506 or cumulative_view_v14.get("remaining_content_token_floor") != 6974539594 or cumulative_view_v14.get("binary_shards_rewritten") is not False:
        failures.append({"code": "cumulative_filtered_view_v14_scope_mismatch", "actual": cumulative_view_v14})
    cumulative_challenge_v4 = positive.get("cumulative_filtered_near_duplicate_challenge_sample_v4", {})
    if cumulative_challenge_v4.get("verdict") != "C1_CUMULATIVE_FILTERED_NEAR_DUPLICATE_SAMPLE_V4_VALIDATED":
        failures.append({"code": "cumulative_filtered_challenge_v4_not_validated", "actual": cumulative_challenge_v4})
    if cumulative_challenge_v4.get("sampled_documents", 0) < 50000 or cumulative_challenge_v4.get("sampled_excluded_document_count") != 0 or cumulative_challenge_v4.get("excluded_document_count") != 1719:
        failures.append({"code": "cumulative_filtered_challenge_v4_scope_mismatch", "actual": cumulative_challenge_v4})
    if cumulative_challenge_v4.get("crossing_pair_count") != 0 or cumulative_challenge_v4.get("max_exact_jaccard_observed", 1) >= 0.8:
        failures.append({"code": "cumulative_filtered_challenge_v4_not_bounded_clear", "actual": cumulative_challenge_v4})
    if "not an all-pairs near-duplicate PASS" not in str(cumulative_challenge_v4.get("scope_limit", "")):
        failures.append({"code": "cumulative_filtered_challenge_v4_missing_noncompletion_guard", "actual": cumulative_challenge_v4.get("scope_limit")})
    lsh_census_v4 = positive.get("cumulative_filtered_lsh_bucket_census_v4", {})
    if lsh_census_v4.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_VALIDATED":
        failures.append({"code": "cumulative_filtered_lsh_census_v4_not_validated", "actual": lsh_census_v4})
    if lsh_census_v4.get("scan_verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_PARTIAL_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_lsh_census_v4_scan_verdict_unexpected", "actual": lsh_census_v4})
    if lsh_census_v4.get("full_document_coverage") is not True or lsh_census_v4.get("full_band_coverage") is not False:
        failures.append({"code": "cumulative_filtered_lsh_census_v4_coverage_invalid", "actual": lsh_census_v4})
    if lsh_census_v4.get("band_count_scanned") != 1 or lsh_census_v4.get("band_starts_scanned") != [0]:
        failures.append({"code": "cumulative_filtered_lsh_census_v4_band_scope_invalid", "actual": lsh_census_v4})
    if lsh_census_v4.get("documents_censused") != 3806884 or lsh_census_v4.get("collision_bucket_count") != 28337 or lsh_census_v4.get("max_bucket_size") != 2994:
        failures.append({"code": "cumulative_filtered_lsh_census_v4_counts_invalid", "actual": lsh_census_v4})
    if "not an all-pairs near-duplicate PASS" not in str(lsh_census_v4.get("scope_limit", "")):
        failures.append({"code": "cumulative_filtered_lsh_census_v4_missing_noncompletion_guard", "actual": lsh_census_v4.get("scope_limit")})
    lsh_band_coverage = positive.get("cumulative_filtered_lsh_bucket_census_v4_band_coverage", {})
    if lsh_band_coverage.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_16_OF_16_BANDS_VALIDATED":
        failures.append({"code": "cumulative_filtered_lsh_band_coverage_not_validated", "actual": lsh_band_coverage})
    if lsh_band_coverage.get("covered_band_starts") != [0, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 60] or lsh_band_coverage.get("covered_band_count") != 16:
        failures.append({"code": "cumulative_filtered_lsh_band_coverage_scope_invalid", "actual": lsh_band_coverage})
    if lsh_band_coverage.get("remaining_band_starts") != []:
        failures.append({"code": "cumulative_filtered_lsh_remaining_bands_invalid", "actual": lsh_band_coverage.get("remaining_band_starts")})
    if lsh_band_coverage.get("all_scanned_bands_full_document_coverage") is not True or lsh_band_coverage.get("all_scanned_bands_validated") is not True:
        failures.append({"code": "cumulative_filtered_lsh_band_coverage_invalid", "actual": lsh_band_coverage})
    if lsh_band_coverage.get("total_collision_bucket_count_observed_across_scanned_bands") != 460200 or lsh_band_coverage.get("max_bucket_size_observed_across_scanned_bands") != 5741:
        failures.append({"code": "cumulative_filtered_lsh_band_coverage_counts_invalid", "actual": lsh_band_coverage})
    if "not exact all-pairs Jaccard adjudication" not in str(lsh_band_coverage.get("scope_limit", "")):
        failures.append({"code": "cumulative_filtered_lsh_band_coverage_missing_noncompletion_guard", "actual": lsh_band_coverage.get("scope_limit")})
    lsh_candidate_index_v4_band48 = positive.get("cumulative_filtered_lsh_candidate_index_v4_band48", {})
    if lsh_candidate_index_v4_band48.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V4_VALIDATED":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v4_band48_not_validated", "actual": lsh_candidate_index_v4_band48})
    if lsh_candidate_index_v4_band48.get("materialization_verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V4_MATERIALIZED_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v4_band48_bad_materialization", "actual": lsh_candidate_index_v4_band48})
    if lsh_candidate_index_v4_band48.get("band_starts_materialized") != [48] or lsh_candidate_index_v4_band48.get("collision_bucket_count") != 28289:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v4_band48_scope_invalid", "actual": lsh_candidate_index_v4_band48})
    if lsh_candidate_index_v4_band48.get("candidate_pair_upper_bound_before_deduplication") != 20991666 or lsh_candidate_index_v4_band48.get("max_bucket_size") != 5741:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v4_band48_counts_invalid", "actual": lsh_candidate_index_v4_band48})
    if "not exact Jaccard adjudication" not in str(lsh_candidate_index_v4_band48.get("scope_limit", "")):
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v4_band48_missing_noncompletion_guard", "actual": lsh_candidate_index_v4_band48.get("scope_limit")})
    partial_adjudication_v4_band48 = positive.get("cumulative_filtered_lsh_candidate_index_v4_band48_adjudication_partial25", {})
    if partial_adjudication_v4_band48.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V4_EXACT_ADJUDICATION_VALIDATED":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v4_band48_partial_adjudication_not_validated", "actual": partial_adjudication_v4_band48})
    if partial_adjudication_v4_band48.get("adjudication_verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V4_EXACT_ADJUDICATION_CROSSINGS_FOUND_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v4_band48_partial_adjudication_bad_verdict", "actual": partial_adjudication_v4_band48})
    if partial_adjudication_v4_band48.get("index_rows_adjudicated") != 25 or partial_adjudication_v4_band48.get("crossing_pair_count") != 17:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v4_band48_partial_adjudication_counts_invalid", "actual": partial_adjudication_v4_band48})
    if partial_adjudication_v4_band48.get("max_exact_jaccard_observed") != 0.970803 or partial_adjudication_v4_band48.get("candidate_pair_count") != 75:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v4_band48_partial_adjudication_metrics_invalid", "actual": partial_adjudication_v4_band48})
    if "not full band-48 adjudication" not in str(partial_adjudication_v4_band48.get("scope_limit", "")):
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v4_band48_partial_adjudication_missing_noncompletion_guard", "actual": partial_adjudication_v4_band48.get("scope_limit")})
    partial_remediation_v4_band48 = positive.get("cumulative_filtered_lsh_candidate_index_v4_band48_adjudication_partial25_remediation", {})
    if partial_remediation_v4_band48.get("verdict") != "C1_LSH_CANDIDATE_ADJUDICATION_V4_REMEDIATION_PACKET_READY_NOT_COMPLETION":
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v4_band48_partial_remediation_bad_verdict", "actual": partial_remediation_v4_band48})
    if partial_remediation_v4_band48.get("remediation_exclusion_document_count") != 14 or partial_remediation_v4_band48.get("cluster_count") != 12:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v4_band48_partial_remediation_counts_invalid", "actual": partial_remediation_v4_band48})
    if partial_remediation_v4_band48.get("existing_cumulative_manifest_overlap_count") != 0:
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v4_band48_partial_remediation_overlap", "actual": partial_remediation_v4_band48})
    if "not a full band-48 remediation" not in str(partial_remediation_v4_band48.get("scope_limit", "")):
        failures.append({"code": "cumulative_filtered_lsh_candidate_index_v4_band48_partial_remediation_missing_noncompletion_guard", "actual": partial_remediation_v4_band48.get("scope_limit")})
    for key in ("exact_document_dedupe_scan", "exact_document_dedupe_validation"):
        row = audited.get(key, {})
        if not row.get("repo_path") or not row.get("sha256"):
            failures.append({"code": "exact_dedupe_audited_source_missing_pin", "key": key, "row": row})
    gaps = receipt.get("required_c1_hygiene_gaps", {})
    missing = sorted(REQUIRED_GAPS - set(gaps))
    if missing:
        failures.append({"code": "required_gap_missing", "gaps": missing})
    for key in REQUIRED_GAPS & set(gaps):
        if key == "eval_suite_contamination_scan":
            allowed = {"MISSING_C1_RECEIPT", "MISSING_FULL_EVAL_SUITE_AND_NORMALIZED_SPAN_RECEIPT", "AVAILABLE_EVAL_TEXT_INVENTORY_READY_FULL_EXTERNAL_SUITE_AND_TOKEN_CORPUS_NORMALIZED_SCAN_REQUIRED"}
            if gaps.get(key) not in allowed:
                failures.append({"code": "gap_not_marked_missing", "key": key, "actual": gaps.get(key)})
        elif gaps.get(key) not in {"MISSING_C1_RECEIPT", "BOUNDED_SAMPLE_FOUND_CANDIDATES_FULL_CORPUS_REMEDIATION_REQUIRED", "SAMPLE_REMEDIATION_READY_FULL_CORPUS_SCAN_AND_PASS_REQUIRED", "TARGETED_EXPANSION_READY_ALL_PAIRS_SCAN_AND_PASS_REQUIRED", "TARGETED_EXCLUSION_MANIFEST_READY_ALL_PAIRS_SCAN_AND_PASS_REQUIRED", "TARGETED_FILTERED_VIEW_READY_ALL_PAIRS_SCAN_AND_PASS_REQUIRED", "TARGETED_FILTERED_CHALLENGE_FOUND_CANDIDATES_ALL_PAIRS_PASS_REQUIRED", "TARGETED_FILTERED_CHALLENGE_REMEDIATION_READY_ALL_PAIRS_PASS_REQUIRED", "CUMULATIVE_FILTERED_V2_CHALLENGE_FOUND_CANDIDATES_ALL_PAIRS_PASS_REQUIRED", "CUMULATIVE_FILTERED_V3_CHALLENGE_FOUND_CANDIDATES_ALL_PAIRS_PASS_REQUIRED", "CUMULATIVE_FILTERED_V4_CHALLENGE_SAMPLE_NO_CROSSINGS_ALL_PAIRS_PASS_REQUIRED", "CUMULATIVE_FILTERED_V4_LSH_BAND0_CENSUS_READY_REMAINING_BANDS_AND_EXACT_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V4_LSH_3_OF_16_BANDS_READY_REMAINING_BANDS_AND_EXACT_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V4_LSH_6_OF_16_BANDS_READY_REMAINING_BANDS_AND_EXACT_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V4_LSH_9_OF_16_BANDS_READY_REMAINING_BANDS_AND_EXACT_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V4_LSH_16_OF_16_BANDS_READY_EXACT_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V4_LSH_BAND48_CANDIDATE_INDEX_READY_EXACT_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V4_LSH_BAND48_PARTIAL_ADJUDICATION_FOUND_CROSSINGS_REMEDIATION_REQUIRED", "CUMULATIVE_FILTERED_V5_PARTIAL_LSH_ADJUDICATION_REMEDIATED_FULL_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V6_PARTIAL_LSH_ADJUDICATION_REMEDIATED_FULL_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V7_PARTIAL_LSH_ADJUDICATION_REMEDIATED_FULL_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V8_PARTIAL_LSH_ADJUDICATION_REMEDIATED_FULL_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V9_WINDOW50_LSH_ADJUDICATION_REMEDIATED_FULL_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V10_WINDOW100_LSH_ADJUDICATION_REMEDIATED_FULL_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V11_WINDOW125_LSH_ADJUDICATION_REMEDIATED_FULL_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V12_WINDOW150_LSH_ADJUDICATION_REMEDIATED_FULL_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V13_WINDOW175_LSH_ADJUDICATION_REMEDIATED_FULL_ADJUDICATION_REQUIRED"}:
            failures.append({"code": "gap_not_marked_blocking", "key": key, "actual": gaps.get(key)})
    if receipt.get("c1_blocking_status") != "BLOCKS_C1_BASELINE_COMPLETE_UNTIL_REPLACED_BY_PASS_RECEIPTS":
        failures.append({"code": "blocking_status_missing", "actual": receipt.get("c1_blocking_status")})
    if "not overall baseline completion" not in str(receipt.get("completion_limit", "")):
        failures.append({"code": "missing_noncompletion_guard"})
    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_DATA_HYGIENE_AUDIT_VALIDATED" if not failures else "C1_DATA_HYGIENE_AUDIT_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "receipt_path": "receipts/4090-data-hygiene-audit-2026-06-30.json",
        "completion_limit": "This validates an explicit C1 data-hygiene gap audit only. It is not a full near-duplicate/contamination PASS and not overall baseline completion.",
    }
    text = json.dumps(result, indent=2 if args.pretty else None, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
