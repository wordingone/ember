# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed admission tests for genuine specialist training manifests."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"))
sys.path.insert(0, str(ROOT / "tools" / "corpus_connectors"))

from domain_manifest import load_domain_training_manifest
# issue2015 exact-local-import:src/ember/infrastructure/tools/corpus_connectors/receipt.py
import importlib.util as _ember_0b714f516abcfc7c_importlib
import sys as _ember_0b714f516abcfc7c_sys
from pathlib import Path as _ember_0b714f516abcfc7c_Path
_ember_0b714f516abcfc7c_path = _ember_0b714f516abcfc7c_Path(__file__).resolve().parents[3].joinpath('src', 'ember', 'infrastructure', 'tools', 'corpus_connectors', 'receipt.py')
if not _ember_0b714f516abcfc7c_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/infrastructure/tools/corpus_connectors/receipt.py')
_ember_0b714f516abcfc7c_aliases = ('_ember_issue2015_0b714f516abcfc7c', 'receipt', 'src.ember.infrastructure.tools.corpus_connectors.receipt', 'tools.corpus_connectors.receipt')
_ember_0b714f516abcfc7c_existing = []
for _ember_0b714f516abcfc7c_alias in _ember_0b714f516abcfc7c_aliases:
    _ember_0b714f516abcfc7c_candidate = _ember_0b714f516abcfc7c_sys.modules.get(_ember_0b714f516abcfc7c_alias)
    if _ember_0b714f516abcfc7c_candidate is not None and all(_ember_0b714f516abcfc7c_candidate is not item for item in _ember_0b714f516abcfc7c_existing):
        _ember_0b714f516abcfc7c_existing.append(_ember_0b714f516abcfc7c_candidate)
if len(_ember_0b714f516abcfc7c_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/infrastructure/tools/corpus_connectors/receipt.py')
if _ember_0b714f516abcfc7c_existing:
    _ember_0b714f516abcfc7c_module = _ember_0b714f516abcfc7c_existing[0]
    _ember_0b714f516abcfc7c_observed = getattr(_ember_0b714f516abcfc7c_module, '__file__', None)
    if _ember_0b714f516abcfc7c_observed is None or _ember_0b714f516abcfc7c_Path(_ember_0b714f516abcfc7c_observed).resolve() != _ember_0b714f516abcfc7c_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/infrastructure/tools/corpus_connectors/receipt.py')
else:
    _ember_0b714f516abcfc7c_spec = _ember_0b714f516abcfc7c_importlib.spec_from_file_location('_ember_issue2015_0b714f516abcfc7c', _ember_0b714f516abcfc7c_path)
    if _ember_0b714f516abcfc7c_spec is None or _ember_0b714f516abcfc7c_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/infrastructure/tools/corpus_connectors/receipt.py')
    _ember_0b714f516abcfc7c_module = _ember_0b714f516abcfc7c_importlib.module_from_spec(_ember_0b714f516abcfc7c_spec)
    for _ember_0b714f516abcfc7c_alias in _ember_0b714f516abcfc7c_aliases:
        _ember_0b714f516abcfc7c_prior = _ember_0b714f516abcfc7c_sys.modules.get(_ember_0b714f516abcfc7c_alias)
        if _ember_0b714f516abcfc7c_prior is not None and _ember_0b714f516abcfc7c_prior is not _ember_0b714f516abcfc7c_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/corpus_connectors/receipt.py')
        _ember_0b714f516abcfc7c_sys.modules[_ember_0b714f516abcfc7c_alias] = _ember_0b714f516abcfc7c_module
    try:
        _ember_0b714f516abcfc7c_spec.loader.exec_module(_ember_0b714f516abcfc7c_module)
    except BaseException:
        for _ember_0b714f516abcfc7c_alias in _ember_0b714f516abcfc7c_aliases:
            if _ember_0b714f516abcfc7c_sys.modules.get(_ember_0b714f516abcfc7c_alias) is _ember_0b714f516abcfc7c_module:
                _ember_0b714f516abcfc7c_sys.modules.pop(_ember_0b714f516abcfc7c_alias, None)
        raise
for _ember_0b714f516abcfc7c_alias in _ember_0b714f516abcfc7c_aliases:
    _ember_0b714f516abcfc7c_prior = _ember_0b714f516abcfc7c_sys.modules.get(_ember_0b714f516abcfc7c_alias)
    if _ember_0b714f516abcfc7c_prior is not None and _ember_0b714f516abcfc7c_prior is not _ember_0b714f516abcfc7c_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/corpus_connectors/receipt.py')
    _ember_0b714f516abcfc7c_sys.modules[_ember_0b714f516abcfc7c_alias] = _ember_0b714f516abcfc7c_module
ConnectorInfo = getattr(_ember_0b714f516abcfc7c_module, 'ConnectorInfo')
FileEntry = getattr(_ember_0b714f516abcfc7c_module, 'FileEntry')
Receipt = getattr(_ember_0b714f516abcfc7c_module, 'Receipt')
to_manifest_row = getattr(_ember_0b714f516abcfc7c_module, 'to_manifest_row')
# issue2015 exact-local-import-end:src/ember/infrastructure/tools/corpus_connectors/receipt.py


class DomainTrainingManifestTests(unittest.TestCase):
    def test_checked_in_domain_manifest_reopens_with_exact_receipt_and_shard_bindings(self) -> None:
        manifest_path = ROOT / "manifests" / "ember-restart-3b" / "domain-training-manifest-v1.json"
        first = load_domain_training_manifest(manifest_path=manifest_path, repo_root=ROOT)
        second = load_domain_training_manifest(manifest_path=manifest_path, repo_root=ROOT)
        self.assertEqual(first, second)
        self.assertEqual(
            set(first),
            {"schema_version", "artifact_id", "shard_path", "domains"},
        )
        for domain in first["domains"]:
            self.assertEqual(
                set(domain),
                {"expert", "shard_path", "shard_sha256", "source_receipt_path", "source_receipt_sha256"},
            )
            receipt = json.loads((ROOT / domain["source_receipt_path"]).read_text(encoding="utf-8"))
            self.assertEqual(
                set(receipt),
                {
                    "schema_version",
                    "result",
                    "expert",
                    "shard_sha256",
                    "goal_id",
                    "invariant_sha256",
                    "source_url",
                    "sha256",
                    "bytes",
                    "license",
                    "human_provenance_basis",
                    "fetched_ts",
                    "sha_convention",
                    "selection_rule",
                    "provenance",
                    "ticket",
                    "ts",
                    "workstream_id",
                    "next_executed_outcome",
                },
            )

    def test_checked_in_fixture_uses_canonical_connector_manifest_projection(self) -> None:
        manifest_path = ROOT / "manifests" / "ember-restart-3b" / "domain-training-manifest-v1.json"
        payload = load_domain_training_manifest(manifest_path=manifest_path, repo_root=ROOT)
        for domain in payload["domains"]:
            receipt_path = ROOT / domain["source_receipt_path"]
            source = json.loads(receipt_path.read_text(encoding="utf-8"))
            connector_receipt = Receipt(
                source="checked-in-fixture",
                source_id=source["selection_rule"],
                canonical_url=source["source_url"],
                license=source["license"],
                license_evidence=source["human_provenance_basis"],
                revision=None,
                files=[FileEntry(path=domain["shard_path"], bytes=source["bytes"], sha256=source["sha256"])],
                fetched_at=source["fetched_ts"],
                connector=ConnectorInfo(name="checked-in-fixture"),
                dest_root=".",
                notes=source["human_provenance_basis"],
            )
            row = to_manifest_row(connector_receipt)[0]
            self.assertEqual(row["source_url"], source["source_url"])
            self.assertEqual(row["sha256"], domain["shard_sha256"])
            self.assertEqual(row["bytes"], source["bytes"])
            self.assertEqual(row["license"], source["license"])
            self.assertEqual(row["human_provenance_basis"], source["human_provenance_basis"])
            self.assertEqual(row["fetched_ts"], source["fetched_ts"])
            self.assertEqual(row["selection_rule"], source["selection_rule"])

    def test_checked_in_domain_manifest_refuses_tamper_missing_and_foreign_receipts(self) -> None:
        manifest_source = ROOT / "manifests" / "ember-restart-3b" / "domain-training-manifest-v1.json"
        manifest_payload = json.loads(manifest_source.read_text(encoding="utf-8"))

        def copy_fixture(destination: Path) -> Path:
            manifest = destination / "manifest.json"
            manifest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(manifest_source, manifest)
            for domain in manifest_payload["domains"]:
                for key in ("shard_path", "source_receipt_path"):
                    source = ROOT / domain[key]
                    target = destination / domain[key]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
            return manifest

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = copy_fixture(root)
            imported = load_domain_training_manifest(manifest_path=manifest, repo_root=root)
            self.assertEqual(imported, json.loads(manifest.read_text(encoding="utf-8")))
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["domains"][0]["shard_sha256"] = "0" * 64
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "shard bytes"):
                load_domain_training_manifest(manifest_path=manifest, repo_root=root)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = copy_fixture(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            missing = root / payload["domains"][0]["source_receipt_path"]
            missing.unlink()
            with self.assertRaisesRegex(ValueError, "source receipt bytes"):
                load_domain_training_manifest(manifest_path=manifest, repo_root=root)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = copy_fixture(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            receipt_path = root / payload["domains"][0]["source_receipt_path"]
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["expert"] = "vision"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            payload["domains"][0]["source_receipt_sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exact specialist"):
                load_domain_training_manifest(manifest_path=manifest, repo_root=root)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = copy_fixture(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["domains"][0]["source_receipt_path"] = "../foreign-receipt.json"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "escapes the repository root"):
                load_domain_training_manifest(manifest_path=manifest, repo_root=root)

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
            shard_hash = hashlib.sha256(shard.read_bytes()).hexdigest()
            source_payload = {"schema_version": "ember-owned-domain-source-receipt-v1", "result": "VERIFIED", "expert": "vision", "shard_sha256": shard_hash, "goal_id": "EMBER-02", "invariant_sha256": "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6", "source_url": "fixture://test/vision", "sha256": shard_hash, "bytes": shard.stat().st_size, "license": "CC0", "human_provenance_basis": "test fixture", "fetched_ts": "2026-08-09T00:00:00Z", "sha_convention": "sha256 over raw shard bytes on disk; no normalization", "selection_rule": "test/vision", "provenance": {"generated_labels": True, "borrowed_model_outputs": False, "teacher_outputs": False, "model_derived_data": False}, "ticket": "test/vision", "ts": "2026-08-09T00:00:00Z", "workstream_id": "EMBER-02B", "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"}
            source = receipts / "source.json"; source.write_text(json.dumps(source_payload), encoding="utf-8")
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            domains = [{"expert": expert, "shard_path": "data/capture.json", "shard_sha256": shard_hash, "source_receipt_path": "receipts/source.json", "source_receipt_sha256": source_hash} for expert in ("vision", "audio", "reasoning", "tool")]
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"schema_version": "ember-owned-domain-training-manifest-v1", "artifact_id": "owned-captured-domain-v1", "shard_path": "data/capture.json", "domains": domains}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "generated labels"):
                load_domain_training_manifest(manifest_path=manifest, repo_root=root)


    def test_source_receipt_must_bind_its_exact_expert_and_shard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"; data.mkdir()
            receipts = root / "receipts"; receipts.mkdir()
            shard = data / "capture.json"; shard.write_bytes(b"captured domain bytes")
            shard_hash = hashlib.sha256(shard.read_bytes()).hexdigest()
            source_payload = {"schema_version": "ember-owned-domain-source-receipt-v1", "result": "VERIFIED", "expert": "audio", "shard_sha256": shard_hash, "goal_id": "EMBER-02", "invariant_sha256": "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6", "source_url": "fixture://test/audio", "sha256": shard_hash, "bytes": shard.stat().st_size, "license": "CC0", "human_provenance_basis": "test fixture", "fetched_ts": "2026-08-09T00:00:00Z", "sha_convention": "sha256 over raw shard bytes on disk; no normalization", "selection_rule": "test/audio", "provenance": {"generated_labels": False, "borrowed_model_outputs": False, "teacher_outputs": False, "model_derived_data": False}, "ticket": "test/audio", "ts": "2026-08-09T00:00:00Z", "workstream_id": "EMBER-02B", "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"}
            source = receipts / "source.json"; source.write_text(json.dumps(source_payload), encoding="utf-8")
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            domains = [{"expert": expert, "shard_path": "data/capture.json", "shard_sha256": shard_hash, "source_receipt_path": "receipts/source.json", "source_receipt_sha256": source_hash} for expert in ("vision", "audio", "reasoning", "tool")]
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"schema_version": "ember-owned-domain-training-manifest-v1", "artifact_id": "owned-captured-domain-v1", "shard_path": "data/capture.json", "domains": domains}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exact specialist"):
                load_domain_training_manifest(manifest_path=manifest, repo_root=root)


if __name__ == "__main__":
    unittest.main()
