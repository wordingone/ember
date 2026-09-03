# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Issue #1464 residual: `energy_proxy_logger.py` must persist the raw
measured-window GPU samples it already collects in memory, so a downstream
per-step energy derivation (`tools/ember-restart-3b/a1_energy_apportionment.py`)
has real, timestamped draw readings to apportion across training steps
instead of only the whole-run aggregate `energy` block.

Exercises `sample_while_pidfile` and `samples_path_for` directly -- the pure,
already-testable surface -- rather than the full `run_watch` idle-baseline +
watch loop, which needs a live GPU reader chain and is covered end-to-end by
the module's own `--selftest`/`--smoke` CLI modes on a real host.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())


def load_module():
    path = ROOT / "scripts" / "energy_proxy_logger.py"
    spec = importlib.util.spec_from_file_location("energy_proxy_logger_samples_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_samples_path_for_is_a_stem_based_sibling(tmp_path: Path) -> None:
    module = load_module()
    receipt = tmp_path / "energy-proxy-receipt.json"
    assert module.samples_path_for(receipt) == tmp_path / "energy-proxy-receipt.gpu-samples.jsonl"
    assert module.samples_path_for(str(receipt)) == tmp_path / "energy-proxy-receipt.gpu-samples.jsonl"


def test_sample_while_pidfile_persists_every_captured_reading(tmp_path: Path, monkeypatch) -> None:
    """The samples file must carry exactly the readings `sample_while_pidfile`
    returns in memory -- same count, same (ts, watts) pairs -- so a consumer
    reopening the file gets the identical real record, not a lossy or
    re-derived one."""
    module = load_module()
    pidfile = tmp_path / "sidecar.pid"
    pidfile.write_text(str(os.getpid()), encoding="utf-8")

    readings = iter([100.0, 150.0, 200.0])

    def fake_read_gpu_watts(reader: str):
        try:
            return next(readings)
        except StopIteration:
            # Close the window on the 4th tick, same as a launcher deleting
            # the pidfile once its measured window ends.
            pidfile.unlink(missing_ok=True)
            return None

    monkeypatch.setattr(module, "_read_gpu_watts", fake_read_gpu_watts)

    samples_path = tmp_path / "energy-proxy-receipt.gpu-samples.jsonl"
    with open(samples_path, "w", encoding="utf-8", newline="\n") as handle:
        in_memory, intended, wall, stop_reason = module.sample_while_pidfile(
            "fake", pidfile, sample_hz=1000.0, samples_handle=handle,
        )

    assert len(in_memory) == 3
    persisted_lines = samples_path.read_text(encoding="utf-8").splitlines()
    assert len(persisted_lines) == 3
    for (ts, watts), line in zip(in_memory, persisted_lines):
        row = json.loads(line)
        assert set(row) == {"ts", "watts"}
        assert row["ts"] == ts
        assert row["watts"] == watts
    assert [json.loads(l)["watts"] for l in persisted_lines] == [100.0, 150.0, 200.0]


def test_sample_while_pidfile_with_no_handle_persists_nothing(tmp_path: Path, monkeypatch) -> None:
    """`samples_handle=None` (the pre-#1464 call shape, still used by
    `run_smoke`) must behave exactly as before -- no file, no side effect."""
    module = load_module()
    pidfile = tmp_path / "sidecar.pid"
    pidfile.write_text(str(os.getpid()), encoding="utf-8")

    calls = {"n": 0}

    def fake_read_gpu_watts(reader: str):
        calls["n"] += 1
        if calls["n"] >= 2:
            pidfile.unlink(missing_ok=True)
            return None
        return 42.0

    monkeypatch.setattr(module, "_read_gpu_watts", fake_read_gpu_watts)
    in_memory, intended, wall, stop_reason = module.sample_while_pidfile(
        "fake", pidfile, sample_hz=1000.0,
    )
    assert len(in_memory) == 1
    assert list(tmp_path.iterdir()) == []
