# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed admission tests for genuine specialist training manifests."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from domain_manifest import load_domain_training_manifest


class DomainTrainingManifestTests(unittest.TestCase):
    def test_retired_bootstrap_manifest_is_not_a_domain_training_admission(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "ember-owned-domain-training-manifest-v1",
                        "artifact_id": "owned-clean-curriculum-128-v1",
                        "shard_path": "data/ember-restart-3b/owned-curriculum-128.json",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "retired bootstrap"):
                load_domain_training_manifest(manifest_path=manifest, repo_root=root)


    def test_nonbootstrap_manifest_must_bind_all_four_specialists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "ember-owned-domain-training-manifest-v1",
                        "artifact_id": "owned-captured-domain-v1",
                        "shard_path": "data/ember-restart-3b/captured-domain-v1.json",
                        "domains": [],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "all four specialists"):
                load_domain_training_manifest(manifest_path=manifest, repo_root=root)


    def test_each_specialist_requires_content_addressed_shard_and_source_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "ember-owned-domain-training-manifest-v1",
                        "artifact_id": "owned-captured-domain-v1",
                        "shard_path": "data/ember-restart-3b/captured-domain-v1.json",
                        "domains": [{"expert": expert} for expert in ("vision", "audio", "reasoning", "tool")],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "content-addressed shard"):
                load_domain_training_manifest(manifest_path=manifest, repo_root=root)


    def test_domain_shard_hash_must_match_the_bound_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"; data.mkdir()
            receipts = root / "receipts"; receipts.mkdir()
            shard = data / "owned-capture.json"; shard.write_bytes(b"captured bytes")
            receipt = receipts / "source.json"; receipt.write_bytes(b"source receipt")
            shard_hash = hashlib.sha256(shard.read_bytes()).hexdigest()
            receipt_hash = hashlib.sha256(receipt.read_bytes()).hexdigest()
            manifest = root / "manifest.json"
            domains = [
                {
                    "expert": expert,
                    "shard_path": "data/owned-capture.json",
                    "shard_sha256": shard_hash,
                    "source_receipt_path": "receipts/source.json",
                    "source_receipt_sha256": receipt_hash,
                }
                for expert in ("vision", "audio", "reasoning", "tool")
            ]
            domains[0]["shard_sha256"] = "0" * 64
            manifest.write_text(json.dumps({"schema_version": "ember-owned-domain-training-manifest-v1", "artifact_id": "owned-captured-domain-v1", "shard_path": "data/owned-capture.json", "domains": domains}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "shard bytes"):
                load_domain_training_manifest(manifest_path=manifest, repo_root=root)


    def test_source_receipt_rejects_generated_labels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"; data.mkdir()
            receipts = root / "receipts"; receipts.mkdir()
            shard = data / "capture.json"; shard.write_bytes(b"captured domain bytes")
            source_payload = {"schema_version": "ember-owned-domain-source-receipt-v1", "result": "VERIFIED", "provenance": {"generated_labels": True, "borrowed_model_outputs": False, "teacher_outputs": False}}
            source = receipts / "source.json"; source.write_text(json.dumps(source_payload), encoding="utf-8")
            shard_hash = hashlib.sha256(shard.read_bytes()).hexdigest()
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            domains = [{"expert": expert, "shard_path": "data/capture.json", "shard_sha256": shard_hash, "source_receipt_path": "receipts/source.json", "source_receipt_sha256": source_hash} for expert in ("vision", "audio", "reasoning", "tool")]
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"schema_version": "ember-owned-domain-training-manifest-v1", "artifact_id": "owned-captured-domain-v1", "shard_path": "data/capture.json", "domains": domains}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "generated labels"):
                load_domain_training_manifest(manifest_path=manifest, repo_root=root)


if __name__ == "__main__":
    unittest.main()
