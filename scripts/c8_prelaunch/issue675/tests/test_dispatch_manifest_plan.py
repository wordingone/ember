# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
from pathlib import Path

import pytest
import torch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "q2_dispatch_manifest.py"


def _load():
    assert MODULE_PATH.exists(), "q2_dispatch_manifest.py is not implemented"
    sys.path.insert(0, str(ROOT))
    try:
        spec = importlib.util.spec_from_file_location("q2_dispatch_manifest", MODULE_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(ROOT))


def _files(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True)
    files = {
        "program": root / "python.exe",
        "producer": root / "q2_event.py",
        "config": root / "config.json",
        "checkpoint": root / "checkpoint.json",
        "batch": root / "batch.json",
        "threshold": root / "threshold.json",
        "verifier": root / "verifier.py",
        "host_commit_receipt": root / "host-commit-receipt.json",
        "gradient": root / "q2-gradient.pt",
        "b3_receipt": root / "b3.json",
        "producer_contract": root / "producer-contract.json",
    }
    for key, path in files.items():
        if key in {"gradient", "b3_receipt", "producer_contract"}:
            continue
        path.write_text(f"{key}\n", encoding="utf-8")
    files["producer"].write_text(
        'GOVERNED_VERTICAL_MODE = "governed-vertical"\n'
        "def run_governed_vertical(args):\n    return 0\n"
        "def main():\n    return run_governed_vertical(None)\n",
        encoding="utf-8",
    )
    for key in (
        "adapter",
        "event_inputs",
        "input_builder",
        "host_commit_probe",
        "host_commit_simulation",
        "measured_dry_run",
        "gradient_lineage",
        "model_lineage",
        "momentum_lineage",
        "muon",
        "rung2_runtime",
        "writer",
    ):
        path = root / f"component-{key}.py"
        path.write_text(f"COMPONENT = {key!r}\n", encoding="utf-8")
        files[f"component_{key}"] = path
    gib = 1024**3
    receipt = {
        "schema_version": "q2-host-commit-simulation-receipt-v1",
        "job_id": "q2-actual-update-001",
        "source_commit": "f3c92ba984711ee34e91c6bea90713e6c89b4b4d",
        "measurement_mode": "bounded_dry_run",
        "process": {"pid": 42, "started_at_ms": 1, "ended_at_ms": 2, "exit_code": 0},
        "bindings": {
            "measurement_tool_sha256": "b" * 64,
            "config_sha256": "c" * 64,
            "checkpoint_manifest_sha256": "d" * 64,
            "batch_manifest_sha256": "e" * 64,
            "producer_sha256": "f" * 64,
        },
        "phases": [],
        "simulated_peak_commit_bytes": 20 * gib,
        "maximum_job_memory_bytes": 20 * gib,
        "producer_budgets": {
            "training_data_loader": 5 * gib,
            "checkpoint_writer": 14 * gib,
            "telemetry_buffer": 1 * gib,
        },
        "trace_sha256": "a" * 64,
        "event_credit": False,
        "scientific_credit": False,
        "no_new_parallel_authority": True,
    }
    receipt["receipt_sha256"] = hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    files["host_commit_receipt"].write_text(json.dumps(receipt), encoding="utf-8")
    target_name = "backbone_model.layers.0.mlp.gate_proj.weight"
    batch_sha = "9" * 64
    torch.save(torch.ones((4, 2), dtype=torch.float32), files["gradient"])
    files["b3_receipt"].write_text(
        json.dumps(
            {
                "ticket": "CBASE-GROW-RUNG2-EVENT-B3",
                "run_id": "q2-actual-update-001",
                "batch_pin_check": {
                    "b1m_sha256": batch_sha,
                    "b3_recomputed_sha256": batch_sha,
                    "match": True,
                },
                "cache_paths": {"grad_post_gate": files["gradient"].name},
                "cache_sha256": {
                    "grad_post_gate": hashlib.sha256(
                        files["gradient"].read_bytes()
                    ).hexdigest()
                },
                "gradient_lineage": {
                    "target_name": target_name,
                    "dtype": "float32",
                    "shape": [4, 2],
                    "source": "pinned-batch-backward",
                    "batch_sha256": batch_sha,
                },
                "verdict": "B3_CAPTURED",
            }
        ),
        encoding="utf-8",
    )
    producer_contract = {
        "schema_version": "q2-governed-producer-contract-v1",
        "source_commit": "f3c92ba984711ee34e91c6bea90713e6c89b4b4d",
        "mode": "governed-vertical",
        "producer_sha256": hashlib.sha256(files["producer"].read_bytes()).hexdigest(),
        "component_sha256": {
            key: hashlib.sha256(files[f"component_{key}"].read_bytes()).hexdigest()
            for key in (
                "adapter",
                "event_inputs",
                "input_builder",
                "host_commit_probe",
                "host_commit_simulation",
                "measured_dry_run",
                "gradient_lineage",
                "model_lineage",
                "momentum_lineage",
                "muon",
                "rung2_runtime",
                "writer",
            )
        },
        "scope": "TARGET_TENSOR_COUNTERFACTUAL",
        "historical_dependencies": [],
        "claims": {
            "actual_event": False,
            "scientific_result": False,
            "whole_step": False,
            "material_loss_bridge": False,
        },
        "no_new_parallel_authority": True,
    }
    producer_contract["contract_sha256"] = hashlib.sha256(
        json.dumps(producer_contract, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    files["producer_contract"].write_text(json.dumps(producer_contract), encoding="utf-8")
    return files


def _producer_components(files: dict[str, Path]) -> dict[str, Path]:
    return {
        key: files[f"component_{key}"]
        for key in (
            "adapter",
            "event_inputs",
            "input_builder",
            "host_commit_probe",
            "host_commit_simulation",
            "measured_dry_run",
            "gradient_lineage",
            "model_lineage",
            "momentum_lineage",
            "muon",
            "rung2_runtime",
            "writer",
        )
    }


def test_dispatch_plan_refuses_historical_import_dependency(tmp_path: Path):
    module = _load()
    files = _files(tmp_path / "inputs")
    historical = tmp_path / "inputs" / "timeshare_pretrain.py"
    historical.write_text(
        "raise SystemExit('historical_only: every importer is execution-denied')\n",
        encoding="utf-8",
    )
    with pytest.raises(module.DispatchPlanRefusal, match="HISTORICAL_IMPORT_EXECUTION_DENIED"):
        module.build_dispatch_manifest(
            **_kwargs(tmp_path, files), source_dependencies=[files["producer"], historical]
        )


def test_dispatch_plan_builds_closed_governed_vertical_manifest(tmp_path: Path):
    module = _load()
    files = _files(tmp_path / "inputs")
    manifest = module.build_dispatch_manifest(
        **_kwargs(tmp_path, files), source_dependencies=[files["producer"]]
    )

    assert manifest["schema_version"] == "ember-lab-dispatch-manifest-v3"
    assert manifest["args"][0] == str(files["producer"].resolve())
    assert manifest["args"][1] == "governed-vertical"
    assert manifest["workload_profile"]["profile_id"] == "governed_vertical"
    assert manifest["workload_profile"]["cpu_rate_percent"] == 80
    assert [row["kind"] for row in manifest["workload_profile"]["pinned_host_producers"]] == [
        "training_data_loader", "checkpoint_writer", "telemetry_buffer"
    ]
    assert sum(row["maximum_bytes"] for row in manifest["workload_profile"]["pinned_host_producers"]) == manifest["simulated_peak_commit_bytes"]
    assert manifest["required_available_maximum_commit_bytes"] == manifest["maximum_job_memory_bytes"] + 10 * 1024**3
    assert set(manifest["env"]) == {
        "TEMP", "TMP", "TORCH_HOME", "TRITON_CACHE_DIR", "CUDA_CACHE_PATH", "HF_HOME", "XDG_CACHE_HOME"
    }
    assert {row["kind"] for row in manifest["bindings"]} == {"config", "manifest", "input", "verifier"}
    assert any(
        row["sha256"] == module._sha(files["host_commit_receipt"])
        for row in manifest["bindings"]
    )
    assert not any(row["sha256"] == module._sha(files["b3_receipt"]) for row in manifest["bindings"])
    assert not any(row["sha256"] == module._sha(files["gradient"]) for row in manifest["bindings"])
    assert any(row["sha256"] == module._sha(files["producer_contract"]) for row in manifest["bindings"])


def test_dispatch_plan_does_not_require_future_b3_outputs(tmp_path: Path):
    module = _load()
    files = _files(tmp_path / "inputs")
    files["b3_receipt"].unlink()
    files["gradient"].unlink()
    manifest = module.build_dispatch_manifest(
        **_kwargs(tmp_path, files), source_dependencies=[files["producer"]]
    )
    bound = {row["path"] for row in manifest["bindings"]}
    assert str(files["b3_receipt"].resolve()) not in bound
    assert str(files["gradient"].resolve()) not in bound


def test_dispatch_plan_refuses_tampered_host_commit_receipt(tmp_path: Path):
    module = _load()
    files = _files(tmp_path / "inputs")
    receipt = json.loads(files["host_commit_receipt"].read_text(encoding="utf-8"))
    receipt["simulated_peak_commit_bytes"] -= 1
    files["host_commit_receipt"].write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(module.DispatchPlanRefusal, match="DISPATCH_HOST_COMMIT_RECEIPT_TAMPERED"):
        module.build_dispatch_manifest(
            **_kwargs(tmp_path, files), source_dependencies=[files["producer"]]
        )


def _kwargs(tmp_path: Path, files: dict[str, Path]) -> dict[str, object]:
    custody = tmp_path / "custody"
    custody.mkdir()
    for name in ("temp", "tmp", "torch", "triton", "cuda", "hf", "xdg"):
        (custody / name).mkdir()
    gib = 1024**3
    return {
        "job_id": "q2-actual-update-001",
        "source_commit": "f3c92ba984711ee34e91c6bea90713e6c89b4b4d",
        "not_before_ms": 1_000,
        "expires_at_ms": 61_000,
        "program_path": files["program"],
        "producer_path": files["producer"],
        "custody_root": custody,
        "config_path": files["config"],
        "checkpoint_manifest_path": files["checkpoint"],
        "batch_manifest_path": files["batch"],
        "threshold_path": files["threshold"],
        "verifier_path": files["verifier"],
        "host_commit_receipt_path": files["host_commit_receipt"],
        "producer_contract_path": files["producer_contract"],
        "producer_component_paths": _producer_components(files),
        "minimum_free_vram_bytes": 21_746_679_808,
        "storage_root": tmp_path,
        "minimum_storage_free_bytes": 42_949_672_960,
        "simulated_peak_commit_bytes": 20 * gib,
        "maximum_job_memory_bytes": 20 * gib,
        "observed_available_maximum_commit_bytes": 40 * gib,
        "producer_budgets": {
            "training_data_loader": 5 * gib,
            "checkpoint_writer": 14 * gib,
            "telemetry_buffer": 1 * gib,
        },
    }
