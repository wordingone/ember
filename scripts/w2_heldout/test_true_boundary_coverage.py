# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import numpy as np


HERE = Path(__file__).resolve().parent
MODULE_PATH = HERE / "build_decontam_batch_mp.py"


class _InlinePool:
    def __init__(self, *, processes):
        self.processes = processes

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    @staticmethod
    def map(function, arguments):
        return [function(argument) for argument in arguments]


def _load_scanner_module(monkeypatch):
    stub = ModuleType("w1_collapse_control_run")
    stub.contamination_recheck = lambda *args, **kwargs: None
    stub.held_out_window_start = lambda *args, **kwargs: 0
    stub.assert_disjoint_from_training = lambda *args, **kwargs: {}
    stub.compute_n_windows_from_manifest = lambda *args, **kwargs: 0
    stub.CONTAMINATION_WINDOW_TOKENS = 13
    stub.CONTAMINATION_ROLL_BASE = 256
    monkeypatch.setitem(sys.modules, "w1_collapse_control_run", stub)
    monkeypatch.syspath_prepend(str(HERE))

    name = "build_decontam_batch_mp_issue331"
    spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "Pool", _InlinePool)
    return module


def test_mp_scanner_covers_true_boundary_between_worker_groups(
        tmp_path, monkeypatch):
    module = _load_scanner_module(monkeypatch)
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir()
    for shard_index in range(4):
        start = shard_index * 20
        np.arange(start, start + 20, dtype="<u2").tofile(
            shard_dir / f"shard-{shard_index:04d}.bin")

    boundary_window = list(range(35, 48))
    result = module.contamination_recheck_mp(
        [boundary_window],
        str(shard_dir),
        window=13,
        roll_base=256,
        n_workers=2,
        progress_file=str(tmp_path / "progress.jsonl"),
        chunk_tokens=64,
        dump_matches=str(tmp_path / "matches.jsonl"),
    )

    assert result["verdict"] == "CONTAMINATED"
    assert any(
        match.get("boundary") == "shard-0001.bin|shard-0002.bin"
        and match["window"] == boundary_window
        for match in result["confirmed_matches"]
    )
    assert result["true_shard_boundaries_scanned"] == 3
    assert result["boundary_window_convention"] == (
        "all true physical shard boundaries included exactly once; "
        "worker-group seams are scanned by the predecessor worker"
    )


def test_worker_partition_is_balanced_and_contiguous(monkeypatch):
    module = _load_scanner_module(monkeypatch)
    shards = [f"shard-{index:04d}.bin" for index in range(7)]
    assert module._contiguous_worker_shards(shards, 3) == [
        shards[0:3],
        shards[3:5],
        shards[5:7],
    ]


def test_mp_scanner_does_not_join_round_robin_fake_boundaries(
        tmp_path, monkeypatch):
    module = _load_scanner_module(monkeypatch)
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir()
    for shard_index in range(4):
        start = shard_index * 20
        np.arange(start, start + 20, dtype="<u2").tofile(
            shard_dir / f"shard-{shard_index:04d}.bin")

    fake_round_robin_window = list(range(8, 20)) + [40]
    result = module.contamination_recheck_mp(
        [fake_round_robin_window],
        str(shard_dir),
        window=13,
        roll_base=256,
        n_workers=2,
        progress_file=str(tmp_path / "progress.jsonl"),
        chunk_tokens=64,
        dump_matches=str(tmp_path / "matches.jsonl"),
    )

    assert result["verdict"] == "CLEAN"
    assert not any(
        match.get("boundary") == "shard-0000.bin|shard-0002.bin"
        for match in result["confirmed_matches"]
    )
