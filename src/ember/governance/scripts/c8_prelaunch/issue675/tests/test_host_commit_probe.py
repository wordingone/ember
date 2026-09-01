# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "q2_host_commit_probe.py"
VALIDATOR_PATH = ROOT / "q2_host_commit_simulation.py"


def _load(path: Path, name: str):
    assert path.exists(), f"{path.name} is not implemented"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bindings() -> dict[str, str]:
    return {
        "measurement_tool_sha256": "a" * 64,
        "config_sha256": "b" * 64,
        "checkpoint_manifest_sha256": "c" * 64,
        "batch_manifest_sha256": "d" * 64,
        "producer_sha256": "e" * 64,
    }


def test_probe_emits_validator_accepted_os_high_water_trace(tmp_path: Path):
    module = _load(MODULE_PATH, "q2_host_commit_probe")
    validator = _load(VALIDATOR_PATH, "q2_host_commit_simulation_probe_test")
    values = iter(range(100, 320, 20))
    clock = iter(range(1_000, 2_000, 10))
    probe = module.HostCommitProbe(
        job_id="q2-actual-update-001",
        source_commit="f3c92ba984711ee34e91c6bea90713e6c89b4b4d",
        bindings=_bindings(),
        peak_commit_sampler=lambda: next(values),
        clock_ms=lambda: next(clock),
        pid=4312,
    )
    for name, _producer in module.PHASES:
        probe.begin_phase(name)
        probe.sample()
        probe.end_phase()
    trace = probe.finish(exit_code=0)
    path = tmp_path / "trace.json"
    module.write_trace_atomic(path, trace)

    receipt = validator.validate_host_commit_measurement(path)
    assert receipt["simulated_peak_commit_bytes"] == 200
    assert [row["sample_count"] for row in receipt["phases"]] == [2] * 5
    assert all(row["measurement_source"] == "os_commit_probe" for row in receipt["phases"])


def test_probe_refuses_phase_reorder_or_non_growth():
    module = _load(MODULE_PATH, "q2_host_commit_probe_refusal")
    probe = module.HostCommitProbe(
        job_id="q2-actual-update-001",
        source_commit="f3c92ba984711ee34e91c6bea90713e6c89b4b4d",
        bindings=_bindings(),
        peak_commit_sampler=lambda: 100,
        clock_ms=lambda: 1_000,
        pid=4312,
    )
    with pytest.raises(module.HostCommitProbeRefusal, match="HOST_COMMIT_PHASE_ORDER_INVALID"):
        probe.begin_phase("optimizer_momentum")

    probe.begin_phase("model_reconstruction")
    probe.sample()
    with pytest.raises(module.HostCommitProbeRefusal, match="HOST_COMMIT_PHASE_NO_GROWTH"):
        probe.end_phase()


def test_probe_refuses_incomplete_or_failed_run():
    module = _load(MODULE_PATH, "q2_host_commit_probe_incomplete")
    values = iter([100, 120, 140])
    clock = iter([1_000, 1_010, 1_020, 1_030])
    probe = module.HostCommitProbe(
        job_id="q2-actual-update-001",
        source_commit="f3c92ba984711ee34e91c6bea90713e6c89b4b4d",
        bindings=_bindings(),
        peak_commit_sampler=lambda: next(values),
        clock_ms=lambda: next(clock),
        pid=4312,
    )
    probe.begin_phase("model_reconstruction")
    probe.sample()
    probe.end_phase()
    with pytest.raises(module.HostCommitProbeRefusal, match="HOST_COMMIT_PHASE_SET_INVALID"):
        probe.finish(exit_code=0)


@pytest.mark.skipif(os.name != "nt", reason="Windows commit probe")
def test_live_windows_commit_sampler_returns_os_high_water():
    module = _load(MODULE_PATH, "q2_host_commit_probe_live")
    assert module.windows_peak_commit_bytes() > 0
