# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Production-shaped issue-1505 producer tests."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load_module():
    path = ROOT / "scripts" / "forecast_recalibration.py"
    spec = importlib.util.spec_from_file_location("forecast_recalibration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_fixture(tmp_path: Path, *, run_ids: tuple[str, ...]) -> tuple[object, Path, Path]:
    module = load_module()
    repo = tmp_path / "repo"
    forecast = repo / "docs" / "spec" / "ember02-r1-forecast-v1.json"
    forecast.parent.mkdir(parents=True)
    forecast.write_text(
        json.dumps(
            {
                "schema_version": "ember02-r1-forecast/v1",
                "quantities": {
                    "step_time_ms": {"predicted": 10.0},
                    "tokens_per_second": {"predicted": 100.0},
                    "proxy_joules_per_token": {"predicted": 1.0},
                    "peak_vram_gib": {"predicted": 1.0},
                    "loss_trajectory": {"predicted_anchors": {"step_1": 1.0}},
                },
            }
        ),
        encoding="utf-8",
    )
    run_root = repo / "run"
    telemetry = run_root / "telemetry" / "train.jsonl"
    telemetry.parent.mkdir(parents=True)
    rows = []
    for run_id in run_ids:
        for step in (1, 2):
            rows.append(
                {
                    "ts": f"2026-08-09T00:00:0{step}Z",
                    "kind": "train_step",
                    "source": "ember-restart-3b",
                    "payload": {
                        "run_id": run_id,
                        "step": step,
                        "step_ms": 10.0,
                        "tokens_consumed": 1.0,
                        "loss": 1.0,
                        "total_gib": 2.0,
                        "free_gib": 1.0,
                    },
                }
            )
    telemetry.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    energy = run_root / "energy-proxy-receipt.json"
    energy.parent.mkdir(parents=True, exist_ok=True)
    energy.write_text(json.dumps({"total_proxy_joules": 4.0, "energy_boundary": "CPU"}), encoding="utf-8")
    manifest = run_root / "checkpoint-manifest.json"
    manifest.write_text(json.dumps({"data_cursor": {"tokens_seen": 2, "global_step": 2}}), encoding="utf-8")
    (run_root / "run-child.log").write_text(json.dumps({"peak_memory_bytes": 1024**3}) + "\n", encoding="utf-8")
    module.REPO_ROOT = repo
    module.load_t01 = lambda: 2
    return module, forecast, run_root


def test_producer_selects_one_run_and_emits_run_id(tmp_path: Path) -> None:
    module, forecast, run_root = write_fixture(tmp_path, run_ids=("run-a",))

    receipt = module.build_receipt(forecast, run_root)

    assert receipt["run_id"] == "run-a"
    assert receipt["steps_measured"] == 2
    assert receipt["telemetry_sha256"] == module.telemetry_sha256(run_root)


def test_producer_binds_every_telemetry_file_and_rejects_mutation(tmp_path: Path) -> None:
    module, forecast, run_root = write_fixture(tmp_path, run_ids=("run-a",))
    second = run_root / "telemetry" / "other.jsonl"
    second.write_text("{\"source\":\"unrelated\"}\n", encoding="utf-8")

    receipt = module.build_receipt(forecast, run_root)
    assert receipt["telemetry_sha256"] == module.telemetry_sha256(run_root)

    tracked = run_root / "telemetry" / "train.jsonl"
    tracked.write_text(tracked.read_text(encoding="utf-8").replace("\"step\": 2", "\"step\": 99", 1), encoding="utf-8")
    with pytest.raises(module.RecalibrationRefusal, match="TELEMETRY"):
        module.validate_telemetry_binding(receipt, run_root)


def test_e6_hash_domain_matches_consumer_and_rejects_unreadable_drift(tmp_path: Path) -> None:
    module, forecast, run_root = write_fixture(tmp_path, run_ids=("run-a",))
    unrelated = run_root / "telemetry" / "unrelated.jsonl"
    unrelated.write_text('{"source":"other"}\n', encoding="utf-8")
    receipt = module.build_receipt(forecast, run_root)
    assert module.telemetry_paths(run_root) == [run_root / "telemetry" / "train.jsonl"]
    assert receipt["telemetry_sha256"] == module.telemetry_sha256(run_root)
    unrelated.write_text("{not-json}\n", encoding="utf-8")
    assert module.telemetry_sha256(run_root) == receipt["telemetry_sha256"]
    tracked = run_root / "telemetry" / "train.jsonl"
    tracked.write_bytes(b"\xff")
    with pytest.raises(module.RecalibrationRefusal, match="TELEMETRY_UNREADABLE"):
        module.telemetry_paths(run_root)


def test_e6_hash_domain_excludes_oversized_governed_rows_on_both_sides(tmp_path: Path) -> None:
    module, forecast, run_root = write_fixture(tmp_path, run_ids=("run-a",))
    oversized = run_root / "telemetry" / "oversized.jsonl"
    oversized.write_text(
        json.dumps({"source": "ember-restart-3b", "padding": "x" * 4096}) + "\n",
        encoding="utf-8",
    )
    receipt = module.build_receipt(forecast, run_root)
    assert oversized not in module.telemetry_paths(run_root)

    battery_path = ROOT / "scripts" / "r1_exit_battery.py"
    spec = importlib.util.spec_from_file_location("r1_exit_battery", battery_path)
    assert spec is not None and spec.loader is not None
    battery = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(battery)
    assert oversized not in battery.find_telemetry_files(run_root)
    assert receipt["telemetry_sha256"] == battery._telemetry_sha256(run_root)


def test_validator_rejects_missing_or_foreign_telemetry_binding(tmp_path: Path) -> None:
    module, forecast, run_root = write_fixture(tmp_path, run_ids=("run-a",))
    receipt = module.build_receipt(forecast, run_root)
    missing = dict(receipt)
    missing.pop("telemetry_sha256")
    with pytest.raises(module.RecalibrationRefusal, match="TELEMETRY_SHA256"):
        module.validate_telemetry_binding(missing, run_root)

    foreign = dict(receipt)
    foreign["telemetry_sha256"] = "f" * 64
    with pytest.raises(module.RecalibrationRefusal, match="TELEMETRY_SHA256"):
        module.validate_telemetry_binding(foreign, run_root)


def test_e6_consumer_rejects_receipt_without_telemetry_binding(tmp_path: Path) -> None:
    module, forecast, run_root = write_fixture(tmp_path, run_ids=("run-a",))
    receipt = module.build_receipt(forecast, run_root)
    receipt.pop("telemetry_sha256")
    candidate = run_root / "forecast-recalibration.json"
    candidate.write_text(json.dumps(receipt), encoding="utf-8")
    battery_path = ROOT / "scripts" / "r1_exit_battery.py"
    spec = importlib.util.spec_from_file_location("r1_exit_battery", battery_path)
    assert spec is not None and spec.loader is not None
    battery = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(battery)
    thresholds = {"T-01": 2}
    result = battery.check_r1_e6(run_root, thresholds, repo_root=run_root.parent)
    assert result["status"] != "MET"
    assert any("telemetry_sha256" in defect for row in result["components"]["candidate_validation"] for defect in row["defects"])


def test_e6_consumer_hash_domain_rejects_tracked_unreadable_drift(tmp_path: Path) -> None:
    module, forecast, run_root = write_fixture(tmp_path, run_ids=("run-a",))
    unrelated = run_root / "telemetry" / "unrelated.jsonl"
    unrelated.write_text('{"source":"other"}\n', encoding="utf-8")
    receipt = module.build_receipt(forecast, run_root)
    candidate = run_root / "forecast-recalibration.json"
    candidate.write_text(json.dumps(receipt), encoding="utf-8")
    battery_path = ROOT / "scripts" / "r1_exit_battery.py"
    spec = importlib.util.spec_from_file_location("r1_exit_battery", battery_path)
    assert spec is not None and spec.loader is not None
    battery = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(battery)
    thresholds = {"T-01": 2}

    unrelated.write_text('{"source":"foreign"}\n', encoding="utf-8")
    result = battery.check_r1_e6(run_root, thresholds, repo_root=run_root.parent)
    assert not any("telemetry_sha256" in defect for row in result["components"]["candidate_validation"] for defect in row["defects"])

    tracked = run_root / "telemetry" / "train.jsonl"
    tracked.write_bytes(b"\xff\xfe")
    result = battery.check_r1_e6(run_root, thresholds, repo_root=run_root.parent)
    defects = [defect for row in result["components"]["candidate_validation"] for defect in row["defects"]]
    assert any("TELEMETRY_UNREADABLE" in defect for defect in defects)


def test_producer_refuses_ambiguous_run_ids(tmp_path: Path) -> None:
    module, forecast, run_root = write_fixture(tmp_path, run_ids=("run-a", "run-b"))

    with pytest.raises(module.RecalibrationRefusal, match="AMBIGUOUS"):
        module.build_receipt(forecast, run_root)
