# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import ast
import os
from pathlib import Path


SOURCE = (
    Path(__file__).resolve().parents[2]
    / "src" / "ember" / "governance" / "scripts" / "w1_collapse_control_run.py"
)


def _load_classifier():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef)
        and item.name == "classify_contamination_self_matches"
    )
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    namespace = {
        "CONTAMINATION_WINDOW_TOKENS": 13,
        "os": os,
    }
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace["classify_contamination_self_matches"]


def test_boundary_straddling_match_is_not_classified_as_self(tmp_path):
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir()
    (shard_dir / "shard-0000.bin").write_bytes(b"\x00\x00" * 256)

    seq = 16
    n_mtp = 2
    candidate_idx = 5
    candidate_end = candidate_idx * seq + seq + 1 + n_mtp
    contamination = {
        "confirmed_matches": [
            {
                "shard": "shard-0000.bin",
                "offset": candidate_end - 1,
                "window": list(range(13)),
            }
        ]
    }

    classified = _load_classifier()(
        contamination, [candidate_idx],
        seq=seq, n_mtp=n_mtp, shard_dir=str(shard_dir))
    assert classified["verdict"] == "CONTAMINATED"
    assert classified["self_matches_excluded"] == 0
    assert classified["confirmed_non_self_matches"] == contamination["confirmed_matches"]


def test_fully_contained_match_remains_classified_as_self(tmp_path):
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir()
    (shard_dir / "shard-0000.bin").write_bytes(b"\x00\x00" * 256)

    seq = 16
    n_mtp = 2
    candidate_idx = 5
    candidate_end = candidate_idx * seq + seq + 1 + n_mtp
    contamination = {
        "confirmed_matches": [
            {
                "shard": "shard-0000.bin",
                "offset": candidate_end - 13,
                "window": list(range(13)),
            }
        ]
    }

    classified = _load_classifier()(
        contamination, [candidate_idx],
        seq=seq, n_mtp=n_mtp, shard_dir=str(shard_dir))
    assert classified["verdict"] == "CLEAN"
    assert classified["self_matches_excluded"] == 1
    assert classified["confirmed_non_self_matches"] == []
