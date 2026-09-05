# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
SOURCE = ROOT / "src" / "ember" / "governance" / "scripts" / "catalog_train_stream.py"
SPEC = importlib.util.spec_from_file_location("catalog_train_stream", SOURCE)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

SEMANTIC = ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b" / "semantic_stream.py"
SEMANTIC_SPEC = importlib.util.spec_from_file_location("semantic_stream", SEMANTIC)
assert SEMANTIC_SPEC and SEMANTIC_SPEC.loader
SEMANTIC_MODULE = importlib.util.module_from_spec(SEMANTIC_SPEC)
sys.modules[SEMANTIC_SPEC.name] = SEMANTIC_MODULE
SEMANTIC_SPEC.loader.exec_module(SEMANTIC_MODULE)

TRAIN = "dataset:issue1581-bulk-train:" + "a" * 64
HELDOUT = "dataset:issue1581-bulk-heldout:" + "b" * 64


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_tokenizer(tmp_path: Path) -> tuple[Path, str]:
    """A WordLevel tokenizer whose ids 0..7 are reserved band tokens unreachable from text."""

    tokenizers = pytest.importorskip("tokenizers")
    from tokenizers import Tokenizer, models, pre_tokenizers

    vocab = {f"<band{i}>": i for i in range(8)}
    words = ["hello", "world", "catalog", "train", "stream", "doc", "one", "two", "[UNK]"]
    for offset, word in enumerate(words):
        vocab[word] = 8 + offset
    tokenizer = Tokenizer(models.WordLevel(vocab=vocab, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.add_special_tokens(["<band1>"])
    path = tmp_path / "tokenizer.json"
    tokenizer.save(str(path))
    return path, sha(path.read_bytes())


def build_fixture(tmp_path: Path, *, leak: bool = False, adjudicated_overlap: bool = False, quarantined_train: bool = False) -> tuple[Path, Path, list[bytes]]:
    custody = tmp_path / "custody"
    custody.mkdir()
    payloads = [b"hello world\n", b"catalog train stream doc one\n", b"two two two\n"]
    files = []
    overlap_raw = b"overlap text adjudicated to train\n"
    withdrawn_raw = b"train text withdrawn by quarantine\n"
    custody_payloads = list(payloads) + ([overlap_raw] if adjudicated_overlap else []) + ([withdrawn_raw] if quarantined_train else [])
    for index, raw in enumerate(custody_payloads):
        (custody / f"f{index}.txt").write_bytes(raw)
        files.append({"path": f"f{index}.txt", "bytes": len(raw), "sha256": sha(raw)})
    receipt = {"schema": "corpus-connector-receipt-v1", "dest_root": str(custody), "files": files}
    receipt_raw = json.dumps(receipt).encode()
    receipt_path = tmp_path / "connector-receipt.json"
    receipt_path.write_bytes(receipt_raw)

    heldout_raw = b"protected heldout text\n"
    pdf_raw = b"%PDF-1.4 fake"
    records: list[dict] = [
        {"kind": "dataset_version", "id": TRAIN, "state": "admitted"},
        {"kind": "dataset_version", "id": HELDOUT, "state": "admitted"},
        {"kind": "receipt", "id": "sha256:" + sha(receipt_raw), "sha256": sha(receipt_raw)},
    ]
    edges: list[dict] = []

    def add(raw: bytes, split: str, dataset: str, media: str, state: str = "admitted") -> None:
        digest = sha(raw)
        records.append({"kind": "immutable_object", "id": f"sha256:{digest}", "sha256": digest, "byte_count": len(raw), "media_type": media, "locator": f"sha256/{digest[:2]}/{digest}", "custody_state": "available"})
        membership = f"membership:{dataset[-8:]}:{split}:{state}:{digest}"
        records.append({"kind": "membership", "id": membership, "split": split, "admission_state": state, "exact_sha256": digest, "tokenizer_sha256": "t" * 64})
        edges.append({"kind": "version_membership", "from_id": dataset, "to_id": membership})
        edges.append({"kind": "membership_object", "from_id": membership, "to_id": f"sha256:{digest}"})
        edges.append({"kind": "object_receipt", "from_id": f"sha256:{digest}", "to_id": "sha256:" + sha(receipt_raw)})

    for raw in payloads:
        add(raw, "train", TRAIN, "text/plain; charset=utf-8")
    add(pdf_raw, "train", TRAIN, "application/pdf")
    add(heldout_raw, "heldout", HELDOUT, "text/plain; charset=utf-8")
    if leak:
        # The planted positive: a heldout object also carried by the train dataset.
        add(heldout_raw, "train", TRAIN, "text/plain; charset=utf-8")
    if adjudicated_overlap:
        # The catalog's own overlap resolution: the heldout side was quarantined, train stays admitted.
        add(overlap_raw, "heldout", HELDOUT, "text/plain; charset=utf-8", state="quarantined")
        add(overlap_raw, "train", TRAIN, "text/plain; charset=utf-8")
    if quarantined_train:
        add(withdrawn_raw, "train", TRAIN, "text/plain; charset=utf-8", state="quarantined")
        add(withdrawn_raw, "train", TRAIN, "text/plain; charset=utf-8")
    export_path = tmp_path / "export.json"
    export_path.write_bytes(json.dumps({"records": records, "edges": edges}).encode())
    return export_path, receipt_path, payloads


def test_stage_orders_classifies_and_excludes_deterministically(tmp_path: Path) -> None:
    export_path, receipt_path, payloads = build_fixture(tmp_path)
    manifest = MODULE.build_staging_manifest(
        export_raw=export_path.read_bytes(),
        dataset_ids=None,
        tokenizer_sha256="t" * 64,
        custody_receipts=[(receipt_path, receipt_path.read_bytes())],
    )
    assert manifest["result"] == "PASS"
    assert manifest["dataset_ids"] == [TRAIN]
    assert [row["sha256"] for row in manifest["rows"]] == sorted(sha(raw) for raw in payloads)
    assert manifest["excluded_media_classes"] == {"application/pdf": {"objects": 1, "bytes": 13}}
    assert manifest["unresolved_custody"] == {"objects": 0, "bytes": 0}
    assert manifest["leakage_assertion"]["result"] == "executed_pass"
    assert manifest["leakage_assertion"]["heldout_hashes"] == 1
    again = MODULE.build_staging_manifest(
        export_raw=export_path.read_bytes(),
        dataset_ids=None,
        tokenizer_sha256="t" * 64,
        custody_receipts=[(receipt_path, receipt_path.read_bytes())],
    )
    assert again["self_sha256"] == manifest["self_sha256"]


def test_stage_refuses_a_heldout_object_inside_the_train_dataset(tmp_path: Path) -> None:
    export_path, receipt_path, _ = build_fixture(tmp_path, leak=True)
    with pytest.raises(ValueError, match="LEAKAGE_REFUSED:heldout:"):
        MODULE.build_staging_manifest(
            export_raw=export_path.read_bytes(),
            dataset_ids=None,
            tokenizer_sha256="t" * 64,
            custody_receipts=[(receipt_path, receipt_path.read_bytes())],
        )


def test_stage_refuses_a_custody_receipt_the_catalog_never_bound(tmp_path: Path) -> None:
    export_path, receipt_path, _ = build_fixture(tmp_path)
    foreign = tmp_path / "foreign.json"
    foreign.write_bytes(json.dumps({"schema": "corpus-connector-receipt-v1", "dest_root": str(tmp_path), "files": []}).encode())
    with pytest.raises(ValueError, match="CUSTODY_RECEIPT_NOT_IN_CATALOG_REFUSED"):
        MODULE.build_staging_manifest(
            export_raw=export_path.read_bytes(),
            dataset_ids=None,
            tokenizer_sha256="t" * 64,
            custody_receipts=[(foreign, foreign.read_bytes())],
        )


def test_fill_produces_a_receipt_the_semantic_stream_loader_accepts_unchanged(tmp_path: Path) -> None:
    tokenizer_path, tokenizer_sha = write_tokenizer(tmp_path)
    export_path, receipt_path, payloads = build_fixture(tmp_path)
    export = json.loads(export_path.read_bytes())
    for row in export["records"]:
        if row.get("kind") == "membership":
            row["tokenizer_sha256"] = tokenizer_sha
    export_path.write_bytes(json.dumps(export).encode())
    manifest = MODULE.build_staging_manifest(
        export_raw=export_path.read_bytes(),
        dataset_ids=None,
        tokenizer_sha256=tokenizer_sha,
        custody_receipts=[(receipt_path, receipt_path.read_bytes())],
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_raw = json.dumps(manifest, sort_keys=True).encode()
    manifest_path.write_bytes(manifest_raw)
    cache = tmp_path / "cache"
    receipt_path_out, receipt = MODULE.fill_shards(
        manifest=manifest, manifest_raw_sha256=sha(manifest_raw), tokenizer_path=tokenizer_path,
        cache_root=cache, shard_tokens=4, shard_count=3,
    )
    assert receipt["ticket"] == "TOKEN-SHARDS-V0"
    assert receipt["catalog_binding"]["dataset_ids"] == [TRAIN]
    assert len(receipt["shards"]) == 3 and all(item["n_tokens"] == 4 for item in receipt["shards"])
    # Total tokens = 3 docs: (2+1) + (5+1) + (3+1) = 13; three shards of 4 cover the first 12.
    assert receipt["total_stream_tokens"] == 12
    stream = SEMANTIC_MODULE.ManifestBoundTokenStream.from_receipt(
        receipt_path=receipt_path_out, shards_root=receipt_path_out.parent, tokenizer_path=tokenizer_path,
    )
    assert stream.tokenizer_sha256 == tokenizer_sha
    episode, cursor = stream.next_episode(shard_index=0, token_offset=0, sequence_length=4)
    # Objects stage in sha256 order; rebuild the expected stream from that order.
    frozen, _ = MODULE.load_frozen_tokenizer(tokenizer_path, tokenizer_sha)
    expected: list[int] = []
    starts: list[int] = []
    for raw in sorted(payloads, key=sha):
        starts.append(len(expected))
        expected.extend(frozen.encode(raw.decode(), add_special_tokens=False).ids + [0])
    assert len(expected) == 13
    assert episode["token_ids"] == expected[:4]
    assert cursor == {"shard_index": 0, "token_offset": 4, "tokens_seen": 4}
    spans = json.loads((receipt_path_out.parent / "object-spans-k3-s4.json").read_text())["spans"]
    assert [span["token_start"] for span in spans] == starts
    assert spans[-1]["token_end"] == 12

    # Idempotent: a second fill with the same inputs re-verifies and rewrites nothing.
    before = {p.name: sha(p.read_bytes()) for p in receipt_path_out.parent.iterdir()}
    _, again = MODULE.fill_shards(
        manifest=manifest, manifest_raw_sha256=sha(manifest_raw), tokenizer_path=tokenizer_path,
        cache_root=cache, shard_tokens=4, shard_count=3,
    )
    assert again["self_sha256"] == receipt["self_sha256"]
    assert {p.name: sha(p.read_bytes()) for p in receipt_path_out.parent.iterdir()} == before

    # A mutated cached shard refuses both the loader and the producer's re-verification.
    shard = receipt_path_out.parent / receipt["shards"][0]["name"]
    shard.write_bytes(struct.pack("<4H", 8, 8, 8, 8))
    with pytest.raises(ValueError, match="shard sha256 does not match"):
        SEMANTIC_MODULE.ManifestBoundTokenStream.from_receipt(
            receipt_path=receipt_path_out, shards_root=receipt_path_out.parent, tokenizer_path=tokenizer_path,
        )
    with pytest.raises(ValueError, match="CACHED_SHARD_DRIFT_REFUSED"):
        MODULE.fill_shards(
            manifest=manifest, manifest_raw_sha256=sha(manifest_raw), tokenizer_path=tokenizer_path,
            cache_root=cache, shard_tokens=4, shard_count=3,
        )


def test_fill_refuses_a_document_that_reaches_the_reserved_band(tmp_path: Path) -> None:
    tokenizer_path, tokenizer_sha = write_tokenizer(tmp_path)
    export_path, receipt_path, _ = build_fixture(tmp_path)
    export = json.loads(export_path.read_bytes())
    for row in export["records"]:
        if row.get("kind") == "membership":
            row["tokenizer_sha256"] = tokenizer_sha
    export_path.write_bytes(json.dumps(export).encode())
    manifest = MODULE.build_staging_manifest(
        export_raw=export_path.read_bytes(), dataset_ids=None, tokenizer_sha256=tokenizer_sha,
        custody_receipts=[(receipt_path, receipt_path.read_bytes())],
    )

    def band_encoder(tokenizer: object, row: dict) -> tuple[list[int], int]:
        raise MODULE.StreamError(f"RESERVED_BAND_REFUSED:{row['sha256']}")

    with pytest.raises(ValueError, match="RESERVED_BAND_REFUSED"):
        MODULE.fill_shards(
            manifest=manifest, manifest_raw_sha256=sha(json.dumps(manifest).encode()), tokenizer_path=tokenizer_path,
            cache_root=tmp_path / "cache2", shard_tokens=4, shard_count=1, encoder=band_encoder,
        )
    # The frozen tokenizer's own added-token literal encodes as ordinary pieces (band unreachable).
    tokenizer, literals = MODULE.load_frozen_tokenizer(tokenizer_path, tokenizer_sha)
    assert literals == ["<band1>"]
    assert MODULE.reserved_band_probe(tokenizer, literals)["result"] == "PASS"


def test_stage_counts_the_catalogs_overlap_resolution_and_refuses_a_quarantined_train_membership(tmp_path: Path) -> None:
    export_path, receipt_path, payloads = build_fixture(tmp_path, adjudicated_overlap=True)
    manifest = MODULE.build_staging_manifest(
        export_raw=export_path.read_bytes(),
        dataset_ids=None,
        tokenizer_sha256="t" * 64,
        custody_receipts=[(receipt_path, receipt_path.read_bytes())],
    )
    assertion = manifest["leakage_assertion"]
    assert assertion["result"] == "executed_pass"
    assert assertion["adjudicated_overlap_hashes"] == 1
    assert assertion["adjudicated_overlap_staged"] == 1
    assert manifest["staged_count"] == len(payloads) + 1
    # The admitted heldout object is still protected.
    assert assertion["heldout_hashes"] == 1

    (tmp_path / "q").mkdir()
    export_path, receipt_path, _ = build_fixture(tmp_path / "q", quarantined_train=True)
    with pytest.raises(ValueError, match="TRAIN_MEMBERSHIP_STATE_REFUSED|LEAKAGE_REFUSED:quarantined:"):
        MODULE.build_staging_manifest(
            export_raw=export_path.read_bytes(),
            dataset_ids=None,
            tokenizer_sha256="t" * 64,
            custody_receipts=[(receipt_path, receipt_path.read_bytes())],
        )
