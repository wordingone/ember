# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Production-shaped issue-1505 producer tests."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load_module():
    path = ROOT / "src" / "ember" / "governance" / "scripts" / "forecast_recalibration.py"
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
    # Real shape: scripts/energy_proxy_logger.py (schema ember-energy-proxy-run-v1)
    # always nests these fields under "energy" -- so does the E5 battery leg's read.
    energy.write_text(
        json.dumps({"energy": {"total_proxy_joules": 4.0, "energy_boundary": "CPU"}}),
        encoding="utf-8",
    )
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

    battery_path = ROOT / "src" / "ember" / "governance" / "scripts" / "r1_exit_battery.py"
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
    battery_path = ROOT / "src" / "ember" / "governance" / "scripts" / "r1_exit_battery.py"
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
    battery_path = ROOT / "src" / "ember" / "governance" / "scripts" / "r1_exit_battery.py"
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


def test_energy_leg_binds_nested_energy_block_and_refuses_flat_receipt(tmp_path: Path) -> None:
    module, forecast, run_root = write_fixture(tmp_path, run_ids=("run-a",))
    receipt = module.build_receipt(forecast, run_root)
    q = receipt["quantities"]["proxy_joules_per_token"]
    assert q["measurement"]["total_proxy_joules"] == 4.0
    assert q["measurement"]["energy_boundary"] == "CPU"

    # The real producer never writes a flat top-level shape; a receipt that
    # does must be refused, not silently read as zero-signal.
    (run_root / "energy-proxy-receipt.json").write_text(
        json.dumps({"total_proxy_joules": 4.0, "energy_boundary": "CPU"}), encoding="utf-8"
    )
    with pytest.raises(module.RecalibrationRefusal, match="proxy_joules_per_token"):
        module.build_receipt(forecast, run_root)


def test_peak_vram_prefers_e4_measurement_receipt_over_telemetry(tmp_path: Path) -> None:
    module, forecast, run_root = write_fixture(tmp_path, run_ids=("run-a",))
    (run_root / "run-child.log").unlink()
    (run_root / "e4-measurement-receipt.json").write_text(
        json.dumps(
            {
                "schema_version": "ember02-r1-e4-measurement/v1",
                "run_id": "run-a",
                "peak_vram": {"allocated_bytes": 3 * 1024 ** 3, "reserved_bytes": 4 * 1024 ** 3},
            }
        ),
        encoding="utf-8",
    )

    receipt = module.build_receipt(forecast, run_root)

    q = receipt["quantities"]["peak_vram_gib"]
    # Telemetry total_gib/free_gib in the fixture would measure 1.0 GiB; the
    # e4 receipt's allocator peak (3.0 GiB) must win, proving the source order.
    assert q["measured"] == pytest.approx(3.0)
    assert "e4-measurement-receipt.json" in q["measurement"]["source"]
    assert "allocated_bytes" in q["measurement"]["source"]


def test_peak_vram_refuses_non_finite_e4_allocated_bytes(tmp_path: Path) -> None:
    module, forecast, run_root = write_fixture(tmp_path, run_ids=("run-a",))
    (run_root / "run-child.log").unlink()
    (run_root / "e4-measurement-receipt.json").write_text(
        json.dumps(
            {
                "schema_version": "ember02-r1-e4-measurement/v1",
                "run_id": "run-a",
                "peak_vram": {"allocated_bytes": float("nan"), "reserved_bytes": 4 * 1024 ** 3},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(module.RecalibrationRefusal, match="peak_vram_gib"):
        module.build_receipt(forecast, run_root)


def test_r2_receipt_binds_rung_to_its_canonical_forecast(tmp_path: Path) -> None:
    module, r1_forecast, run_root = write_fixture(tmp_path, run_ids=("run-a",))
    r2_forecast = r1_forecast.with_name("ember02-r2-forecast-v1.json")
    r2_forecast.write_bytes(r1_forecast.read_bytes())

    receipt = module.build_receipt(r2_forecast, run_root, rung="R2")

    assert receipt["rung"] == "R2"
    assert receipt["forecast_path"] == "docs/spec/ember02-r2-forecast-v1.json"


@pytest.mark.parametrize(
    ("rung", "forecast_name", "reason"),
    [
        ("R3", "ember02-r2-forecast-v1.json", "UNKNOWN_RUNG"),
        ("R2", "ember02-r1-forecast-v1.json", "FORECAST_NOT_PREREGISTERED"),
        ("R1", "ember02-r2-forecast-v1.json", "FORECAST_NOT_PREREGISTERED"),
    ],
)
def test_producer_refuses_unknown_or_cross_rung_forecast(
    tmp_path: Path, rung: str, forecast_name: str, reason: str
) -> None:
    module, r1_forecast, run_root = write_fixture(tmp_path, run_ids=("run-a",))
    forecast = r1_forecast.with_name(forecast_name)
    if forecast != r1_forecast:
        forecast.write_bytes(r1_forecast.read_bytes())

    with pytest.raises(module.RecalibrationRefusal, match=reason):
        module.build_receipt(forecast, run_root, rung=rung)


def test_consumer_refuses_foreign_rung_and_path_tamper(tmp_path: Path) -> None:
    module, r1_forecast, run_root = write_fixture(tmp_path, run_ids=("run-a",))
    r2_forecast = r1_forecast.with_name("ember02-r2-forecast-v1.json")
    r2_forecast.write_bytes(r1_forecast.read_bytes())
    receipt = module.build_receipt(r2_forecast, run_root, rung="R2")
    candidate = run_root / "forecast-recalibration.json"
    battery = load_battery()

    receipt["rung"] = "R1"
    candidate.write_text(json.dumps(receipt), encoding="utf-8")
    defects = battery._validate_recalibration_content(
        candidate, repo_root=run_root.parent, run_root=run_root, t01=2, rung="R2"
    )
    assert any("rung" in defect for defect in defects)

    receipt["rung"] = "R2"
    receipt["forecast_path"] = "docs/domains/governance/spec/ember02-r1-forecast-v1.json"
    candidate.write_text(json.dumps(receipt), encoding="utf-8")
    defects = battery._validate_recalibration_content(
        candidate, repo_root=run_root.parent, run_root=run_root, t01=2, rung="R2"
    )
    assert any("forecast_path" in defect for defect in defects)


def test_public_e6_path_adjudicates_r2_and_binds_selected_rung(tmp_path: Path) -> None:
    module, r1_forecast, run_root = write_fixture(tmp_path, run_ids=("run-a",))
    r2_forecast = r1_forecast.with_name("ember02-r2-forecast-v1.json")
    r2_forecast.write_bytes(r1_forecast.read_bytes())
    receipt = module.build_receipt(r2_forecast, run_root, rung="R2")
    (run_root / "forecast-recalibration.json").write_text(json.dumps(receipt), encoding="utf-8")
    battery = load_battery()

    result = battery.check_r1_e6(run_root, {"T-01": 2}, repo_root=run_root.parent, rung="R2")

    assert result["status"] == "MET"
    assert result["components"]["rung"] == "R2"


@pytest.mark.parametrize("rung", ["", "R3"])
def test_public_e6_path_refuses_absent_or_unknown_rung(tmp_path: Path, rung: str) -> None:
    _, _, run_root = write_fixture(tmp_path, run_ids=("run-a",))
    battery = load_battery()

    with pytest.raises(battery.R1ExitBatteryRefusal, match="UNKNOWN_RUNG"):
        battery.check_r1_e6(run_root, {"T-01": 2}, repo_root=run_root.parent, rung=rung)


def test_public_e6_path_refuses_cross_rung_receipt(tmp_path: Path) -> None:
    module, r1_forecast, run_root = write_fixture(tmp_path, run_ids=("run-a",))
    receipt = module.build_receipt(r1_forecast, run_root, rung="R1")
    (run_root / "forecast-recalibration.json").write_text(json.dumps(receipt), encoding="utf-8")
    battery = load_battery()

    result = battery.check_r1_e6(run_root, {"T-01": 2}, repo_root=run_root.parent, rung="R2")

    assert result["status"] == "NOT_MET"
    assert any(
        "rung mismatch" in defect
        for row in result["components"]["candidate_validation"]
        for defect in row["defects"]
    )


def test_battery_cli_adjudicates_r2_receipt_and_records_rung(tmp_path: Path) -> None:
    module, r1_forecast, run_root = write_fixture(tmp_path, run_ids=("run-a",))
    r2_forecast = r1_forecast.with_name("ember02-r2-forecast-v1.json")
    r2_forecast.write_bytes(r1_forecast.read_bytes())
    receipt = module.build_receipt(r2_forecast, run_root, rung="R2")
    (run_root / "forecast-recalibration.json").write_text(json.dumps(receipt), encoding="utf-8")
    out_dir = tmp_path / "receipts"
    battery = load_battery()
    thresholds_path = battery.DEFAULT_THRESHOLDS_PATH
    telemetry = run_root / "telemetry" / "train.jsonl"
    template = json.loads(telemetry.read_text(encoding="utf-8").splitlines()[0])
    rows = []
    for step in range(1, 101):
        row = json.loads(json.dumps(template))
        row["payload"]["step"] = step
        rows.append(row)
    telemetry.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    receipt = module.build_receipt(r2_forecast, run_root, rung="R2")
    (run_root / "forecast-recalibration.json").write_text(json.dumps(receipt), encoding="utf-8")

    original_repo_root = battery.REPO_ROOT
    battery.REPO_ROOT = run_root.parent
    try:
        code = battery.main(
            [
                "--run-root", str(run_root), "--exit", "e6", "--rung", "R2",
                "--thresholds", str(thresholds_path), "--out-dir", str(out_dir),
            ]
        )
    finally:
        battery.REPO_ROOT = original_repo_root

    assert code == 0
    emitted = json.loads(next(out_dir.glob("r1-e6-*.json")).read_text(encoding="utf-8"))
    assert emitted["status"] == "MET"
    assert emitted["subject"]["rung"] == "R2"
    assert emitted["result"]["components"]["rung"] == "R2"


def test_cli_emits_selected_rung_and_canonical_path(tmp_path: Path) -> None:
    module, fixture_forecast, run_root = write_fixture(tmp_path, run_ids=("run-a",))
    telemetry = run_root / "telemetry" / "train.jsonl"
    template = json.loads(telemetry.read_text(encoding="utf-8").splitlines()[0])
    rows = []
    for step in range(1, 101):
        row = json.loads(json.dumps(template))
        row["ts"] = f"2026-08-09T00:{step // 60:02d}:{step % 60:02d}Z"
        row["payload"]["step"] = step
        rows.append(row)
    telemetry.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    r2_forecast = ROOT / "docs" / "spec" / "ember02-r2-forecast-v1.json"
    original = r2_forecast.read_bytes() if r2_forecast.exists() else None
    r2_forecast.parent.mkdir(parents=True, exist_ok=True)
    r2_forecast.write_bytes(fixture_forecast.read_bytes())
    out = run_root / "r2-forecast-recalibration.json"
    script_root = ROOT / "src" / "ember" / "governance" / "scripts"
    env = dict(__import__("os").environ, PYTHONPATH=str(script_root))
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(script_root / "forecast_recalibration.py"),
                "--forecast",
                str(r2_forecast),
                "--rung",
                "R2",
                "--run-root",
                str(run_root),
                "--out",
                str(out),
            ],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
    finally:
        if original is None:
            r2_forecast.unlink(missing_ok=True)
        else:
            r2_forecast.write_bytes(original)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert (receipt["rung"], receipt["forecast_path"]) == (
        "R2",
        "docs/spec/ember02-r2-forecast-v1.json",
    )


def load_battery():
    path = ROOT / "src" / "ember" / "governance" / "scripts" / "r1_exit_battery.py"
    spec = importlib.util.spec_from_file_location("r1_exit_battery_issue1613", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
