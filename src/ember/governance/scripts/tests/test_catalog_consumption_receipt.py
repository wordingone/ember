# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""catalog_consumption_receipt: consumed-window accounting, planted negatives, import fragment."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import catalog_consumption_receipt as ccr  # noqa: E402
import catalog_train_stream as cts  # noqa: E402

SEQ = 8
STEPS = 5
SHARD = 32
HEAD = "a" * 40
TOKENIZER = "2" * 64


def _digest(tag: str) -> str:
    return cts.sha(tag.encode()).lower()


def _export(objects: list[str], heldout: list[str], datasets: list[str]) -> dict:
    records = []
    edges = []
    for d in datasets:
        records.append({"kind": "dataset_version", "id": d, "state": "admitted"})
    for h in objects:
        records.append({"kind": "immutable_object", "id": f"sha256:{h}", "sha256": h})
        records.append({"kind": "membership", "exact_sha256": h, "split": "train", "admission_state": "admitted", "dataset_version_id": datasets[0]})
    for h in heldout:
        records.append({"kind": "immutable_object", "id": f"sha256:{h}", "sha256": h})
        records.append({"kind": "membership", "exact_sha256": h, "split": "heldout", "admission_state": "admitted"})
    eval_sha = _digest("eval")
    records.append({"kind": "protected_eval", "id": f"evaluation:e-matrix-catalog-isolation:{eval_sha}"})
    edges.append({"kind": "evaluation_object", "from_id": f"evaluation:e-matrix-catalog-isolation:{eval_sha}", "to_id": f"sha256:{_digest('eval-object')}"})
    return {"schema_version": "ember-data-catalog-export-v1", "records": records, "edges": edges}


@pytest.fixture
def world(tmp_path: Path) -> dict:
    objects = [_digest(f"obj{i}") for i in range(6)]
    heldout = [_digest("held0")]
    datasets = [f"dataset:issue1581-bulk-train:{_digest('ds0')}", f"dataset:issue1581-bulk-train:{_digest('ds1')}"]
    datasets.sort()
    export = _export(objects, heldout, datasets)
    export_raw = json.dumps(export, sort_keys=True).encode() + b"\n"
    export_path = tmp_path / "export.json"
    export_path.write_bytes(export_raw)
    receipt = cts.self_hashed(
        {
            "schema_version": cts.STREAM_RECEIPT_SCHEMA,
            "shards": [{"name": "v1-00000.bin", "n_tokens": SHARD, "sha256": _digest("s0")}, {"name": "v1-00001.bin", "n_tokens": SHARD, "sha256": _digest("s1")}],
            "total_stream_tokens": 2 * SHARD,
            "content_total_tokens": 2 * SHARD - 5,
            "separator_tokens": 5,
            "catalog_binding": {"catalog_export_sha256": cts.sha(export_raw), "dataset_ids": datasets, "staging_manifest_raw_sha256": _digest("staging")},
        }
    )
    receipt_raw = json.dumps(receipt, sort_keys=True).encode() + b"\n"
    receipt_path = tmp_path / "stream-receipt.json"
    receipt_path.write_bytes(receipt_raw)
    # six objects, 10/11 tokens each, contiguous over 64 tokens
    bounds = [0, 10, 21, 32, 43, 54, 64]
    spans = [{"sha256": objects[i], "token_start": bounds[i], "token_end": bounds[i + 1]} for i in range(6)]
    spans_doc = {"schema_version": cts.BINDING_SCHEMA, "receipt_self_sha256": receipt["self_sha256"], "spans": spans}
    spans_path = tmp_path / "spans.json"
    spans_path.write_bytes(json.dumps(spans_doc, sort_keys=True).encode() + b"\n")
    tokens_seen = STEPS * SEQ  # 40 -> shard 1 offset 8
    result = {
        "segment": {
            "global_step": STEPS,
            "tokens_seen": tokens_seen,
            "data_cursor": {"shard": "TOKEN-SHARDS-V0:" + cts.sha(receipt_raw)[:12], "record_index": STEPS, "receipt_sha256": cts.sha(receipt_raw), "tokenizer_sha256": TOKENIZER, "shard_index": 1, "token_offset": tokens_seen - SHARD, "global_step": STEPS, "tokens_seen": tokens_seen},
        },
        "stream_receipt_sha256": cts.sha(receipt_raw),
        "tokenizer_sha256": TOKENIZER,
        "launch_seed": 7,
    }
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    runner_receipt_path = tmp_path / "runner-receipt.json"
    runner_receipt_path.write_text(json.dumps({"schema_version": 7, "runner_exit_code": 0, "child_exit_code": 0}), encoding="utf-8")
    run_spec_path = tmp_path / "run-spec.json"
    run_spec_path.write_text(json.dumps({"semantic_canary_sequence_length": SEQ, "requested_scope": {"optimizer_steps": STEPS}}), encoding="utf-8")
    return {
        "tmp": tmp_path, "objects": objects, "heldout": heldout, "datasets": datasets, "export": export, "export_path": export_path,
        "receipt_path": receipt_path, "receipt_sha": cts.sha(receipt_raw), "spans_path": spans_path, "spans_doc": spans_doc,
        "result": result, "result_path": result_path, "runner_receipt_path": runner_receipt_path, "run_spec_path": run_spec_path,
    }


def _emit(world: dict, out: str = "receipt.json", **overrides) -> tuple[int, dict]:
    output = world["tmp"] / out
    argv = [
        "emit", "--runner-result", str(overrides.get("result_path", world["result_path"])),
        "--runner-receipt", str(world["runner_receipt_path"]), "--run-spec", str(world["run_spec_path"]),
        "--stream-receipt", str(world["receipt_path"]), "--expected-stream-receipt-sha256", overrides.get("expected", world["receipt_sha"]),
        "--spans", str(overrides.get("spans_path", world["spans_path"])), "--catalog-export", str(overrides.get("export_path", world["export_path"])),
        "--run-id", "run-test", "--merged-head", HEAD, "--output", str(output),
    ]
    rc = ccr.main(argv)
    return rc, (json.loads(output.read_bytes()) if output.exists() else {})


def test_receipt_binds_window_and_partial_object(world: dict, capsys) -> None:
    rc, receipt = _emit(world)
    assert rc == 0, capsys.readouterr().out
    c = receipt["consumption"]
    assert c["consumed_token_count"] == 40 and c["window_token_end"] == 41 and c["lookahead_tokens"] == 1
    assert c["final_cursor"] == {"shard_index": 1, "token_offset": 8, "position": 40}
    # objects 0..3 fully (0-43 covers 41), object 3 is partial (32..43 clipped to 41)
    assert [row["sha256"] for row in c["consumed_object_spans"]] == world["objects"][:4]
    assert c["consumed_object_spans"][-1] == {"sha256": world["objects"][3], "token_start": 32, "token_end": 41, "partial": True}
    assert c["partial_object_count"] == 1 and receipt["leakage_assertion"]["result"] == "executed_pass"
    cts.verify_self_hash(receipt, "X")


def test_count_off_by_one_sequence_refuses(world: dict, capsys) -> None:
    bad = json.loads(json.dumps(world["result"]))
    bad["segment"]["tokens_seen"] -= SEQ
    bad["segment"]["data_cursor"]["tokens_seen"] -= SEQ
    bad["segment"]["data_cursor"]["token_offset"] -= SEQ
    p = world["tmp"] / "bad-result.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    rc, _ = _emit(world, out="r2.json", result_path=p)
    assert rc == 78 and "CONSUMED_COUNT_MISMATCH_REFUSED:32!=40" in capsys.readouterr().out


def test_planted_heldout_object_in_consumed_window_refuses(world: dict, capsys) -> None:
    doc = json.loads(json.dumps(world["spans_doc"]))
    doc["spans"][1]["sha256"] = world["heldout"][0]
    p = world["tmp"] / "spans-leak.json"
    p.write_bytes(json.dumps(doc, sort_keys=True).encode() + b"\n")
    rc, _ = _emit(world, out="r3.json", spans_path=p)
    assert rc == 78 and f"LEAKAGE_REFUSED:heldout:{world['heldout'][0]}" in capsys.readouterr().out


def test_span_file_byte_change_refuses(world: dict, capsys) -> None:
    raw = bytearray(world["spans_path"].read_bytes())
    marker = raw.find(b'"receipt_self_sha256": "') + len(b'"receipt_self_sha256": "')
    raw[marker] = ord("0") if raw[marker] != ord("0") else ord("1")
    p = world["tmp"] / "spans-flip.json"
    p.write_bytes(bytes(raw))
    rc, _ = _emit(world, out="r4.json", spans_path=p)
    assert rc == 78 and "SPANS_RECEIPT_BINDING_REFUSED" in capsys.readouterr().out


def test_stream_receipt_pin_drift_refuses(world: dict, capsys) -> None:
    rc, _ = _emit(world, out="r5.json", expected="f" * 64)
    assert rc == 78 and "STREAM_RECEIPT_SHA256_DRIFT_REFUSED" in capsys.readouterr().out


def test_fragment_binds_one_attempt_per_dataset(world: dict, capsys) -> None:
    rc, receipt = _emit(world, out="r6.json")
    assert rc == 0
    ckpt = world["tmp"] / "checkpoint-manifest.json"
    ckpt.write_text("{}", encoding="utf-8")
    cfg = world["tmp"] / "config.json"
    cfg.write_text("{}", encoding="utf-8")
    eval_id = next(r["id"] for r in world["export"]["records"] if r["kind"] == "protected_eval")
    out = world["tmp"] / "fragment.json"
    rc = ccr.main(["fragment", "--receipt", str(world["tmp"] / "r6.json"), "--catalog-export", str(world["export_path"]), "--evaluation-id", eval_id, "--checkpoint-manifest", str(ckpt), "--architecture-config", str(cfg), "--output", str(out)])
    assert rc == 0, capsys.readouterr().out
    fragment = json.loads(out.read_bytes())
    attempts = [r for r in fragment["records"] if r["kind"] == "consumer_attempt"]
    assert len(attempts) == len(world["datasets"]) and all(a["id"] == a["run_attempt_id"] and a["state"] == "completed" for a in attempts)
    receipt_sha = cts.sha_file(world["tmp"] / "r6.json")
    for a in attempts:
        mine = [e for e in fragment["edges"] if e["from_id"] == a["id"]]
        assert sorted(e["kind"] for e in mine) == ["consumer_dataset", "consumer_evaluation", "consumer_receipt"]
        assert {e["to_id"] for e in mine if e["kind"] == "consumer_receipt"} == {f"sha256:{receipt_sha}"}
        assert a["source_tree_sha"] == HEAD and a["tokenizer_sha256"] == TOKENIZER
    assert {e["to_id"] for e in fragment["edges"] if e["kind"] == "consumer_dataset"} == set(world["datasets"])
    assert [r for r in fragment["records"] if r["kind"] == "receipt"][0]["sha256"] == receipt_sha
    # an evaluation id absent from the export refuses
    rc = ccr.main(["fragment", "--receipt", str(world["tmp"] / "r6.json"), "--catalog-export", str(world["export_path"]), "--evaluation-id", "evaluation:missing", "--checkpoint-manifest", str(ckpt), "--architecture-config", str(cfg), "--output", str(world["tmp"] / "f2.json")])
    assert rc == 78 and "EVALUATION_ID_ABSENT_REFUSED" in capsys.readouterr().out


# --------------------------------------------------------------------------- shard ledger (#2135)
def _ledger_for(world: dict, extra_tokens: int) -> tuple[Path, dict]:
    """Genesis rows restating the receipt's two shards, plus one produced shard with real bytes."""

    receipt = json.loads(world["receipt_path"].read_bytes())
    spans = world["spans_doc"]["spans"]
    rows = []
    prev = cts.LEDGER_GENESIS_PREV
    running = 0
    for index, shard in enumerate(receipt["shards"]):
        end = running + shard["n_tokens"]
        clipped = cts._clip_spans(spans, running, end)
        row = cts.build_ledger_row(index=index, name=shard["name"], sha256=shard["sha256"], n_tokens=shard["n_tokens"], token_start=running,
                                   spans=clipped, resume={"object_index": 0, "carry_tokens": 0}, exhausted=False, prev_row_sha256=prev)
        rows.append(row); prev = row["row_sha256"]; running = end
    chunk = bytes(range(extra_tokens * 2 % 256)) if False else b"\x01\x00" * extra_tokens
    name = f"v1-00002-{cts.sha(chunk)[:12]}.bin"
    (world["tmp"] / name).write_bytes(chunk)
    row = cts.build_ledger_row(index=2, name=name, sha256=cts.sha(chunk), n_tokens=extra_tokens, token_start=running,
                               spans=[{"sha256": world["objects"][0], "token_start": running, "token_end": running + extra_tokens}],
                               resume={"object_index": 6, "carry_tokens": 0}, exhausted=True, prev_row_sha256=prev)
    rows.append(row)
    ledger = world["tmp"] / "shard-ledger-s32.jsonl"
    ledger.write_bytes(b"".join(json.dumps(r, sort_keys=True, separators=(",", ":")).encode() + b"\n" for r in rows))
    return ledger, rows[-1]


def test_cursor_beyond_the_receipt_needs_the_ledger_and_binds_it(world: dict, capsys) -> None:
    ledger, produced = _ledger_for(world, extra_tokens=16)
    # 2 receipt shards of 32 + one ledger shard of 16 = 80 tokens; a run of 9 steps x 8 = 72 lands in shard 2.
    beyond = json.loads(json.dumps(world["result"]))
    beyond["segment"]["global_step"] = 9
    beyond["segment"]["tokens_seen"] = 72
    beyond["segment"]["data_cursor"].update({"global_step": 9, "tokens_seen": 72, "shard_index": 2, "token_offset": 8, "record_index": 9})
    result_path = world["tmp"] / "beyond.json"
    result_path.write_text(json.dumps(beyond), encoding="utf-8")
    world["run_spec_path"].write_text(json.dumps({"semantic_canary_sequence_length": SEQ, "requested_scope": {"optimizer_steps": 9}}), encoding="utf-8")
    rc, _ = _emit(world, out="no-ledger.json", result_path=result_path)
    assert rc == 78 and "CURSOR_OUT_OF_RANGE_REFUSED" in capsys.readouterr().out
    output = world["tmp"] / "with-ledger.json"
    argv = [
        "emit", "--runner-result", str(result_path), "--runner-receipt", str(world["runner_receipt_path"]), "--run-spec", str(world["run_spec_path"]),
        "--stream-receipt", str(world["receipt_path"]), "--expected-stream-receipt-sha256", world["receipt_sha"], "--spans", str(world["spans_path"]),
        "--catalog-export", str(world["export_path"]), "--run-id", "run-ledger", "--merged-head", HEAD, "--shard-ledger", str(ledger), "--shards-root", str(world["tmp"]),
        "--output", str(output),
    ]
    assert ccr.main(argv) == 0, capsys.readouterr().out
    receipt = json.loads(output.read_bytes())
    assert receipt["stream"]["total_stream_tokens"] == 80 and receipt["stream"]["receipt_total_stream_tokens"] == 64
    assert receipt["stream"]["receipt_shard_count"] == 2 and len(receipt["stream"]["shards"]) == 3
    assert receipt["stream"]["shard_ledger"] == {"raw_sha256": cts.sha_file(ledger), "rows": 3, "rows_beyond_receipt": 1, "rows_consumed": 3}
    assert receipt["consumption"]["consumed_token_count"] == 72 and receipt["consumption"]["final_cursor"] == {"shard_index": 2, "token_offset": 8, "position": 72}
    last = receipt["consumption"]["consumed_object_spans"][-1]
    assert last["sha256"] == world["objects"][0] and last["token_start"] == 64 and last["token_end"] == 73 and last["partial"]
    # Drifted ledger shard bytes refuse; a ledger whose genesis disagrees with the receipt refuses.
    (world["tmp"] / produced["name"]).write_bytes(b"\x02\x00" * 16)
    out2 = world["tmp"] / "drift.json"
    assert ccr.main(argv[:-1] + [str(out2)]) == 78 and "SHARD_LEDGER_BYTES_REFUSED" in capsys.readouterr().out
