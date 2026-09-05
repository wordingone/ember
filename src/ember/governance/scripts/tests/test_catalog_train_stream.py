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
        records.append({"kind": "membership", "id": membership, "split": split, "admission_state": state, "exact_sha256": digest, "tokenizer_sha256": "t" * 64, "window_start": 0, "window_end": len(raw)})
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
    written_receipt = json.loads(receipt_path_out.read_text(encoding="utf-8"))
    # Accounting is measured inside the written shards: content + separators == covered tokens.
    assert written_receipt["content_total_tokens"] + written_receipt["separator_tokens"] == written_receipt["total_stream_tokens"]
    assert written_receipt["separator_tokens"] >= 1
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


# --------------------------------------------------------------------------- plan (#2135)
AUTHORITY_TEXT = (
    "# EMBER-02\n\n16. Something else.\n"
    "17. Freeze a sufficient-pretraining token budget, minimum-token floor, and stopping rule from the measured 3B learning curve before the claim-bearing run.\n"
    "18. Another clause.\n"
)


def _staged_manifest(tmp_path: Path):
    export_path, receipt_path, payloads = build_fixture(tmp_path)
    manifest = MODULE.build_staging_manifest(
        export_raw=export_path.read_bytes(), dataset_ids=None, tokenizer_sha256="t" * 64,
        custody_receipts=[(receipt_path, receipt_path.read_bytes())],
    )
    manifest_raw = json.dumps(manifest, sort_keys=True).encode()
    return export_path, receipt_path, payloads, manifest, manifest_raw


def test_plan_coverage_equality_and_window_tokens(tmp_path: Path) -> None:
    export_path, receipt_path, payloads, manifest, manifest_raw = _staged_manifest(tmp_path)
    coverage = MODULE.build_coverage_receipt(
        export_raw=export_path.read_bytes(), manifest=manifest, manifest_raw_sha256=sha(manifest_raw),
        custody_receipts=[(receipt_path, receipt_path.read_bytes())],
    )
    assert coverage["result"] == "PASS" and coverage["schema_version"] == MODULE.COVERAGE_SCHEMA
    [row] = coverage["per_dataset"]
    # three staged text objects + one excluded pdf, no unresolved custody
    assert (row["staged"], row["excluded"], row["unresolved"], row["attributed_objects"]) == (3, 1, 0, 4)
    assert row["equality"] == "3 + 1 + 0 == 4"
    staged_tokens = sum(len(raw) for raw in payloads)
    assert row["window_tokens"]["staged"] == staged_tokens
    assert coverage["totals"]["catalog_window_tokens"] == staged_tokens + len(b"%PDF-1.4 fake")
    assert coverage["totals"]["excluded_media_classes"] == manifest["excluded_media_classes"]
    assert coverage["staging_manifest_self_sha256"] == manifest["self_sha256"]
    MODULE.verify_self_hash(coverage, "COVERAGE")


def test_plan_refuses_a_manifest_missing_a_stageable_object(tmp_path: Path) -> None:
    export_path, receipt_path, _, manifest, _ = _staged_manifest(tmp_path)
    # planted negative: drop one staged row and re-seal the manifest; the export still admits the object
    dropped = manifest["rows"][0]["sha256"]
    broken = dict(manifest)
    broken["rows"] = manifest["rows"][1:]
    broken["staged_count"] = len(broken["rows"])
    broken.pop("self_sha256")
    broken = MODULE.self_hashed(broken)
    with pytest.raises(MODULE.StreamError, match=f"COVERAGE_MISSING_OBJECT_REFUSED:{dropped}"):
        MODULE.build_coverage_receipt(
            export_raw=export_path.read_bytes(), manifest=broken, manifest_raw_sha256="0" * 64,
            custody_receipts=[(receipt_path, receipt_path.read_bytes())],
        )


def test_plan_refuses_export_drift_and_incomplete_custody(tmp_path: Path) -> None:
    export_path, receipt_path, _, manifest, manifest_raw = _staged_manifest(tmp_path)
    with pytest.raises(MODULE.StreamError, match="COVERAGE_EXPORT_DRIFT_REFUSED"):
        MODULE.build_coverage_receipt(
            export_raw=export_path.read_bytes() + b"\n", manifest=manifest, manifest_raw_sha256=sha(manifest_raw),
            custody_receipts=[(receipt_path, receipt_path.read_bytes())],
        )
    with pytest.raises(MODULE.StreamError, match="COVERAGE_CUSTODY_RECEIPTS_INCOMPLETE_REFUSED"):
        MODULE.build_coverage_receipt(
            export_raw=export_path.read_bytes(), manifest=manifest, manifest_raw_sha256=sha(manifest_raw), custody_receipts=[],
        )


def test_plan_budget_is_unfrozen_without_an_artifact_and_computes_epochs_with_one(tmp_path: Path) -> None:
    export_path, receipt_path, payloads, manifest, manifest_raw = _staged_manifest(tmp_path)
    coverage = MODULE.build_coverage_receipt(
        export_raw=export_path.read_bytes(), manifest=manifest, manifest_raw_sha256=sha(manifest_raw),
        custody_receipts=[(receipt_path, receipt_path.read_bytes())],
    )
    authority = tmp_path / "EMBER-02.md"
    authority.write_text(AUTHORITY_TEXT, encoding="utf-8")
    coverage_raw = json.dumps(coverage, sort_keys=True).encode()
    unfrozen = MODULE.build_budget_receipt(
        coverage=coverage, coverage_raw_sha256=sha(coverage_raw), authority_path=authority,
        authority_raw=authority.read_bytes(), frozen_budget=None, frozen_budget_raw_sha256=None,
    )
    assert unfrozen["status"] == "UNFROZEN" and unfrozen["budget_tokens"] is None and unfrozen["epochs_required"] is None
    assert unfrozen["authority"]["clause_index"] == 17 and unfrozen["authority"]["clause_text"].startswith("17. Freeze")
    assert unfrozen["authority"]["raw_sha256"] == sha(authority.read_bytes())
    staged_tokens = sum(len(raw) for raw in payloads)
    frozen = {"budget_tokens": staged_tokens * 3 + 1, "minimum_token_floor": staged_tokens, "source": "test"}
    frozen_raw = json.dumps(frozen).encode()
    bound = MODULE.build_budget_receipt(
        coverage=coverage, coverage_raw_sha256=sha(coverage_raw), authority_path=authority,
        authority_raw=authority.read_bytes(), frozen_budget=frozen, frozen_budget_raw_sha256=sha(frozen_raw),
    )
    assert bound["status"] == "FROZEN" and bound["epochs_required"]["over_staged"] == 4
    assert bound["shortfall_tokens"]["over_staged"] == staged_tokens * 2 + 1
    with pytest.raises(MODULE.StreamError, match="BUDGET_CLAUSE_MISSING_REFUSED:17"):
        MODULE.build_budget_receipt(
            coverage=coverage, coverage_raw_sha256=sha(coverage_raw), authority_path=authority,
            authority_raw=b"# EMBER-02\n17. no such clause here\n", frozen_budget=None, frozen_budget_raw_sha256=None,
        )


# --------------------------------------------------------------------------- produce (#2135)
def _filled_stream(tmp_path: Path, *, shard_tokens: int, shard_count: int):
    tokenizer_path, tokenizer_sha = write_tokenizer(tmp_path)
    export_path, receipt_path, payloads = build_fixture(tmp_path)
    export = json.loads(export_path.read_bytes())
    for row in export["records"]:
        if row.get("kind") == "membership":
            row["tokenizer_sha256"] = tokenizer_sha
    export_path.write_bytes(json.dumps(export).encode())
    manifest = MODULE.build_staging_manifest(
        export_raw=export_path.read_bytes(), dataset_ids=None, tokenizer_sha256=tokenizer_sha,
        custody_receipts=[(receipt_path, receipt_path.read_bytes())],
    )
    manifest_raw = json.dumps(manifest, sort_keys=True).encode()
    stream_receipt_path, stream_receipt = MODULE.fill_shards(
        manifest=manifest, manifest_raw_sha256=sha(manifest_raw), tokenizer_path=tokenizer_path,
        cache_root=tmp_path / "cache", shard_tokens=shard_tokens, shard_count=shard_count,
    )
    spans_doc = json.loads((stream_receipt_path.parent / f"object-spans-k{shard_count}-s{shard_tokens}.json").read_bytes())
    return tokenizer_path, manifest, stream_receipt_path, stream_receipt, spans_doc, payloads


def test_produce_extends_the_ledger_past_the_immutable_receipt_and_is_idempotent(tmp_path: Path) -> None:
    tokenizer_path, manifest, receipt_path, receipt, spans_doc, payloads = _filled_stream(tmp_path, shard_tokens=2, shard_count=2)
    receipt_raw_before = receipt_path.read_bytes()
    assert receipt["total_stream_tokens"] == 4  # 13 tokens staged; the receipt covers the first two shards of 2
    ledger, rows, produced = MODULE.produce_shards(
        manifest=manifest, receipt_path=receipt_path, receipt=receipt, receipt_spans=spans_doc["spans"],
        tokenizer_path=tokenizer_path, shard_tokens=2, target_shards=7,
    )
    assert receipt_path.read_bytes() == receipt_raw_before, "the stream receipt must never be rewritten"
    # 13 tokens = 2 receipt shards + 4 full ledger shards + 1 partial shard of 1 token, then exhaustion
    assert produced == 5 and len(rows) == 7
    assert [row["n_tokens"] for row in rows] == [2, 2, 2, 2, 2, 2, 1]
    assert rows[-1]["staged_objects_exhausted"] is True and not rows[-2]["staged_objects_exhausted"]
    assert rows[:2] == MODULE.read_shard_ledger(ledger)[:2]
    MODULE.verify_ledger_genesis(rows, receipt)
    MODULE.verify_ledger_shards(receipt_path.parent, rows)
    # The extended stream is byte-identical to a one-shot fill of the whole corpus.
    frozen, _ = MODULE.load_frozen_tokenizer(tokenizer_path, manifest["tokenizer_sha256"])
    expected: list[int] = []
    for raw in sorted(payloads, key=sha):
        expected.extend(frozen.encode(raw.decode(), add_special_tokens=False).ids + [0])
    produced_tokens: list[int] = []
    for row in rows:
        chunk = (receipt_path.parent / row["name"]).read_bytes()
        produced_tokens.extend(struct.unpack(f"<{len(chunk) // 2}H", chunk))
    assert produced_tokens == expected
    # Spans over receipt + ledger are contiguous and total the corpus.
    spans = MODULE.extended_spans(spans_doc["spans"], rows, len(receipt["shards"]))
    assert spans[0]["token_start"] == 0 and spans[-1]["token_end"] == 13
    assert all(spans[i]["token_end"] == spans[i + 1]["token_start"] for i in range(len(spans) - 1))
    assert [span["sha256"] for span in spans] == [sha(raw) for raw in sorted(payloads, key=sha)]
    # Idempotent: a second call with the same target produces nothing and changes no row.
    ledger_raw = ledger.read_bytes()
    _, again, produced_again = MODULE.produce_shards(
        manifest=manifest, receipt_path=receipt_path, receipt=receipt, receipt_spans=spans_doc["spans"],
        tokenizer_path=tokenizer_path, shard_tokens=2, target_shards=9,
    )
    assert produced_again == 0 and again == rows and ledger.read_bytes() == ledger_raw
    # The loader still opens the untouched receipt exactly as before.
    stream = SEMANTIC_MODULE.ManifestBoundTokenStream.from_receipt(receipt_path=receipt_path, shards_root=receipt_path.parent, tokenizer_path=tokenizer_path)
    assert stream.receipt_sha256 == sha(receipt_raw_before)


def test_produce_refuses_a_broken_chain_and_regenerates_only_identical_bytes(tmp_path: Path) -> None:
    tokenizer_path, manifest, receipt_path, receipt, spans_doc, _ = _filled_stream(tmp_path, shard_tokens=2, shard_count=2)
    ledger, rows, _ = MODULE.produce_shards(
        manifest=manifest, receipt_path=receipt_path, receipt=receipt, receipt_spans=spans_doc["spans"],
        tokenizer_path=tokenizer_path, shard_tokens=2, target_shards=4,
    )
    # A deleted ledger shard refuses by default and is regenerated byte-identically on request.
    victim = receipt_path.parent / rows[3]["name"]
    original = victim.read_bytes()
    victim.unlink()
    with pytest.raises(MODULE.StreamError, match=f"SHARD_LEDGER_BYTES_REFUSED:{rows[3]['name']}"):
        MODULE.produce_shards(manifest=manifest, receipt_path=receipt_path, receipt=receipt, receipt_spans=spans_doc["spans"], tokenizer_path=tokenizer_path, shard_tokens=2, target_shards=4)
    MODULE.produce_shards(manifest=manifest, receipt_path=receipt_path, receipt=receipt, receipt_spans=spans_doc["spans"], tokenizer_path=tokenizer_path, shard_tokens=2, target_shards=4, regenerate=True)
    assert victim.read_bytes() == original
    # A receipt shard is never regenerated by the producer (the receipt's own custody rule owns it).
    genesis_file = receipt_path.parent / rows[0]["name"]
    genesis_file.write_bytes(genesis_file.read_bytes()[:-1] + b"\x7f")
    with pytest.raises(MODULE.StreamError, match="RECEIPT_SHARD_REGENERATION_REFUSED"):
        MODULE.produce_shards(manifest=manifest, receipt_path=receipt_path, receipt=receipt, receipt_spans=spans_doc["spans"], tokenizer_path=tokenizer_path, shard_tokens=2, target_shards=4, regenerate=True)
    # A tampered ledger row breaks the chain for every reader.
    lines = ledger.read_bytes().split(b"\n")
    row = json.loads(lines[2]); row["n_tokens"] = 1; lines[2] = json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
    ledger.write_bytes(b"\n".join(lines))
    with pytest.raises(MODULE.StreamError, match="SHARD_LEDGER_ROW_HASH_REFUSED:2"):
        MODULE.read_shard_ledger(ledger)
    # A second producer holding the lock refuses instead of racing.
    ledger.write_bytes(b"\n".join(lines[:2]) + b"\n")
    lock = receipt_path.parent / "shard-ledger-s2.lock"
    lock.mkdir()
    with pytest.raises(MODULE.StreamError, match="SHARD_LEDGER_LOCKED_REFUSED"):
        MODULE.produce_shards(manifest=manifest, receipt_path=receipt_path, receipt=receipt, receipt_spans=spans_doc["spans"], tokenizer_path=tokenizer_path, shard_tokens=2, target_shards=4)
    lock.rmdir()
