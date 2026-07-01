#!/usr/bin/env python3
"""Validate C1 single-4090 data-governance evidence.

This validates token-substrate provenance and explicit data gaps. It does not
turn data readiness into training completion.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPECTED_VERDICT = "C1_DATA_GOVERNANCE_EVIDENCE_READY_WITH_EXPLICIT_GAPS"


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
    receipt_path = root / "receipts/4090-data-governance-2026-06-30.json"
    protocol_path = root / "protocols/4090-data-governance-v0.md"
    receipt = read_json(receipt_path) if receipt_path.exists() else {}
    if receipt.get("verdict") != EXPECTED_VERDICT:
        failures.append({"code": "data_governance_bad_verdict", "actual": receipt.get("verdict")})
    if not protocol_path.exists() or "Status: SUPPORTING EVIDENCE, NOT COMPLETION" not in protocol_path.read_text(encoding="utf-8-sig", errors="replace"):
        failures.append({"code": "protocol_missing_noncompletion_guard"})
    evidence = receipt.get("source_evidence", {})
    for key in ("v0_pretrain_config", "token_shards_receipt", "tokenizer_freeze_receipt", "real_data_lm_loss_probe_from_scratch", "real_data_lm_loss_probe_pretraining_equivalent", "real_data_lm_loss_validation", "checkpoint_resume_probe_pretraining_equivalent", "checkpoint_resume_validation", "multistep_stability_probe_pretraining_equivalent", "multistep_stability_validation", "steady_state_throughput_probe_pretraining_equivalent", "steady_state_throughput_validation", "varied_window_throughput_probe_pretraining_equivalent", "varied_window_throughput_validation", "streamed_window_throughput_probe_pretraining_equivalent", "streamed_window_throughput_validation", "streamed_128_window_throughput_probe_pretraining_equivalent", "streamed_128_window_throughput_validation", "power_sampled_128_window_probe_pretraining_equivalent", "power_sampled_128_window_receipt", "power_sampled_128_window_validation", "checkpoint_cadence_probe_pretraining_equivalent", "checkpoint_cadence_validation", "eval_accounting_probe_pretraining_equivalent", "eval_accounting_validation", "recovery_accounting_probe_pretraining_equivalent", "recovery_accounting_validation", "integrated_policy_probe_pretraining_equivalent", "integrated_policy_validation", "policy_amortized_256_window_probe_pretraining_equivalent", "policy_amortized_256_window_power", "policy_amortized_256_window_validation"):
        row = evidence.get(key, {})
        if not row.get("repo_path") or not row.get("sha256"):
            failures.append({"code": "source_evidence_missing_pin", "key": key, "row": row})
    tokenizer = receipt.get("tokenizer", {})
    if tokenizer.get("frozen_pre_step0") is not True or tokenizer.get("tokens_pending_tokenizer_freeze") is not False:
        failures.append({"code": "tokenizer_not_frozen_cleanly", "tokenizer": tokenizer})
    if tokenizer.get("c1_vocab_compatibility") != "PASS_TOKEN_IDS_FIT_C1_VOCAB":
        failures.append({"code": "c1_vocab_compatibility_not_pass", "tokenizer": tokenizer})
    if tokenizer.get("reserved_band_observed_in_stream") != 0:
        failures.append({"code": "reserved_band_observed_in_stream", "actual": tokenizer.get("reserved_band_observed_in_stream")})
    corpus = receipt.get("corpus", {})
    if corpus.get("content_total_tokens", 0) < 5_000_000_000:
        failures.append({"code": "content_tokens_below_pretraining_floor", "actual": corpus.get("content_total_tokens")})
    if corpus.get("shard_count", 0) < 1 or not corpus.get("shard_hashes"):
        failures.append({"code": "shard_hashes_missing", "corpus": corpus})
    lanes = receipt.get("lane_readiness", {})
    from_lane = lanes.get("from_scratch", {})
    pre_lane = lanes.get("pretraining_equivalent", {})
    if from_lane.get("status") != "TOKEN_SHORTFALL_FOR_LOCKED_10B_FROM_SCRATCH_LANE" or from_lane.get("missing_tokens", 0) <= 0:
        failures.append({"code": "from_scratch_gap_not_explicit", "lane": from_lane})
    if pre_lane.get("status") != "TOKEN_FLOOR_READY_FOR_LOCKED_5B_PRETRAINING_EQUIVALENT_LANE":
        failures.append({"code": "pretraining_lane_not_token_ready", "lane": pre_lane})
    gaps = receipt.get("governance_gaps", {})
    for key in ("dedupe_receipt_for_c1", "contamination_receipt_for_c1", "real_data_lm_loss_probe", "long_run_checkpoint_resume", "varied_window_throughput_probe", "streamed_window_throughput_probe", "power_sampled_128_window_probe", "checkpoint_cadence_probe", "eval_accounting_probe", "recovery_accounting_probe", "integrated_policy_probe", "policy_amortized_256_window_probe"):
        if not gaps.get(key) or gaps.get(key) in {"PASS", "DONE", "COMPLETE"}:
            failures.append({"code": "governance_gap_not_explicit", "key": key, "actual": gaps.get(key)})
    if gaps.get("real_data_lm_loss_probe") != "BOUNDED_REAL_TOKEN_FULL_STACK_LM_LOSS_PROBE_READY_LONG_RUN_STILL_REQUIRED":
        failures.append({"code": "real_data_lm_loss_probe_not_bounded_ready", "actual": gaps.get("real_data_lm_loss_probe")})
    real_validation = root / "receipts/4090-real-data-lm-loss-validation-2026-06-30.json"
    if not real_validation.exists() or read_json(real_validation).get("verdict") != "C1_REAL_DATA_LM_LOSS_PROBE_VALIDATED":
        failures.append({"code": "real_data_lm_loss_validation_missing_or_invalid"})
    if gaps.get("long_run_checkpoint_resume") != "BOUNDED_REAL_TOKEN_CHECKPOINT_RESUME_PROBE_READY_LONG_RUN_CADENCE_STILL_REQUIRED":
        failures.append({"code": "checkpoint_resume_not_bounded_ready", "actual": gaps.get("long_run_checkpoint_resume")})
    checkpoint_validation = root / "receipts/4090-checkpoint-resume-validation-2026-06-30.json"
    if not checkpoint_validation.exists() or read_json(checkpoint_validation).get("verdict") != "C1_CHECKPOINT_RESUME_PROBE_VALIDATED":
        failures.append({"code": "checkpoint_resume_validation_missing_or_invalid"})
    if gaps.get("multistep_stability_probe") != "BOUNDED_SAME_WINDOW_REAL_TOKEN_MULTISTEP_STABILITY_READY_LONG_RUN_STILL_REQUIRED":
        failures.append({"code": "multistep_stability_not_bounded_ready", "actual": gaps.get("multistep_stability_probe")})
    stability_validation = root / "receipts/4090-multistep-stability-validation-2026-06-30.json"
    if not stability_validation.exists() or read_json(stability_validation).get("verdict") != "C1_MULTISTEP_STABILITY_PROBE_VALIDATED":
        failures.append({"code": "multistep_stability_validation_missing_or_invalid"})
    if gaps.get("steady_state_throughput_probe") != "BOUNDED_SAME_WINDOW_STEADY_STATE_THROUGHPUT_CLEARS_TFLOPS_LONG_RUN_STILL_REQUIRED":
        failures.append({"code": "steady_state_throughput_not_bounded_ready", "actual": gaps.get("steady_state_throughput_probe")})
    steady_validation = root / "receipts/4090-steady-state-throughput-validation-2026-06-30.json"
    if not steady_validation.exists() or read_json(steady_validation).get("verdict") != "C1_STEADY_STATE_THROUGHPUT_PROBE_VALIDATED":
        failures.append({"code": "steady_state_throughput_validation_missing_or_invalid"})
    if gaps.get("varied_window_throughput_probe") != "BOUNDED_VARIED_WINDOW_REAL_TOKEN_THROUGHPUT_CLEARS_TFLOPS_DATALOADER_LONG_RUN_STILL_REQUIRED":
        failures.append({"code": "varied_window_throughput_not_bounded_ready", "actual": gaps.get("varied_window_throughput_probe")})
    varied_validation = root / "receipts/4090-varied-window-throughput-validation-2026-06-30.json"
    if not varied_validation.exists() or read_json(varied_validation).get("verdict") != "C1_VARIED_WINDOW_THROUGHPUT_PROBE_VALIDATED":
        failures.append({"code": "varied_window_throughput_validation_missing_or_invalid"})
    if gaps.get("streamed_window_throughput_probe") != "BOUNDED_STREAMED_128_WINDOW_THROUGHPUT_CLEARS_TFLOPS_FULL_SHARD_LONG_RUN_STILL_REQUIRED":
        failures.append({"code": "streamed_window_throughput_not_bounded_ready", "actual": gaps.get("streamed_window_throughput_probe")})
    streamed_validation = root / "receipts/4090-streamed-window-throughput-validation-2026-06-30.json"
    if not streamed_validation.exists() or read_json(streamed_validation).get("verdict") != "C1_STREAMED_WINDOW_THROUGHPUT_PROBE_VALIDATED":
        failures.append({"code": "streamed_window_throughput_validation_missing_or_invalid"})
    streamed_128_validation = root / "receipts/4090-streamed-128-window-throughput-validation-2026-06-30.json"
    if not streamed_128_validation.exists() or read_json(streamed_128_validation).get("verdict") != "C1_STREAMED_128_WINDOW_THROUGHPUT_VALIDATED":
        failures.append({"code": "streamed_128_window_throughput_validation_missing_or_invalid"})
    if gaps.get("power_sampled_128_window_probe") != "BOUNDED_POWER_SAMPLED_128_WINDOW_READY_FULL_RUN_ENERGY_STILL_REQUIRED":
        failures.append({"code": "power_sampled_128_window_not_bounded_ready", "actual": gaps.get("power_sampled_128_window_probe")})
    power_validation = root / "receipts/4090-power-sampled-128-window-validation-2026-06-30.json"
    if not power_validation.exists() or read_json(power_validation).get("verdict") != "C1_POWER_SAMPLED_128_WINDOW_THROUGHPUT_VALIDATED":
        failures.append({"code": "power_sampled_128_window_validation_missing_or_invalid"})
    if gaps.get("checkpoint_cadence_probe") != "BOUNDED_STREAMED_CHECKPOINT_CADENCE_READY_LONG_RUN_POLICY_STILL_REQUIRED":
        failures.append({"code": "checkpoint_cadence_not_bounded_ready", "actual": gaps.get("checkpoint_cadence_probe")})
    cadence_validation = root / "receipts/4090-checkpoint-cadence-validation-2026-06-30.json"
    if not cadence_validation.exists() or read_json(cadence_validation).get("verdict") != "C1_CHECKPOINT_CADENCE_PROBE_VALIDATED":
        failures.append({"code": "checkpoint_cadence_validation_missing_or_invalid"})
    if gaps.get("eval_accounting_probe") != "BOUNDED_STREAMED_EVAL_ACCOUNTING_READY_FULL_EXTERNAL_EVAL_STILL_REQUIRED":
        failures.append({"code": "eval_accounting_not_bounded_ready", "actual": gaps.get("eval_accounting_probe")})
    eval_validation = root / "receipts/4090-eval-accounting-validation-2026-06-30.json"
    if not eval_validation.exists() or read_json(eval_validation).get("verdict") != "C1_EVAL_ACCOUNTING_PROBE_VALIDATED":
        failures.append({"code": "eval_accounting_validation_missing_or_invalid"})
    if gaps.get("recovery_accounting_probe") != "BOUNDED_STREAMED_RECOVERY_ACCOUNTING_READY_LONG_RUN_POLICY_STILL_REQUIRED":
        failures.append({"code": "recovery_accounting_not_bounded_ready", "actual": gaps.get("recovery_accounting_probe")})
    recovery_validation = root / "receipts/4090-recovery-accounting-validation-2026-06-30.json"
    if not recovery_validation.exists() or read_json(recovery_validation).get("verdict") != "C1_RECOVERY_ACCOUNTING_PROBE_VALIDATED":
        failures.append({"code": "recovery_accounting_validation_missing_or_invalid"})
    if gaps.get("integrated_policy_probe") != "BOUNDED_STREAMED_TRAIN_CHECKPOINT_EVAL_RECOVERY_READY_LONG_RUN_STILL_REQUIRED":
        failures.append({"code": "integrated_policy_not_bounded_ready", "actual": gaps.get("integrated_policy_probe")})
    integrated_validation = root / "receipts/4090-integrated-policy-validation-2026-06-30.json"
    if not integrated_validation.exists() or read_json(integrated_validation).get("verdict") != "C1_INTEGRATED_POLICY_PROBE_VALIDATED":
        failures.append({"code": "integrated_policy_validation_missing_or_invalid"})
    if gaps.get("policy_amortized_256_window_probe") != "BOUNDED_POLICY_AMORTIZED_256_WINDOW_MEASURED_BELOW_REQUIRED_LONG_RUN_STILL_REQUIRED":
        failures.append({"code": "policy_amortized_256_window_not_bounded_gap", "actual": gaps.get("policy_amortized_256_window_probe")})
    policy_validation = root / "receipts/4090-policy-amortized-256-window-validation-2026-06-30.json"
    if not policy_validation.exists() or read_json(policy_validation).get("verdict") != "C1_POLICY_AMORTIZED_256_WINDOW_VALIDATED":
        failures.append({"code": "policy_amortized_256_window_validation_missing_or_invalid"})
    if "not overall baseline completion" not in str(receipt.get("completion_limit", "")):
        failures.append({"code": "missing_noncompletion_guard"})
    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_DATA_GOVERNANCE_VALIDATED" if not failures else "C1_DATA_GOVERNANCE_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "receipt_path": "receipts/4090-data-governance-2026-06-30.json",
        "completion_limit": "This validates C1 data-governance evidence only. It is not a long-run training receipt and not overall baseline completion.",
    }
    text = json.dumps(result, indent=2 if args.pretty else None, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
