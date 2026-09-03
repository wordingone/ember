# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Focused #648 source-inventory bridge tests."""

from __future__ import annotations

import hashlib
import json
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.ember.infrastructure.tools.corpus_connectors import receipt as connector_receipt
from source_inventory import load_authorized_source_inventory, reopen_authorized_source_inventory


def _fixture(root: Path) -> Path:
    shard = root / "raw" / "arxiv" / "abstracts.jsonl"
    shard.parent.mkdir(parents=True)
    shard.write_bytes(b'{"id":"a1","text":"owned fixture"}\n')
    digest = hashlib.sha256(shard.read_bytes()).hexdigest()
    receipt = root / "receipts" / "arxiv.json"
    receipt.parent.mkdir(parents=True)
    canonical = connector_receipt.Receipt(
        source="fixture",
        source_id="arxiv-abstracts",
        canonical_url="https://example.invalid/arxiv-abstracts",
        license="CC-BY-4.0",
        license_evidence="fixture license record",
        revision="fixture-r1",
        files=[connector_receipt.FileEntry(path=shard.name, bytes=shard.stat().st_size, sha256=digest)],
        fetched_at="2026-08-09T00:00:00Z",
        connector=connector_receipt.ConnectorInfo(name="fixture-connector"),
        dest_root=str(shard.parent),
        notes="human-provenance: fixture license record",
    )
    receipt.write_text(json.dumps(canonical.to_dict(), sort_keys=True), encoding="utf-8")
    manifest = root / "source-inventory.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "ember-authorized-source-inventory-v1",
                "sources": [
                    {
                        "source_id": "arxiv-abstracts",
                        "domain": "I",
                        "raw_path": "raw/arxiv/abstracts.jsonl",
                        "raw_sha256": digest,
                        "receipt_path": "receipts/arxiv.json",
                        "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_authorized_inventory_round_trips_and_rejects_license_tamper() -> None:
    with tempfile.TemporaryDirectory(prefix="issue648-source-inventory-") as directory:
        root = Path(directory)
        manifest = _fixture(root)
        loaded = load_authorized_source_inventory(manifest_path=manifest, custody_root=root)
        assert loaded["schema_version"] == "ember-authorized-source-inventory-v1"
        assert reopen_authorized_source_inventory(manifest_path=manifest, custody_root=root) == loaded
        receipt = root / "receipts" / "arxiv.json"
        payload = json.loads(receipt.read_text(encoding="utf-8"))
        payload["license"] = "UNSPECIFIED"
        receipt.write_text(json.dumps(payload), encoding="utf-8")
        manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
        manifest_payload["sources"][0]["receipt_sha256"] = hashlib.sha256(receipt.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
        try:
            load_authorized_source_inventory(manifest_path=manifest, custody_root=root)
        except ValueError as error:
            assert "license" in str(error)
        else:
            raise AssertionError("tampered license must refuse before import")


def test_rejects_missing_receipt_and_raw_hash_tamper() -> None:
    with tempfile.TemporaryDirectory(prefix="issue648-source-inventory-") as directory:
        root = Path(directory)
        manifest = _fixture(root)
        receipt = root / "receipts" / "arxiv.json"
        receipt.unlink()
        try:
            load_authorized_source_inventory(manifest_path=manifest, custody_root=root)
        except ValueError as error:
            assert "receipt_path" in str(error) or "missing" in str(error)
        else:
            raise AssertionError("missing receipt must refuse")
    with tempfile.TemporaryDirectory(prefix="issue648-source-inventory-") as directory:
        root = Path(directory)
        manifest = _fixture(root)
        raw = root / "raw" / "arxiv" / "abstracts.jsonl"
        raw.write_bytes(raw.read_bytes() + b"tamper\n")
        try:
            load_authorized_source_inventory(manifest_path=manifest, custody_root=root)
        except ValueError as error:
            assert "raw source bytes" in str(error)
        else:
            raise AssertionError("raw-byte tamper must refuse")


def test_rejects_foreign_path_and_nondeterministic_rows() -> None:
    with tempfile.TemporaryDirectory(prefix="issue648-source-inventory-") as directory:
        root = Path(directory)
        manifest = _fixture(root)
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["sources"][0]["raw_path"] = "../outside.jsonl"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        try:
            load_authorized_source_inventory(manifest_path=manifest, custody_root=root)
        except ValueError as error:
            assert "escapes" in str(error) or "normalized" in str(error)
        else:
            raise AssertionError("foreign raw path must refuse")

    with tempfile.TemporaryDirectory(prefix="issue648-source-inventory-") as directory:
        root = Path(directory)
        manifest = _fixture(root)
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        original = payload["sources"][0]
        foreign_raw = root / "raw" / "foreign" / "abstracts.jsonl"
        foreign_raw.parent.mkdir(parents=True)
        foreign_raw.write_bytes((root / original["raw_path"]).read_bytes())
        receipt = root / original["receipt_path"]
        receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
        receipt_payload["dest_root"] = str(foreign_raw.parent)
        receipt.write_text(json.dumps(receipt_payload, sort_keys=True), encoding="utf-8")
        original["receipt_sha256"] = hashlib.sha256(receipt.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        try:
            load_authorized_source_inventory(manifest_path=manifest, custody_root=root)
        except ValueError as error:
            assert "file identity" in str(error)
        else:
            raise AssertionError("same bytes under a foreign receipt path must refuse")

    with tempfile.TemporaryDirectory(prefix="issue648-source-inventory-") as directory:
        root = Path(directory)
        manifest = _fixture(root)
        receipt = root / "receipts" / "arxiv.json"
        receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
        receipt_payload["notes"] = "model-generated bytes with an allowed CC-BY license"
        receipt.write_text(json.dumps(receipt_payload, sort_keys=True), encoding="utf-8")
        manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
        manifest_payload["sources"][0]["receipt_sha256"] = hashlib.sha256(receipt.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
        try:
            load_authorized_source_inventory(manifest_path=manifest, custody_root=root)
        except ValueError as error:
            assert "license/source identity" in str(error) or "provenance" in str(error)
        else:
            raise AssertionError("model-derived provenance must refuse even with an allowed license")

    with tempfile.TemporaryDirectory(prefix="issue648-source-inventory-") as directory:
        root = Path(directory)
        manifest = _fixture(root)
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        extra_raw = root / "raw" / "courtlistener" / "opinions.jsonl"
        extra_raw.parent.mkdir(parents=True)
        extra_raw.write_bytes(b'{"id":"c1"}\n')
        extra_digest = hashlib.sha256(extra_raw.read_bytes()).hexdigest()
        extra_receipt = root / "receipts" / "courtlistener.json"
        extra_receipt_payload = json.loads((root / "receipts" / "arxiv.json").read_text(encoding="utf-8"))
        extra_receipt_payload.update(
            {
                "source_id": "courtlistener",
                "canonical_url": "https://example.invalid/courtlistener",
                "files": [{"path": "opinions.jsonl", "bytes": extra_raw.stat().st_size, "sha256": extra_digest}],
                "total_bytes": extra_raw.stat().st_size,
                "sha256_manifest": connector_receipt.sha256_of_manifest([extra_digest]),
                "dest_root": str(extra_raw.parent),
            }
        )
        extra_receipt.write_text(json.dumps(extra_receipt_payload, sort_keys=True), encoding="utf-8")
        payload["sources"].append(
            {
                "source_id": "courtlistener",
                "domain": "I",
                "raw_path": "raw/courtlistener/opinions.jsonl",
                "raw_sha256": extra_digest,
                "receipt_path": "receipts/courtlistener.json",
                "receipt_sha256": hashlib.sha256(extra_receipt.read_bytes()).hexdigest(),
            }
        )
        payload["sources"] = list(reversed(payload["sources"]))
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        try:
            load_authorized_source_inventory(manifest_path=manifest, custody_root=root)
        except ValueError as error:
            assert "deterministically ordered" in str(error)
        else:
            raise AssertionError("unsorted source rows must refuse")


def test_rejects_noncommercial_license_even_when_hashes_are_recomputed() -> None:
    with tempfile.TemporaryDirectory(prefix="issue648-source-inventory-") as directory:
        root = Path(directory)
        manifest = _fixture(root)
        receipt = root / "receipts" / "arxiv.json"
        payload = json.loads(receipt.read_text(encoding="utf-8"))
        payload["license"] = "CC-BY-NC-4.0"
        receipt.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
        manifest_payload["sources"][0]["receipt_sha256"] = hashlib.sha256(receipt.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
        try:
            load_authorized_source_inventory(manifest_path=manifest, custody_root=root)
        except ValueError as error:
            assert "license" in str(error)
        else:
            raise AssertionError("noncommercial sources must remain outside the admitted license set")
