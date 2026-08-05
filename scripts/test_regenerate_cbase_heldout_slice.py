# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("regenerate_cbase_heldout_slice.py")


def load_module():
    spec = importlib.util.spec_from_file_location("regenerate_cbase_heldout_slice", SCRIPT)
    assert SCRIPT.is_file() and spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_does_not_import_execution_denied_historical_trainer():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "from timeshare_pretrain" not in source
    assert "from w1_collapse_control_run" not in source
    assert "import timeshare_pretrain" not in source
    assert "import w1_collapse_control_run" not in source


def test_cumulative_shard_offsets_matches_sum_and_order():
    m = load_module()
    receipt = {"shards": [{"name": "a", "n_tokens": 10}, {"name": "b", "n_tokens": 20},
                          {"name": "c", "n_tokens": 5}]}
    offsets, total = m.cumulative_shard_offsets(receipt)
    assert offsets == {"a": (0, 10), "b": (10, 30), "c": (30, 35)}
    assert total == 35


def test_pick_clean_shard_skips_tainted_and_prefers_earliest_clean_after_exclusion():
    m = load_module()
    # shards of 100 tokens each; excluded range covers all of shard "b" and
    # part of "c" -- "d" is the first WHOLLY clean shard at/after the
    # exclusion end, "a" is clean but before it (must not be picked: the
    # picker explicitly restricts to shards starting at/after exclusion_end).
    receipt = {"total_stream_tokens": 400,
              "shards": [{"name": "a", "n_tokens": 100}, {"name": "b", "n_tokens": 100},
                        {"name": "c", "n_tokens": 100}, {"name": "d", "n_tokens": 100}]}
    excluded = [(100, 250)]   # covers all of b [100,200) and half of c [200,300)
    name, start, end = m.pick_clean_shard(receipt, excluded)
    assert (name, start, end) == ("d", 300, 400)


def test_pick_clean_shard_refuses_when_none_wholly_clean():
    m = load_module()
    receipt = {"total_stream_tokens": 200,
              "shards": [{"name": "a", "n_tokens": 100}, {"name": "b", "n_tokens": 100}]}
    with pytest.raises(SystemExit, match="REGEN_REFUSED"):
        m.pick_clean_shard(receipt, [(0, 200)])


def test_pick_clean_shard_refuses_on_shard_sum_mismatch():
    m = load_module()
    receipt = {"total_stream_tokens": 999,
              "shards": [{"name": "a", "n_tokens": 100}]}
    with pytest.raises(SystemExit, match="REGEN_REFUSED"):
        m.pick_clean_shard(receipt, [])


def test_select_windows_even_stride_deterministic_and_ceiling_respected():
    m = load_module()
    # seq=4, n_mtp=0 -> block_len=5; shard of 45 tokens -> (45-5)//4+1 = 11
    # candidate windows; asking for 4 forces stride=2 (11//4).
    windows = m.select_windows("s.bin", shard_start=1000, shard_len=45, seq=4, n_mtp=0,
                               count=4, training_ceiling_token=0)
    assert len(windows) == 4
    starts = [w["global_token_start"] for w in windows]
    assert starts == sorted(starts) and len(set(starts)) == 4   # strictly increasing, no repeats
    for w in windows:
        assert w["global_token_end_exclusive"] - w["global_token_start"] == 5      # seq+1
        assert w["source_global_token_end_exclusive"] - w["global_token_start"] == 5  # n_mtp=0
        assert w["window_index"] == w["global_token_start"] // 4
        assert w["shard_name"] == "s.bin"
    # same inputs -> same output (reproducible, not randomized)
    again = m.select_windows("s.bin", shard_start=1000, shard_len=45, seq=4, n_mtp=0,
                             count=4, training_ceiling_token=0)
    assert windows == again


def test_select_windows_refuses_below_training_ceiling():
    m = load_module()
    with pytest.raises(SystemExit, match="REGEN_REFUSED"):
        m.select_windows("s.bin", shard_start=0, shard_len=45, seq=4, n_mtp=0,
                         count=2, training_ceiling_token=10**9)


def test_select_windows_refuses_when_shard_too_small():
    m = load_module()
    with pytest.raises(SystemExit, match="REGEN_REFUSED"):
        m.select_windows("s.bin", shard_start=0, shard_len=45, seq=4, n_mtp=0,
                         count=100, training_ceiling_token=0)
