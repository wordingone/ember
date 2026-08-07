# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_source(root: Path, name: str, rows: list[dict], *, license_name: str = "CC0-1.0") -> None:
    source = root / name
    source.mkdir(parents=True)
    payload = b"".join(
        (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        for row in rows
    )
    data_path = source / "records.jsonl"
    data_path.write_bytes(payload)
    receipt = {
        "relative_path": "records.jsonl",
        "source_url": f"https://example.invalid/{name}",
        "sha256": _sha(payload),
        "bytes": len(payload),
        "license": license_name,
        "human_provenance_basis": "fixture human-authored records",
        "fetched_ts": "2026-08-06T00:00:00Z",
        "selection_rule": "fixture-records-v1",
    }
    (source / "manifest.jsonl").write_text(json.dumps(receipt) + "\n", encoding="utf-8")


def _fixture(root: Path) -> Path:
    raw = root / "raw"
    _write_source(
        raw,
        "alpha",
        [
            {"id": "a0", "text": "alpha one"},
            {"id": "a1", "text": "alpha two"},
            {"id": "a2", "text": "shared duplicate"},
        ],
    )
    _write_source(
        raw,
        "beta",
        [
            {"id": "b0", "text": "beta one"},
            {"id": "b1", "text": "shared duplicate"},
            {"id": "b2", "text": "beta three"},
        ],
    )
    return raw


def test_missing_builder_api_is_the_first_red():
    from scripts.corpus.owned_v1 import build_owned_corpus

    assert build_owned_corpus is not None


def test_source_inventory_is_closed_and_rejects_unknown_license(tmp_path: Path):
    from scripts.corpus.owned_v1 import load_source_inventory

    raw = tmp_path / "raw"
    _write_source(raw, "bad", [{"id": "x", "text": "x"}], license_name="")
    with pytest.raises(ValueError, match="license"):
        load_source_inventory(raw, source_names=("bad",))


def test_build_is_byte_stable_and_split_roots_are_disjoint(tmp_path: Path):
    from scripts.corpus.owned_v1 import build_owned_corpus

    raw = _fixture(tmp_path)
    first = build_owned_corpus(raw_root=raw, output_root=tmp_path / "first", source_names=("alpha", "beta"), shard_records=2)
    second = build_owned_corpus(raw_root=raw, output_root=tmp_path / "second", source_names=("alpha", "beta"), shard_records=2)
    assert (tmp_path / "first" / "manifest.json").read_bytes() == (tmp_path / "second" / "manifest.json").read_bytes()
    assert first["train_root_sha256"] == second["train_root_sha256"]
    assert first["heldout_root_sha256"] == second["heldout_root_sha256"]
    assert set(first["train_content_sha256"]).isdisjoint(first["heldout_content_sha256"])
    assert "raw" not in (tmp_path / "first" / "manifest.json").read_text(encoding="utf-8")


def test_resume_from_completed_shard_matches_uninterrupted_build(tmp_path: Path):
    from scripts.corpus.owned_v1 import build_owned_corpus

    raw = _fixture(tmp_path)
    partial = tmp_path / "partial"
    receipt = build_owned_corpus(raw_root=raw, output_root=partial, source_names=("alpha", "beta"), shard_records=2, max_records=2)
    assert receipt["result"] == "INTERRUPTED"
    resumed = build_owned_corpus(raw_root=raw, output_root=partial, source_names=("alpha", "beta"), shard_records=2, resume=True)
    clean = build_owned_corpus(raw_root=raw, output_root=tmp_path / "clean", source_names=("alpha", "beta"), shard_records=2)
    assert resumed == clean
    assert (partial / "manifest.json").read_bytes() == (tmp_path / "clean" / "manifest.json").read_bytes()


def test_malformed_record_and_path_escape_fail_closed(tmp_path: Path):
    from scripts.corpus.owned_v1 import build_owned_corpus

    raw = tmp_path / "raw"
    _write_source(raw, "alpha", [{"id": "a", "text": "ok"}])
    (raw / "alpha" / "manifest.jsonl").write_text(
        json.dumps({
            "relative_path": "../outside.jsonl",
            "source_url": "https://example.invalid/alpha",
            "sha256": "0" * 64,
            "bytes": 1,
            "license": "CC0-1.0",
            "human_provenance_basis": "fixture",
            "fetched_ts": "2026-08-06T00:00:00Z",
            "selection_rule": "fixture-records-v1",
        }) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="path"):
        build_owned_corpus(raw_root=raw, output_root=tmp_path / "out", source_names=("alpha",))



def test_uppercase_receipt_digest_is_canonicalized(tmp_path: Path):
    from scripts.corpus.owned_v1 import load_source_inventory

    raw = tmp_path / "raw"
    _write_source(raw, "alpha", [{"id": "a", "text": "ok"}])
    receipt_path = raw / "alpha" / "manifest.jsonl"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["sha256"] = receipt["sha256"].upper()
    receipt_path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    rows = load_source_inventory(raw, source_names=("alpha",))
    assert rows[0]["sha256"] == receipt["sha256"].lower()


def test_output_root_inside_raw_custody_is_rejected(tmp_path: Path):
    from scripts.corpus.owned_v1 import build_owned_corpus

    raw = _fixture(tmp_path)
    with pytest.raises(ValueError, match="raw|output|custody"):
        build_owned_corpus(raw_root=raw, output_root=raw / "assembled", source_names=("alpha", "beta"), shard_records=2)


def test_manifest_reopen_rejects_undeclared_extra_shard(tmp_path: Path):
    from scripts.corpus.owned_v1 import build_owned_corpus, validate_manifest

    raw = _fixture(tmp_path)
    out = tmp_path / "out"
    build_owned_corpus(raw_root=raw, output_root=out, source_names=("alpha", "beta"), shard_records=2)
    extra = out / "train" / "shard-extra.jsonl"
    extra.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="extra|unexpected|shard"):
        validate_manifest(out / "manifest.json", output_root=out)


def test_manifest_reopen_rejects_source_binding_drift(tmp_path: Path):
    from scripts.corpus.owned_v1 import build_owned_corpus, validate_manifest

    raw = _fixture(tmp_path)
    out = tmp_path / "out"
    build_owned_corpus(raw_root=raw, output_root=out, source_names=("alpha", "beta"), shard_records=2)
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sources"][0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source|binding"):
        validate_manifest(manifest_path, output_root=out)


def test_truncated_gzip_record_fails_closed(tmp_path: Path):
    from scripts.corpus.owned_v1 import build_owned_corpus

    raw = tmp_path / "raw"
    source = raw / "alpha"
    source.mkdir(parents=True)
    data_path = source / "records.jsonl.gz"
    data_path.write_bytes(b"\x1f\x8b\x08\x00truncated")
    receipt = {
        "relative_path": "records.jsonl.gz",
        "source_url": "https://example.invalid/alpha",
        "sha256": _sha(data_path.read_bytes()),
        "bytes": data_path.stat().st_size,
        "license": "CC0-1.0",
        "human_provenance_basis": "fixture human-authored records",
        "fetched_ts": "2026-08-06T00:00:00Z",
        "selection_rule": "fixture-records-v1",
    }
    (source / "manifest.jsonl").write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="gzip|record|source"):
        build_owned_corpus(raw_root=raw, output_root=tmp_path / "out", source_names=("alpha",))


def test_manifest_reopen_rejects_shard_byte_drift(tmp_path: Path):
    from scripts.corpus.owned_v1 import build_owned_corpus, validate_manifest

    raw = _fixture(tmp_path)
    build_owned_corpus(raw_root=raw, output_root=tmp_path / "out", source_names=("alpha", "beta"), shard_records=2)
    manifest_path = tmp_path / "out" / "manifest.json"
    validate_manifest(manifest_path, output_root=tmp_path / "out")
    shard = next((tmp_path / "out" / "train").glob("*.jsonl"))
    shard.write_bytes(shard.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="shard"):
        validate_manifest(manifest_path, output_root=tmp_path / "out")


def test_receipt_manifest_utf8_bom_is_decoded_without_changing_bound_bytes(tmp_path: Path):
    from scripts.corpus.owned_v1 import load_source_inventory

    raw = tmp_path / "raw"
    _write_source(raw, "alpha", [{"id": "a", "text": "ok"}])
    receipt_path = raw / "alpha" / "manifest.jsonl"
    receipt_path.write_bytes(b"\xef\xbb\xbf" + receipt_path.read_bytes())
    rows = load_source_inventory(raw, source_names=("alpha",))
    assert len(rows) == 1
    assert rows[0]["manifest_sha256"] == _sha(receipt_path.read_bytes())


def test_duplicate_receipt_rows_are_rejected_before_build(tmp_path: Path):
    from scripts.corpus.owned_v1 import load_source_inventory

    raw = tmp_path / "raw"
    _write_source(raw, "alpha", [{"id": "a", "text": "ok"}])
    receipt_path = raw / "alpha" / "manifest.jsonl"
    line = receipt_path.read_bytes()
    receipt_path.write_bytes(line + line)
    with pytest.raises(ValueError, match="duplicated|duplicate"):
        load_source_inventory(raw, source_names=("alpha",))


def test_manifest_source_authority_hash_is_recomputed(tmp_path: Path):
    from scripts.corpus.owned_v1 import build_owned_corpus, validate_manifest

    raw = _fixture(tmp_path)
    out = tmp_path / "out"
    build_owned_corpus(raw_root=raw, output_root=out, source_names=("alpha", "beta"), shard_records=2)
    path = out / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["source_manifest_sha256"] = "0" * 64
    path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source authority|source manifest"):
        validate_manifest(path, output_root=out)


def test_owned_corpus_cursor_reopens_closed_manifest_and_streams_without_materializing(tmp_path: Path):
    from scripts.corpus.owned_v1 import build_owned_corpus, iter_owned_records

    raw = _fixture(tmp_path)
    out = tmp_path / "out"
    manifest = build_owned_corpus(raw_root=raw, output_root=out, source_names=("alpha", "beta"), shard_records=2)
    cursor = {
        "schema_version": "ember-owned-corpus-cursor-v1",
        "manifest_sha256": _sha((out / "manifest.json").read_bytes()),
        "split": "train",
        "root_sha256": manifest["train_root_sha256"],
        "record_index": 0,
    }
    first = list(iter_owned_records(out / "manifest.json", output_root=out, cursor=cursor, max_records=1))
    assert len(first) == 1
    assert first[0][1]["record_index"] == 1
    assert first[0][1]["manifest_sha256"] == cursor["manifest_sha256"]
    with pytest.raises(ValueError, match="manifest|cursor|root"):
        list(iter_owned_records(out / "manifest.json", output_root=out, cursor={**cursor, "manifest_sha256": "0" * 64}, max_records=1))


def test_owned_corpus_cursor_rejects_wrong_split_root_and_range(tmp_path: Path):
    from scripts.corpus.owned_v1 import build_owned_corpus, iter_owned_records

    raw = _fixture(tmp_path)
    out = tmp_path / "out"
    manifest = build_owned_corpus(raw_root=raw, output_root=out, source_names=("alpha", "beta"), shard_records=2)
    base = {"schema_version": "ember-owned-corpus-cursor-v1", "manifest_sha256": _sha((out / "manifest.json").read_bytes()), "split": "train", "root_sha256": manifest["train_root_sha256"], "record_index": 0}
    for cursor, message in (({**base, "split": "heldout", "root_sha256": base["root_sha256"]}, "root"), ({**base, "root_sha256": "0" * 64}, "root"), ({**base, "record_index": 10_000}, "cursor")):
        with pytest.raises(ValueError, match=message):
            list(iter_owned_records(out / "manifest.json", output_root=out, cursor=cursor, max_records=1))
