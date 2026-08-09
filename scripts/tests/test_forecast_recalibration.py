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


def test_producer_refuses_ambiguous_run_ids(tmp_path: Path) -> None:
    module, forecast, run_root = write_fixture(tmp_path, run_ids=("run-a", "run-b"))

    with pytest.raises(module.RecalibrationRefusal, match="AMBIGUOUS"):
        module.build_receipt(forecast, run_root)
