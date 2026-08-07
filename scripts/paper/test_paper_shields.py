from __future__ import annotations
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paper_shields import run_shields
import contamination_scan
import compute_ledger
import provenance_manifest


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
                         timestamp="20260807T000000Z",
                         component_d_comment_url="https://github.com/wordingone/ember/issues/123#issuecomment-test",
                         component_d_comment_body_sha256="a" * 64)
    assert result["component_a_contamination"]["suite_summary"]["n_contaminated"] >= 1
    assert result["component_b_provenance"]["summary"]["n_shards"] >= 2
    assert result["component_c_compute_ledger"][0]["status"] == "HISTORICAL_BACKFILL_ONLY"
    assert result["component_c_status"] == "EXECUTION_DENIED_UNFULFILLED"
    assert result["component_d_status"] == "TRANSFERRED_TO_CANONICAL_CARRIER"
    assert result["component_c_production_hook"]["status"] == "EXECUTION_DENIED"
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


def test_collision_requires_contiguous_ordered_grams():
    positive = "a b c d e f g"
    assert contamination_scan._count_ngram_collisions(
        positive, positive, gram_size=3, window_len=3
    ) == 1
    separated_or_reordered = "a b c X b c d Y c d e"
    assert contamination_scan._count_ngram_collisions(
        positive, separated_or_reordered, gram_size=3, window_len=3
    ) == 0


def test_component_b_opens_config_manifest_shards_and_transform_links(tmp_path):
    shard = tmp_path / "toy-000.jsonl"
    shard.write_bytes(b'{"text":"toy"}\n')
    transform = tmp_path / "transform.json"
    transform.write_bytes(b'{"step":"normalize"}\n')
    shard_sha = __import__("hashlib").sha256(shard.read_bytes()).hexdigest()
    transform_sha = __import__("hashlib").sha256(transform.read_bytes()).hexdigest()
    manifest = tmp_path / "corpus-manifest.json"
    manifest.write_text(json.dumps({
        "shards": [{
            "file": shard.name,
            "bytes_on_disk": shard.stat().st_size,
            "sha256": shard_sha,
            "transform_links": [{"path": transform.name, "sha256": transform_sha}],
        }],
    }), encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "sources": {"toy": {"manifest_path": manifest.name}},
    }), encoding="utf-8")
    result = provenance_manifest.build_manifest(
        [str(config)], authority_roots=[tmp_path]
    )
    rows = [row for row in result["manifest"] if row.get("shard_path") == shard.name]
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "VERIFIED"
    assert row["sha256"] == shard_sha
    assert row["declared_sha256"] == shard_sha
    assert row["transform_links"][0]["sha256"] == transform_sha
    assert row["transform_links"][0]["status"] == "VERIFIED"


def test_component_d_requires_public_append_only_carrier_comment(tmp_path):
    eval_path = tmp_path / "eval.json"
    shard = tmp_path / "shard.txt"
    config = tmp_path / "config.json"
    run = tmp_path / "run.json"
    out = tmp_path / "receipt.json"
    eval_path.write_text(json.dumps([{"item_id": "x", "text": "clean"}]), encoding="utf-8")
    shard.write_text("different corpus", encoding="utf-8")
    config.write_text(json.dumps({"shards": [str(shard)]}), encoding="utf-8")
    run.write_text(json.dumps({"steps": 1, "wall_s": 1}), encoding="utf-8")
    result = run_shields(
        str(eval_path), [str(shard)], [str(config)], [str(run)], str(out),
        timestamp="20260807T000000Z",
        component_d_comment_url="https://github.com/wordingone/ember/issues/123#issuecomment-test",
        component_d_comment_body_sha256="a" * 64,
    )
    transfer = result["component_d_transfer"]
    assert transfer["status"] == "TRANSFERRED_TO_CANONICAL_CARRIER"
    assert transfer["carrier_issue"] == 123
    assert transfer["carrier_comment_body_sha256"] == "a" * 64
    assert set(transfer["accepted_clauses"]) == {
        "coordinator freeze declaration binds commit_hash suite_manifest_sha256 ts",
        "pre-freeze numbers are labeled development appendix",
        "one held-out eval selected by a published rule seeded by freeze commit",
        "no human selection and no capability claim before freeze",
    }


def test_compute_ledger_binds_nested_measured_segment_and_runner_hook(tmp_path):
    measured = {
        "steps": None,
        "wall_s": None,
        "post_grow_segment": {"steps": 60, "wall_s": 64.433},
        "governor": {"peak_vram_used_gib": 12.5},
    }
    ledger = compute_ledger.compute_ledger_from_receipt(measured)
    assert ledger["optimizer_steps"] == 60
    assert ledger["wall_seconds"] == 64.433
    assert ledger["sec_per_step_mean"] == 1.0739
    assert ledger["peak_vram_gib"] == 12.5
    runner = Path(__file__).resolve().parents[1] / "timeshare_pretrain.py"
    assert compute_ledger.verify_production_hook(runner)["status"] == "EXECUTION_DENIED"
    bad = tmp_path / "runner.py"
    bad.write_text("def run():\n    return {}\n", encoding="utf-8")
    try:
        compute_ledger.verify_production_hook(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("missing ledger hook must fail closed")


def test_execution_denied_producer_cannot_report_verified(tmp_path):
    denied = tmp_path / "denied.py"
    denied.write_text("# EMBER_ARTIFACT_CLASS=historical_only\nraise SystemExit('historical_only')\nreceipt = add_compute_ledger_to_receipt(receipt)\nreturn receipt\n", encoding="utf-8")
    result = compute_ledger.verify_production_hook(denied)
    assert result["status"] == "EXECUTION_DENIED"
