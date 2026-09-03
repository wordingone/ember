# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Closed step-2 realization registry admission regressions."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
import sys
sys.path.insert(0, str(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"))

from step2_realization_registry import (
    validate_step2_realization_registry_bundle,
    validate_step2_realization_receipt,
    write_step2_realization_registry,
)


class Step2RealizationRegistryTests(unittest.TestCase):
    def test_runtime_bundle_binds_the_exact_checkpoint_manifest_and_realization(self) -> None:
        """A portable historical verifier is usable only for its exact checkpoint bytes."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = root / "checkpoint"
            checkpoint.mkdir()
            current_config = ROOT / "configs" / "ember-restart-3b.json"
            historical_config = root / "historical-config.json"
            historical_payload = json.loads(current_config.read_bytes())
            historical_payload["training"]["gpu"]["gpu_hours_cap"] = 999
            historical_config.write_text(json.dumps(historical_payload, sort_keys=True), encoding="utf-8")
            historical_config_sha256 = hashlib.sha256(historical_config.read_bytes()).hexdigest()
            counts = {
                "allocated_parameters": 3_839_161_856,
                "unique_parameters": 3_839_161_856,
                "trainable_parameters": 3_839_161_856,
                "served_parameters": 3_839_161_856,
                "active_parameters": 1_020_589_568,
                "episode_trainable_parameters": 1_020_589_568,
            }
            genesis = {name: hashlib.sha256(name.encode("utf-8")).hexdigest() for name in ("vision", "audio", "reasoning", "tool")}
            manifest = {
                "schema_version": "ember-sparse-checkpoint-v3",
                "model_config_sha256": historical_config_sha256,
                "architecture_revision": "ember-sparse-3b-v2",
                "active_expert_ids": ["shared"],
                "architecture": dict(counts),
                "expert_genesis_sha256": genesis,
                "expert_parameter_sha256": genesis,
            }
            manifest_path = checkpoint / "checkpoint-manifest.json"
            manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
            subject = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            source_counter = root / "source-counter.py"
            source_counter.write_text("# reviewed historical counter bytes\n", encoding="utf-8")
            counter_sha256 = hashlib.sha256(source_counter.read_bytes()).hexdigest()
            source_receipt = root / "source-receipt.json"
            source_receipt.write_text(json.dumps({
                "schema_version": "ember-sparse-realization-receipt-v1",
                "verification_boundary": "VERIFIED_MEASURED",
                "result": "MEASURED",
                "subject_checkpoint_sha256": subject,
                "model_config_sha256": manifest["model_config_sha256"],
                "counter_sha256": counter_sha256,
                "architecture_revision": manifest["architecture_revision"],
                "active_expert_ids": manifest["active_expert_ids"],
                **counts,
                "expert_genesis_sha256": genesis,
                "expert_parameter_sha256": genesis,
            }, sort_keys=True), encoding="utf-8")
            registry = write_step2_realization_registry(
                root / "registry", receipt_path=source_receipt, counter_path=source_counter,
                model_config_path=historical_config,
            )

            admitted = validate_step2_realization_registry_bundle(registry, manifest_path, current_config)
            self.assertEqual(admitted["subject_checkpoint_sha256"], subject)
            self.assertNotEqual(admitted["historical_model_config_sha256"], admitted["current_model_config_sha256"])
            self.assertEqual(admitted["semantic_model_contract_sha256"], "42b32f11e267dcdb581351c82dcddf7c55dbec7f48b544b4025ede16da86d23e")
            registry_payload = json.loads(registry.read_bytes())
            registry_payload["verifiers"][0]["unreviewed_authority"] = True
            registry.write_text(json.dumps(registry_payload, sort_keys=True), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "entries must be closed"):
                validate_step2_realization_registry_bundle(registry, manifest_path, current_config)
            del registry_payload["verifiers"][0]["unreviewed_authority"]
            registry.write_text(json.dumps(registry_payload, sort_keys=True), encoding="utf-8")
            manifest["expert_parameter_sha256"]["vision"] = "f" * 64
            manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "receipt binding|checkpoint manifest"):
                validate_step2_realization_registry_bundle(registry, manifest_path, current_config)

    def test_writer_builds_a_portable_exact_counter_and_receipt_bundle(self) -> None:
        """Runtime trust starts from one self-contained, content-addressed bundle."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_counter = root / "source-counter.py"
            source_counter.write_text("# reviewed counter bytes\n", encoding="utf-8")
            counter_sha256 = hashlib.sha256(source_counter.read_bytes()).hexdigest()
            subject, config = "b" * 64, "5" * 64
            source_receipt = root / "source-receipt.json"
            source_receipt.write_text(json.dumps({
                "schema_version": "ember-sparse-realization-receipt-v1",
                "verification_boundary": "VERIFIED_MEASURED",
                "result": "MEASURED",
                "subject_checkpoint_sha256": subject,
                "model_config_sha256": config,
                "counter_sha256": counter_sha256,
                "architecture_revision": "ember-sparse-3b-v2",
                "active_expert_ids": ["shared"],
                **{"allocated_parameters": 3839161856, "unique_parameters": 3839161856,
                   "trainable_parameters": 3839161856, "served_parameters": 3839161856,
                   "active_parameters": 1020589568, "episode_trainable_parameters": 1020589568},
                "expert_genesis_sha256": {name: "a" * 64 for name in ("vision", "audio", "reasoning", "tool")},
                "expert_parameter_sha256": {name: "a" * 64 for name in ("vision", "audio", "reasoning", "tool")},
            }, sort_keys=True), encoding="utf-8")

            bundle = root / "step2-registry"
            write_step2_realization_registry(
                bundle, receipt_path=source_receipt, counter_path=source_counter,
            )

            registry = json.loads((bundle / "trusted-verifiers.json").read_text(encoding="utf-8"))
            self.assertEqual(registry["verifiers"][0]["path"], "parameter_counter.py")
            self.assertEqual(registry["realization_receipts"][0]["path"], "step2-realization-receipt.json")
            self.assertEqual((bundle / "parameter_counter.py").read_bytes(), source_counter.read_bytes())
            self.assertEqual((bundle / "step2-realization-receipt.json").read_bytes(), source_receipt.read_bytes())
            admitted = validate_step2_realization_receipt(
                bundle / "step2-realization-receipt.json", bundle / "trusted-verifiers.json",
                subject_checkpoint_sha256=subject, model_config_sha256=config,
                counter_path=bundle / "parameter_counter.py",
            )
            self.assertEqual(admitted["subject_checkpoint_sha256"], subject)
            with self.assertRaisesRegex(FileExistsError, "already exists"):
                write_step2_realization_registry(
                    bundle, receipt_path=source_receipt, counter_path=source_counter,
                )

    def test_registry_rejects_receipt_binding_that_escapes_registry_root(self) -> None:
        """Receipt custody must be bundle-relative, not a matching external path."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry_root = root / "registry"
            registry_root.mkdir()
            counter = registry_root / "parameter_counter.py"
            counter.write_text("# exact reviewed counter bytes\n", encoding="utf-8")
            counter_sha256 = hashlib.sha256(counter.read_bytes()).hexdigest()
            subject, config = "b" * 64, "5" * 64
            receipt = root / "receipt.json"
            payload = {"schema_version": "ember-sparse-realization-receipt-v1", "verification_boundary": "VERIFIED_MEASURED", "result": "MEASURED", "subject_checkpoint_sha256": subject, "model_config_sha256": config, "counter_sha256": counter_sha256, "architecture_revision": "ember-sparse-3b-v2", "active_expert_ids": ["shared"], "allocated_parameters": 3839161856, "unique_parameters": 3839161856, "trainable_parameters": 3839161856, "served_parameters": 3839161856, "active_parameters": 1020589568, "episode_trainable_parameters": 1020589568, "expert_genesis_sha256": {name: "a" * 64 for name in ("vision", "audio", "reasoning", "tool")}, "expert_parameter_sha256": {name: "a" * 64 for name in ("vision", "audio", "reasoning", "tool")}}
            receipt.write_text(json.dumps(payload), encoding="utf-8")
            registry = registry_root / "trusted-verifiers.json"
            registry.write_text(json.dumps({"schema_version": "ember-trusted-verifiers-v1", "verifiers": [{"path": "parameter_counter.py", "sha256": counter_sha256, "evidence_classes": ["parameter_realization"], "criterion_ids": ["ember-sparse-step2-realization-v1"]}], "realization_receipts": [{"path": "../receipt.json", "sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(), "subject_checkpoint_sha256": subject, "model_config_sha256": config, "counter_sha256": counter_sha256, "active_expert": "shared"}]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "receipt binding"):
                validate_step2_realization_receipt(receipt, registry, subject_checkpoint_sha256=subject, model_config_sha256=config, counter_path=counter)
    def test_registry_requires_a_content_addressed_receipt_binding(self) -> None:
        """A trusted counter source alone cannot authorize an arbitrary receipt."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            counter = root / "parameter_counter.py"
            counter.write_text("# exact reviewed counter bytes\n", encoding="utf-8")
            counter_sha256 = hashlib.sha256(counter.read_bytes()).hexdigest()
            subject, config = "b" * 64, "5" * 64
            receipt = root / "receipt.json"
            receipt.write_text(json.dumps({"schema_version": "ember-sparse-realization-receipt-v1", "verification_boundary": "VERIFIED_MEASURED", "result": "MEASURED", "subject_checkpoint_sha256": subject, "model_config_sha256": config, "counter_sha256": counter_sha256, "architecture_revision": "ember-sparse-3b-v2", "active_expert_ids": ["shared"], **{"allocated_parameters": 3839161856, "unique_parameters": 3839161856, "trainable_parameters": 3839161856, "served_parameters": 3839161856, "active_parameters": 1020589568, "episode_trainable_parameters": 1020589568}, "expert_genesis_sha256": {name: "a" * 64 for name in ("vision", "audio", "reasoning", "tool")}, "expert_parameter_sha256": {name: "a" * 64 for name in ("vision", "audio", "reasoning", "tool")}}), encoding="utf-8")
            registry = root / "trusted-verifiers.json"
            receipt_sha256 = hashlib.sha256(receipt.read_bytes()).hexdigest()
            registry.write_text(json.dumps({"schema_version": "ember-trusted-verifiers-v1", "verifiers": [{"path": "parameter_counter.py", "sha256": counter_sha256, "evidence_classes": ["parameter_realization"], "criterion_ids": ["ember-sparse-step2-realization-v1"]}]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "receipt binding"):
                validate_step2_realization_receipt(receipt, registry, subject_checkpoint_sha256=subject, model_config_sha256=config, counter_path=counter)
    def test_registry_admits_only_the_exact_trusted_counter_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            counter = root / "parameter_counter.py"
            counter.write_text("# exact reviewed counter bytes\n", encoding="utf-8")
            counter_sha256 = hashlib.sha256(counter.read_bytes()).hexdigest()
            receipt = root / "receipt.json"
            subject = "b" * 64
            config = "5" * 64
            receipt.write_text(json.dumps({
                "schema_version": "ember-sparse-realization-receipt-v1",
                "verification_boundary": "VERIFIED_MEASURED",
                "result": "MEASURED",
                "subject_checkpoint_sha256": subject,
                "model_config_sha256": config,
                "counter_sha256": counter_sha256,
                "architecture_revision": "ember-sparse-3b-v2",
                "active_expert_ids": ["shared"],
                "allocated_parameters": 3839161856,
                "unique_parameters": 3839161856,
                "trainable_parameters": 3839161856,
                "served_parameters": 3839161856,
                "active_parameters": 1020589568,
                "episode_trainable_parameters": 1020589568,
                "expert_genesis_sha256": {name: "a" * 64 for name in ("vision", "audio", "reasoning", "tool")},
                "expert_parameter_sha256": {name: "a" * 64 for name in ("vision", "audio", "reasoning", "tool")},
            }, sort_keys=True), encoding="utf-8")
            registry = root / "trusted-verifiers.json"
            receipt_sha256 = hashlib.sha256(receipt.read_bytes()).hexdigest()
            registry.write_text(json.dumps({"schema_version": "ember-trusted-verifiers-v1", "verifiers": [{"path": "parameter_counter.py", "sha256": counter_sha256, "evidence_classes": ["parameter_realization"], "criterion_ids": ["ember-sparse-step2-realization-v1"]}], "realization_receipts": [{"path": "receipt.json", "sha256": receipt_sha256, "subject_checkpoint_sha256": subject, "model_config_sha256": config, "counter_sha256": counter_sha256, "active_expert": "shared"}]}), encoding="utf-8")
            admitted = validate_step2_realization_receipt(receipt, registry, subject_checkpoint_sha256=subject, model_config_sha256=config, counter_path=counter)
        self.assertEqual(admitted["counter_sha256"], counter_sha256)
        self.assertEqual(admitted["subject_checkpoint_sha256"], subject)


if __name__ == "__main__":
    unittest.main()
