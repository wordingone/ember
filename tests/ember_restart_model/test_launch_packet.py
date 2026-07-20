# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Tests for the EMBER-01 cond7 launch-packet readiness runner.

Each implemented preflight gets a PASS case and a FAIL-CLOSED negative case.
No GPU, no training; pure config arithmetic + on-disk path checks.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[2] / "tools" / "ember-restart-3b" / "launch_packet.py"
_spec = importlib.util.spec_from_file_location("launch_packet", _MODULE_PATH)
lp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lp)

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "ember-restart-3b.json"


@pytest.fixture
def cfg() -> dict:
    return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def root() -> Path:
    return _CONFIG_PATH.resolve().parent.parent


# ---- no-sub-3B ------------------------------------------------------------

def test_no_sub_3b_pass_real_config(cfg, root):
    r = lp.preflight_no_sub_3b(cfg, root)
    assert r["status"] == "pass"
    assert r["computed_total_parameters"] >= 3_000_000_000
    # Independent recompute must match the contract's stated total exactly.
    assert r["matches_stated"] is True


def test_no_sub_3b_fail_closed_small_model(cfg, root):
    small = copy.deepcopy(cfg)
    small["model"]["hidden_size"] = 256   # collapses param count well below 3e9
    small["model"]["layers"] = 2
    r = lp.preflight_no_sub_3b(small, root)
    assert r["status"] == "fail"
    assert r["computed_total_parameters"] < 3_000_000_000


def test_no_sub_3b_fail_closed_missing_field(cfg, root):
    broken = copy.deepcopy(cfg)
    del broken["model"]["hidden_size"]
    r = lp.preflight_no_sub_3b(broken, root)
    assert r["status"] == "fail"
    assert "missing" in r["reason"].lower()


# ---- resource -------------------------------------------------------------

def test_resource_pass_real_config(cfg, root):
    r = lp.preflight_resource(cfg, root)
    assert r["status"] == "pass"
    assert r["peak_gpu_mem_gib"] <= 24.0


def test_resource_fail_closed_over_ceiling(cfg, root):
    huge = copy.deepcopy(cfg)
    # Inflate the runtime reserve past the 24 GiB ceiling; every term still present.
    huge["training"]["memory"]["runtime_reserve_gib"] = 64
    r = lp.preflight_resource(huge, root)
    assert r["status"] == "fail"
    assert r["peak_gpu_mem_gib"] > 24.0


def test_resource_fail_closed_missing_term(cfg, root):
    broken = copy.deepcopy(cfg)
    del broken["training"]["memory"]["parameter_bytes"]
    r = lp.preflight_resource(broken, root)
    assert r["status"] == "fail"
    assert "missing" in r["reason"].lower()


# ---- storage --------------------------------------------------------------

def test_storage_pass_real_config(cfg, root):
    r = lp.preflight_storage(cfg, root)
    assert r["status"] == "pass"
    assert r["free_disk_gib"] >= r["checkpoint_floor_gib"]
    assert all(p["exists"] for p in r["checked_paths"])


def test_storage_fail_closed_missing_corpus(cfg, root, tmp_path):
    # Point the runner at a repo root with NO data files -> declared paths absent.
    empty_root = tmp_path
    (empty_root / "configs").mkdir()
    r = lp.preflight_storage(cfg, empty_root)
    assert r["status"] == "fail"
    assert "missing" in r["reason"].lower()
    assert any(not p["exists"] for p in r["checked_paths"])


def test_storage_fail_closed_uncomputable_floor(cfg, root):
    broken = copy.deepcopy(cfg)
    del broken["checkpoints"]["serialization"]["model_parameter_bytes"]
    r = lp.preflight_storage(broken, root)
    assert r["status"] == "fail"


# ---- recovery ---------------------------------------------------------------
# Real save -> simulate-kill -> resume round trip on a tiny CPU shape,
# exercising the REAL checkpoint_artifacts + pretrain machinery (no GPU).

def test_recovery_pass_real_roundtrip(cfg, root):
    r = lp.preflight_recovery(cfg, root)
    assert r["status"] == "pass", r
    assert r["checkpoint_shards"] == 6
    assert r["data_cursor"]["global_step"] == 4


def test_recovery_fail_closed_broken_import(cfg, tmp_path):
    # A repo root with no tools/ember-restart-3b/ package and no configs/ --
    # the round-trip cannot run (module caching in-process may still resolve
    # the real trainer modules, but the real config file it must sha256 is
    # absent) -> fail closed, never a silent pass.
    empty_root = tmp_path
    r = lp.preflight_recovery(cfg, empty_root)
    assert r["status"] == "fail"
    assert r["reason"]


def test_recovery_fail_closed_tampered_checkpoint(cfg, root, monkeypatch):
    # Corrupt the checkpoint's replay state after write, before load, by
    # patching load_checkpoint_artifacts to simulate a shard hash mismatch --
    # the round-trip must fail closed, never silently accept divergent state.
    import importlib
    import sys as _sys
    tools_dir = str(root / "tools" / "ember-restart-3b")
    if tools_dir not in _sys.path:
        _sys.path.insert(0, tools_dir)
    checkpoint_artifacts = importlib.import_module("checkpoint_artifacts")

    def _tampering_load(*_args, **_kwargs):
        raise ValueError("checkpoint expert shard hash mismatch: tool")

    monkeypatch.setattr(checkpoint_artifacts, "load_checkpoint_artifacts", _tampering_load)
    r = lp.preflight_recovery(cfg, root)
    assert r["status"] == "fail"
    assert "round-trip raised" in r["reason"]


# ---- clean-genesis ----------------------------------------------------------

def test_clean_genesis_pass_real_config(cfg, root):
    r = lp.preflight_clean_genesis(cfg, root)
    assert r["status"] == "pass", r
    assert r["lineage"]["borrowed_weights"] is False
    assert "identical state_dict" in r["dynamic_proof"]


def test_clean_genesis_fail_closed_borrowed_weights(cfg, root):
    tainted = copy.deepcopy(cfg)
    tainted["lineage"]["borrowed_weights"] = True
    r = lp.preflight_clean_genesis(tainted, root)
    assert r["status"] == "fail"
    assert "borrowed_weights" in r["reason"]


def test_clean_genesis_fail_closed_non_random_init(cfg, root):
    tainted = copy.deepcopy(cfg)
    tainted["lineage"]["initialization"] = "checkpoint-restore"
    r = lp.preflight_clean_genesis(tainted, root)
    assert r["status"] == "fail"
    assert "initialization" in r["reason"]


def test_clean_genesis_fail_closed_parent_checkpoint_set(cfg, root):
    tainted = copy.deepcopy(cfg)
    tainted["lineage"]["parent_checkpoint"] = "receipts/ember-restart-3b/some-prior-run"
    r = lp.preflight_clean_genesis(tainted, root)
    assert r["status"] == "fail"
    assert "parent_checkpoint" in r["reason"]


def test_clean_genesis_fail_closed_missing_lineage(cfg, root):
    broken = copy.deepcopy(cfg)
    del broken["lineage"]
    r = lp.preflight_clean_genesis(broken, root)
    assert r["status"] == "fail"
    assert "missing" in r["reason"].lower()


def test_clean_genesis_fail_closed_borrowed_loading_in_source(cfg, root, tmp_path, monkeypatch):
    # A model.py whose UnifiedDecoder body references a borrowed-weight load
    # call must fail closed even if the config lineage block is clean.
    fake_root = tmp_path
    fake_tools = fake_root / "tools" / "ember-restart-3b"
    fake_tools.mkdir(parents=True)
    (fake_tools / "model.py").write_text(
        "class UnifiedDecoder:\n    def __init__(self):\n        self.load_state_dict({})\n",
        encoding="utf-8",
    )
    r = lp.preflight_clean_genesis(cfg, fake_root)
    assert r["status"] == "fail"
    assert "load_state_dict" in r["reason"]


# ---- overall exit ------------------------------------------------------------

def test_all_five_implemented_no_deferred(cfg, root):
    assert lp.DEFERRED == []
    assert len(lp.IMPLEMENTED) == 5


def test_run_exits_zero_when_all_five_pass(root):
    # Real config: all 5 preflights (storage, resource, no-sub-3B, recovery,
    # clean-genesis) are implemented and pass -> packet exits 0 and prints
    # the real EMBER-02 command.
    rc = lp.run(_CONFIG_PATH)
    assert rc == 0


def test_named_command_is_truthful_no_placeholder(cfg):
    cmd = lp.named_launch_command(cfg)
    assert "run_vertical_slice.py" in cmd["command"]
    assert "semantic" in cmd["command"]
    assert "run_semantic" in cmd["library_entrypoint"]
    # The historical sub-3B trainer is EXECUTION-DENIED (historical_only);
    # the named command must never point at it, and the note must say why.
    assert "timeshare_pretrain.py" not in cmd["command"]
    assert "historical_only" in cmd["note"]
