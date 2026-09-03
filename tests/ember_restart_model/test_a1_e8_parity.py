# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import copy
import hashlib
import importlib
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools" / "ember-restart-3b"
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(SCRIPTS))


def _module():
    return importlib.import_module("a1_e8_parity")


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _write(path: Path, value: dict, *, digest_field: str | None = None) -> str:
    payload = copy.deepcopy(value)
    if digest_field:
        payload[digest_field] = hashlib.sha256(_canonical(payload)).hexdigest()
    path.write_bytes(_canonical(payload) + b"\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity() -> dict:
    return {
        "comparison_id": "r1-e8-a1-vs-a3",
        "corpus_authority_sha256": "1" * 64,
        "shard_sequence_sha256": "2" * 64,
        "tokenizer_sha256": "3" * 64,
        "seed": 147,
        "cursor_start": {"global_step": 0, "record_index": 0, "tokens_seen": 0},
        "schedule_sha256": "4" * 64,
        "genesis_sha256": "5" * 64,
    }


def _run(tier: str, mechanism: str, *, cpu_offload: bool) -> dict:
    return {
        "schema_version": "ember02-r1-e8-run-v1",
        "arm_id": "A1",
        "tier": tier,
        "mechanism": mechanism,
        "status": "TERMINAL",
        "certified_launch_sha256": "6" * 64,
        "source_commit": "a" * 40,
        "architecture_revision": "ember-dense-a1-3b-v1",
        "parameter_count": 3_839_344_640,
        "active_parameter_count": 3_839_344_640,
        "contains_router_or_experts": False,
        "optimizer": {
            "kind": "AdamW", "full_state": True, "cpu_offload": cpu_offload,
            "covered_parameter_count": 3_839_344_640,
        },
        "identity": _identity(),
        "energy_sample_coverage": "1.000000000000",
        "checkpoint_sha256": "7" * 64,
    }


def _telemetry(path: Path, run_id: str, *, loss_delta: float = 0.0) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for step in range(1, 101):
            handle.write(json.dumps({
                "ts": f"2026-08-21T00:{step // 60:02d}:{step % 60:02d}Z",
                "kind": "train_step",
                "source": "ember-restart-3b",
                "payload": {
                    "run_id": run_id,
                    "step": step,
                    "loss": f"{1 + step / 1000 + loss_delta:.12f}",
                    "grad_norm": "2.000000000000",
                },
            }, sort_keys=True) + "\n")


def test_derive_parity_series_requires_exact_contiguous_window(tmp_path: Path) -> None:
    """Catches accepting a partial or duplicate matched-step series."""
    module = _module()
    telemetry = tmp_path / "training.jsonl"
    _telemetry(telemetry, "candidate")
    series = module.derive_parity_series(
        telemetry, run_id="candidate", run_receipt_sha256="a" * 64, steps=100,
    )
    assert series["samples"][0] == {"step": 1, "loss": "1.001000000000", "grad_norm": "2.000000000000"}
    assert series["samples"][-1]["step"] == 100

    rows = telemetry.read_text("utf-8").splitlines()
    telemetry.write_text("\n".join(rows[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="contiguous"):
        module.derive_parity_series(
            telemetry, run_id="candidate", run_receipt_sha256="a" * 64, steps=100,
        )


def test_mint_parity_receipt_matches_real_validator_and_no_overwrite(tmp_path: Path) -> None:
    """Catches producer/validator arithmetic drift or mutable packet custody."""
    module = _module()
    validator = importlib.import_module("r1_e8_validator")
    battery = importlib.import_module("r1_exit_battery")
    thresholds, thresholds_sha = battery.load_thresholds()
    candidate = tmp_path / "tier2-run.json"
    reference = tmp_path / "tier1-reference-run.json"
    _write(candidate, _run("TIER2", "owned-projected-gradient", cpu_offload=False), digest_field="receipt_sha256")
    _write(reference, _run("TIER1", "adamw-cpu-offload", cpu_offload=True), digest_field="receipt_sha256")
    liveness = tmp_path / "a1-e8-liveness.json"
    _write(liveness, {
        "schema_version": "ember02-r1-e8-liveness-v1",
        "thresholds_sha256": thresholds_sha,
        "verdict": "FALLBACK_REQUIRED",
    }, digest_field="receipt_sha256")
    e7 = tmp_path / "r1-e7-v2.json"
    _write(e7, {
        "schema": "r1-exit-battery/v1",
        "exit_criterion": "R1-E7",
        "status": "MET",
        "prereg": {"thresholds_sha256": thresholds_sha},
        "result": {"sigma_seed": {
            "loss": {"sigma_seed": "0.1"},
            "grad_norm_ratio": {"sigma_seed": "0.1"},
            "grad_norm": {"sigma_seed": "0.2", "validator_input": False},
        }},
    }, digest_field="receipt_sha256")
    candidate_telemetry = tmp_path / "candidate.jsonl"
    reference_telemetry = tmp_path / "reference.jsonl"
    _telemetry(candidate_telemetry, "candidate")
    _telemetry(reference_telemetry, "reference")

    receipt_path = module.mint_parity_receipt(
        packet_root=tmp_path,
        candidate_run=candidate,
        reference_run=reference,
        candidate_telemetry=candidate_telemetry,
        candidate_run_id="candidate",
        reference_telemetry=reference_telemetry,
        reference_run_id="reference",
        liveness_receipt=liveness,
        thresholds_path=ROOT / "docs" / "spec" / "ember02-preregistration-thresholds-v1.json",
        e7_receipt=e7,
    )
    result = validator._validate_parity(
        receipt_path,
        liveness_sha=hashlib.sha256(liveness.read_bytes()).hexdigest(),
        thresholds=thresholds,
        thresholds_sha256=thresholds_sha,
        t06=validator._decimal(thresholds["T-06"], "T06_INVALID"),
    )
    assert result["status"] == "MET"
    first = {path.name: path.read_bytes() for path in tmp_path.glob("*parity*.json")}
    with pytest.raises(FileExistsError):
        module.mint_parity_receipt(
            packet_root=tmp_path,
            candidate_run=candidate,
            reference_run=reference,
            candidate_telemetry=candidate_telemetry,
            candidate_run_id="candidate",
            reference_telemetry=reference_telemetry,
            reference_run_id="reference",
            liveness_receipt=liveness,
            thresholds_path=ROOT / "docs" / "spec" / "ember02-preregistration-thresholds-v1.json",
            e7_receipt=e7,
        )
    assert first == {path.name: path.read_bytes() for path in tmp_path.glob("*parity*.json")}
