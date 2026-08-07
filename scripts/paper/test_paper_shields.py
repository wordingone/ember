from __future__ import annotations
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paper_shields import run_shields


def test_components_a_b_c_bind_explicit_inputs_and_hide_paths(tmp_path):
    eval_path = tmp_path / "eval.json"
    shard = tmp_path / "shard.txt"
    config = tmp_path / "config.json"
    run = tmp_path / "run.json"
    out = tmp_path / "receipt.json"
    planted = "one two three four five six seven eight nine ten eleven twelve thirteen"
    eval_path.write_text(json.dumps([{"item_id": "p", "text": planted},
                                     {"item_id": "n", "text": "unrelated clean control"}]), encoding="utf-8")
    shard.write_text(planted, encoding="utf-8")
    config.write_text(json.dumps({"shards": [str(shard), str(tmp_path / "missing.txt")]}), encoding="utf-8")
    run.write_text(json.dumps({"ticket": "RUN", "ts": "20260601T000000Z", "steps": 2,
                               "tokens_this_segment": 20, "wall_s": 4}), encoding="utf-8")
    result = run_shields(str(eval_path), [str(shard)], [str(config)], [str(run)], str(out),
                         timestamp="20260807T000000Z")
    assert result["component_a_contamination"]["suite_summary"]["n_contaminated"] >= 1
    assert result["component_b_provenance"]["summary"]["n_shards"] >= 2
    assert result["component_c_compute_ledger"][0]["status"] == "BACKFILLED"
    assert result["component_d_status"] == "COORDINATOR_GATED_NOT_IMPLEMENTED"
    text = out.read_text(encoding="utf-8")
    assert str(tmp_path) not in text and "\\" not in text


def test_missing_required_inputs_refuse_before_publish(tmp_path):
    out = tmp_path / "receipt.json"
    try:
        run_shields(str(tmp_path / "missing-eval.json"), [], [], [], str(out), timestamp="20260807T000000Z")
    except (FileNotFoundError, ValueError):
        pass
    else:
        raise AssertionError("missing input must fail closed")
    assert not out.exists()
