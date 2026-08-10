# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "q2_host_commit_simulation.py"


def _load():
    assert MODULE_PATH.exists(), "q2_host_commit_simulation.py is not implemented"
    spec = importlib.util.spec_from_file_location("q2_host_commit_simulation", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _trace() -> dict[str, object]:
    phases = [
        ("model_reconstruction", "checkpoint_writer", 10, 110),
        ("optimizer_momentum", "checkpoint_writer", 110, 310),
        ("frozen_batch", "training_data_loader", 310, 350),
        ("capture_staging", "checkpoint_writer", 350, 430),
        ("python_cuda_host_overhead", "telemetry_buffer", 430, 450),
    ]
    return {
        "schema_version": "q2-host-commit-measurement-v1",
        "job_id": "q2-actual-update-001",
        "measurement_mode": "bounded_dry_run",
        "source_commit": "f3c92ba984711ee34e91c6bea90713e6c89b4b4d",
        "process": {"pid": 4312, "started_at_ms": 1_000, "ended_at_ms": 2_000, "exit_code": 0},
        "bindings": {
            "measurement_tool_sha256": _sha("tool"),
            "config_sha256": _sha("config"),
            "checkpoint_manifest_sha256": _sha("checkpoint"),
            "batch_manifest_sha256": _sha("batch"),
            "producer_sha256": _sha("producer"),
        },
        "phases": [
            {
                "ordinal": index,
                "name": name,
                "producer_kind": producer,
                "baseline_commit_bytes": baseline,
                "peak_commit_bytes": peak,
                "sample_count": 2,
                "measurement_source": "os_commit_probe",
            }
            for index, (name, producer, baseline, peak) in enumerate(phases)
        ],
    }


def test_builds_exact_conservative_host_commit_receipt(tmp_path: Path):
    module = _load()
    trace = tmp_path / "trace.json"
    trace.write_text(json.dumps(_trace()), encoding="utf-8")

    receipt = module.validate_host_commit_measurement(trace)

    assert receipt["schema_version"] == "q2-host-commit-simulation-receipt-v1"
    assert receipt["simulated_peak_commit_bytes"] == 440
    assert receipt["maximum_job_memory_bytes"] == 440
    assert receipt["producer_budgets"] == {
        "training_data_loader": 40,
        "checkpoint_writer": 380,
        "telemetry_buffer": 20,
    }
    assert receipt["trace_sha256"] == module.sha256_file(trace)
    assert receipt["receipt_sha256"] == module.receipt_sha256(receipt)
    assert "path" not in json.dumps(receipt).lower()


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda row: row.update(measurement_mode="estimate"), "HOST_COMMIT_NOT_MEASURED"),
        (lambda row: row["phases"].pop(), "HOST_COMMIT_PHASE_SET_INVALID"),
        (lambda row: row["phases"][1].update(ordinal=0), "HOST_COMMIT_PHASE_ORDER_INVALID"),
        (lambda row: row["phases"][1].update(baseline_commit_bytes=109), "HOST_COMMIT_PHASE_OVERLAP_OR_GAP"),
        (lambda row: row["phases"][0].update(sample_count=1), "HOST_COMMIT_PHASE_UNDERSAMPLED"),
        (lambda row: row["phases"][0].update(measurement_source="estimated"), "HOST_COMMIT_PHASE_NOT_OS_MEASURED"),
        (lambda row: row["bindings"].pop("batch_manifest_sha256"), "HOST_COMMIT_BINDINGS_INVALID"),
        (lambda row: row["process"].update(exit_code=1), "HOST_COMMIT_DRY_RUN_FAILED"),
    ],
)
def test_refuses_non_measured_or_incomplete_trace(tmp_path: Path, mutate, code: str):
    module = _load()
    payload = _trace()
    mutate(payload)
    trace = tmp_path / "trace.json"
    trace.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(module.HostCommitRefusal, match=code):
        module.validate_host_commit_measurement(trace)
