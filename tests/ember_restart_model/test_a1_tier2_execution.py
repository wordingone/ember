# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed terminal receipt tests for the owned A1 Tier-2 route."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from unittest import mock

import pytest


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools" / "ember-restart-3b"
sys.path.insert(0, str(TOOLS))


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "a1_tier2_execution_under_test", TOOLS / "a1_tier2_execution.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(root: Path) -> dict[str, Path | dict]:
    artifact = root / "artifact"
    artifact.mkdir()
    contract = root / "tier2-contract.json"
    liveness = root / "liveness.json"
    contract.write_bytes(b"tier2 contract bytes\n")
    liveness.write_bytes(b"liveness bytes\n")
    identity = {
        "comparison_id": "cmp-1464",
        "corpus_authority_sha256": "1" * 64,
        "shard_sequence_sha256": "2" * 64,
        "tokenizer_sha256": "3" * 64,
        "seed": 17,
        "cursor_start": {"global_step": 0, "record_index": 0, "tokens_seen": 0},
        "schedule_sha256": "4" * 64,
        "genesis_sha256": "5" * 64,
    }
    matched = root / "a3-run.json"
    _write(matched, {"identity": identity})
    comparison = root / "comparison.json"
    _write(comparison, {
        "comparison_id": "cmp-1464",
        "genesis_authority_sha256": "6" * 64,
        "matched_a3_run": {"path": matched.name, "sha256": _sha(matched)},
    })
    thresholds = root / "thresholds.json"
    _write(thresholds, {
        "schema_version": "ember02-preregistration-thresholds-v1",
        "frozen": True,
        "entries": [{"id": "T-06", "value": "0.95"}],
    })
    energy = root / "energy.json"
    _write(energy, {
        "schema_version": "ember-energy-proxy-run-v1",
        "result": "MEASURED",
        "executed": True,
        "training_launched": True,
        "intended_samples": 100,
        "captured_samples": 100,
        "t06_coverage_floor": "0.95",
        "coverage_meets_t06": True,
        "energy": {"sample_coverage_fraction": "1"},
    })
    source = "a" * 40
    launch = "b" * 64
    checkpoint_identity = {
        "comparison_id": "cmp-1464",
        "matched_identity": identity,
        "config_sha256": MODULE.A1_CONFIG_SHA256,
        "tier2_contract_sha256": _sha(contract),
        "liveness_sha256": _sha(liveness),
        "source_commit": source,
        "certified_launch_sha256": launch,
        "tier": "TIER_2",
        "mechanism": "OWNED_Q_GALORE_PROJECTED_GRADIENT",
        "predecessor": None,
    }
    core = {
        "schema_version": MODULE.CORE_SCHEMA,
        "status": "TERMINAL",
        "source_commit": source,
        "certified_launch_sha256": launch,
        "parameter_count": 3_839_000_000,
        "optimizer_inventory": {
            "schema_version": "ember-a1-tier2-state-inventory-v1",
            "state_format": "ember-a1-tier2-q-galore-cuda-v1",
            "registered_parameters": 7,
            "registered_numel": 3_839_000_000,
            "initialized_parameters": 7,
            "quantized_payload_bytes": 123,
            "fp32_scale_bytes": 45,
            "persistent_state_device": "cuda",
            "cpu_persistent_state_bytes": 0,
            "complete": True,
        },
        "checkpoint_sha256": "c" * 64,
        "checkpoint_identity": checkpoint_identity,
        "resource_preflight": {
            "schema_version": "ember-a1-tier2-resource-preflight-v1",
            "status": "PASS",
            "parameter_count": 3_839_000_000,
            "cpu_persistent_state_bytes": 0,
            "host_full_gradient_bytes": 0,
            "host_master_weight_bytes": 0,
            "persistent_state_device": "cuda",
        },
        "comparison_authority": {"path": str(comparison), "sha256": _sha(comparison)},
        "tier2_contract": {"path": str(contract), "sha256": _sha(contract)},
        "liveness_receipt": {"path": str(liveness), "sha256": _sha(liveness)},
    }
    _write(artifact / "a1-tier2-run-core.json", core)
    return {
        "artifact": artifact, "comparison": comparison, "contract": contract,
        "liveness": liveness, "thresholds": thresholds, "energy": energy,
        "source": source, "launch": launch, "core": core,
    }


def _finalize(paths: dict[str, Path | dict]) -> Path:
    return MODULE.finalize_tier2_run(
        artifact_root=paths["artifact"], energy_receipt=paths["energy"],
        thresholds_path=paths["thresholds"], expected_source_commit=paths["source"],
        expected_certified_launch_sha256=paths["launch"],
        expected_comparison_authority=paths["comparison"],
        expected_tier2_contract=paths["contract"],
        expected_liveness_receipt=paths["liveness"],
    )


def test_finalizer_emits_truthful_closed_tier2_receipt(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    output = _finalize(paths)
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["tier"] == "TIER2"
    assert receipt["mechanism"] == "OWNED_Q_GALORE_PROJECTED_GRADIENT"
    assert receipt["optimizer"] == {
        "kind": "OWNED_Q_GALORE_PROJECTED_GRADIENT", "full_state": False,
        "cpu_offload": False, "covered_parameter_count": 3_839_000_000,
    }
    assert receipt["parameter_count"] == receipt["active_parameter_count"]
    assert receipt["checkpoint_sha256"] == "c" * 64
    digest = receipt.pop("receipt_sha256")
    assert digest == hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def test_finalizer_refuses_self_asserted_config_identity(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    core = paths["core"]
    assert isinstance(core, dict)
    core["checkpoint_identity"]["config_sha256"] = "d" * 64
    _write(paths["artifact"] / "a1-tier2-run-core.json", core)
    with pytest.raises(ValueError, match="checkpoint identity"):
        _finalize(paths)


def test_finalizer_refuses_inconsistent_energy_coverage(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    energy = json.loads(paths["energy"].read_text(encoding="utf-8"))
    energy["captured_samples"] = 50
    _write(paths["energy"], energy)
    with pytest.raises(ValueError, match="energy sample coverage"):
        _finalize(paths)


def test_finalizer_refuses_open_core_and_off_device_inventory(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    core = paths["core"]
    assert isinstance(core, dict)
    core["unexpected"] = True
    _write(paths["artifact"] / "a1-tier2-run-core.json", core)
    with pytest.raises(ValueError, match="schema is not closed"):
        _finalize(paths)

    del core["unexpected"]
    core["optimizer_inventory"]["persistent_state_device"] = "cpu"
    _write(paths["artifact"] / "a1-tier2-run-core.json", core)
    with pytest.raises(ValueError, match="off-device"):
        _finalize(paths)


def test_execution_enables_ruled_determinism_before_cuda_admission(tmp_path: Path) -> None:
    preflight = {
        "schema_version": "ember-a1-tier2-resource-preflight-v1",
        "status": "PASS",
        "cpu_persistent_state_bytes": 0,
        "host_full_gradient_bytes": 0,
        "host_master_weight_bytes": 0,
    }
    environment = {
        "EMBER_A1_SOURCE_COMMIT": "a" * 40,
        "EMBER_A1_CERTIFIED_LAUNCH_SHA256": "b" * 64,
        "CUBLAS_WORKSPACE_CONFIG": ":4096:8",
    }
    with (
        mock.patch.dict(os.environ, environment, clear=True),
        mock.patch.object(MODULE.torch, "use_deterministic_algorithms") as enable,
        mock.patch.object(MODULE.torch, "are_deterministic_algorithms_enabled", return_value=True),
        mock.patch.object(MODULE.torch.cuda, "is_available", return_value=False),
        pytest.raises(RuntimeError, match="CUDA is required"),
    ):
        MODULE.run_dense_a1_tier2(
            repo_root=tmp_path, seed=17, artifact_root=tmp_path / "artifact",
            token_shards_receipt=tmp_path / "tokens.json", shards_root=tmp_path,
            comparison_authority=tmp_path / "comparison.json", steps=1,
            sequence_length=8, checkpoint_interval=1,
            telemetry_path=tmp_path / "telemetry.jsonl", telemetry_run_id="tier2",
            tier2_contract_path=tmp_path / "contract.json",
            expected_tier2_contract_sha256="c" * 64,
            liveness_receipt=tmp_path / "liveness.json",
            expected_liveness_receipt_sha256="d" * 64,
            resource_preflight=preflight,
        )
    enable.assert_called_once_with(True)
