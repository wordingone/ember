# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Refusals of resume_identity.py on a synthetic parent hour."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

TOOL = Path(__file__).resolve().parents[2] / "src/ember/infrastructure/tools/ember-restart-3b/resume_identity.py"


def load():
    spec = importlib.util.spec_from_file_location("resume_identity", TOOL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def fixture(tmp: Path):
    old_root, intake = tmp / "old-root", tmp / "intake"
    old_root.mkdir()
    (intake / "shards").mkdir(parents=True)
    trained, ext = [], []
    for i in range(2):
        body = bytes([i]) * 8
        (old_root / f"t{i}.bin").write_bytes(body)
        trained.append({"index": i, "n_tokens": 4, "name": f"t{i}.bin", "sha256": sha(body), "row_sha256": f"r{i}",
                        "token_start": 4 * i})
    body = b"\x09" * 8
    (intake / "shards" / "e0.bin").write_bytes(body)
    e = {"index": 2, "n_tokens": 4, "name": "e0.bin", "sha256": sha(body), "row_sha256": "r2", "token_start": 8}
    ext.append(e)
    (intake / "ledger.jsonl").write_text(json.dumps(e) + "\n")
    composed = tmp / "composed.jsonl"
    composed.write_text("".join(json.dumps(r) + "\n" for r in trained + ext))
    digest = "".join(f"{r['sha256']}  {r['name']}\n" for r in trained)
    (tmp / "root.json").write_text(json.dumps({"root": str(old_root), "digest_list": digest}))
    side = {"schema": "s", "ledger_sha256": "x", "rows": [{"cls": "older", "epoch": None, "index": r["index"],
            "ledger_pass_index": 1, "n_tokens": 4, "name": r["name"], "repeat_declared": False,
            "row_sha256": r["row_sha256"], "token_start": r["token_start"]} for r in trained]}
    (tmp / "side.json").write_text(json.dumps(side))
    tmpl = {"data": {"cursor": {"shard_index": 0, "token_offset": 1}, "shard_ledger_path": "p", "shard_ledger_sha256": "s",
                     "shards_root": "r", "tokenizer_sha256": "keep"},
            "stream": {"hour_start_token": 1, "ledger_rows": 2, "total_stream_tokens": 8, "tokens_available_from_cursor": 7},
            "h35_source_binding": {"consumer_ledger": {"sha256": "s", "epoch_label_sidecar_sha256": "x"},
                                   "shards_root": {"path": "r", "files": 2, "digest_list_sha256": "d", "receipt_path": "q",
                                                   "receipt_sha256": "q"}}}
    (tmp / "tmpl.json").write_text(json.dumps(tmpl))
    (tmp / "cap.json").write_text(json.dumps({"cap": 1}))
    (tmp / "hour.json").write_text(json.dumps({"terminal_data_cursor": {"shard": 1, "record_index": 2}}))
    (tmp / "next.json").write_text(json.dumps({"cursor_before": {"shard_index": 1, "token_offset": 2}}))
    return SimpleNamespace(template=tmp / "tmpl.json", parent_sidecar=tmp / "side.json", parent_root_receipt=tmp / "root.json",
                           parent_cap=tmp / "cap.json", parent_continuation_hour=tmp / "hour.json",
                           parent_next_pack=tmp / "next.json", composed_ledger=composed,
                           shards_root=tmp / "new-root", out=tmp / "out", intake=[intake])


def test_builds_within_whitelist(tmp_path):
    m = load()
    r = m.build(fixture(tmp_path))
    assert r["cursor"] == {"shard_index": 1, "token_offset": 2}
    assert set(r["changed_fields"]) <= m.WHITELIST
    ident = json.loads((tmp_path / "out" / "mixture-identity.json").read_text())
    assert ident["data"]["tokenizer_sha256"] == "keep"
    side = json.loads((tmp_path / "out" / "epoch-labels.json").read_text())
    assert side["rows"][2]["epoch"] == 0 and side["rows"][0]["cls"] == "older"
    root = json.loads((tmp_path / "out" / "root-receipt.json").read_text())
    assert root["count"] == 3


def test_refuses_field_outside_whitelist(tmp_path, monkeypatch):
    m = load()
    a = fixture(tmp_path)
    monkeypatch.setattr(m, "WHITELIST", m.WHITELIST - {"data.shards_root"})
    with pytest.raises(SystemExit, match="outside the frozen whitelist"):
        m.build(a)


def test_refuses_extension_sha_mismatch(tmp_path):
    m = load()
    a = fixture(tmp_path)
    (a.intake[0] / "shards" / "e0.bin").write_bytes(b"\x08" * 8)
    with pytest.raises(SystemExit, match="sha does not match"):
        m.build(a)


def test_refuses_non_hardlink_in_root(tmp_path):
    m = load()
    a = fixture(tmp_path)
    a.shards_root.mkdir()
    shutil.copy(tmp_path / "old-root" / "t0.bin", a.shards_root / "t0.bin")
    with pytest.raises(SystemExit, match="not a hard link"):
        m.build(a)


def test_refuses_cursor_outside_trained_rows(tmp_path):
    m = load()
    a = fixture(tmp_path)
    a.parent_continuation_hour.write_text(json.dumps({"terminal_data_cursor": {"shard": "2", "record_index": 0}}))
    a.parent_next_pack.write_text(json.dumps({"cursor_before": {"shard_index": 2, "token_offset": 0}}))
    with pytest.raises(SystemExit, match="not inside the parent's trained rows"):
        m.build(a)


def test_refuses_next_pack_cursor_mismatch(tmp_path):
    m = load()
    a = fixture(tmp_path)
    a.parent_next_pack.write_text(json.dumps({"cursor_before": {"shard_index": 1, "token_offset": 1}}))
    with pytest.raises(SystemExit, match="differs from terminal_data_cursor"):
        m.build(a)


def test_sidecar_refuses_changed_trained_label():
    m = load()
    parent = {"rows": [{"index": 0, "epoch": 1}]}
    rows = [{"index": 0}, {"index": 1, "n_tokens": 4, "name": "e", "row_sha256": "r", "token_start": 4}]
    out = m.sidecar(parent, rows, 1, "L")
    assert out["rows"][0] == {"index": 0, "epoch": 1}
    with pytest.raises(SystemExit, match="1 rows, the trained ledger 2"):
        m.sidecar(parent, rows, 2, "L")
