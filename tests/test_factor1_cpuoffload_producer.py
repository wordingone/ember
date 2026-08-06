"""Red/green contract tests for the current-native #764 producer."""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "factor1_cpuoffload_producer",
    ROOT / "scripts" / "factor1_cpuoffload_producer.py",
)
producer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(producer)


class CurrentNativeProducerTests(unittest.TestCase):
    def test_exact_shape_manifest_is_content_bound(self):
        manifest = producer.exact_shape_manifest()
        self.assertEqual(manifest["muon"]["count"], 140)
        self.assertEqual(manifest["muon"]["numel"], 2_097_152_000)
        self.assertEqual(manifest["adamw"]["count"], 44)
        self.assertEqual(manifest["adamw"]["numel"], 196_692_012)
        self.assertRegex(manifest["shape_sha256"], r"^[0-9a-f]{64}$")

    def test_production_smoke_uses_real_offload_and_both_optimizer_classes(self):
        with tempfile.TemporaryDirectory(prefix="factor1-native-test-") as td:
            result = producer.run_production_smoke(Path(td), steps=2)
        self.assertEqual(result["status"], "PRODUCTION_SMOKE_PASS")
        self.assertEqual(result["steps"], 2)
        self.assertEqual(result["optimizers"]["adamw"]["class"], "AdamW")
        self.assertEqual(result["optimizers"]["muon"]["class"], "Muon")
        self.assertTrue(result["offload_wrapper"]["used_real_cpu_offload_optimizer"])
        self.assertEqual(result["offload_wrapper"]["arithmetic_source"], "optimizer_classes")

    def test_production_smoke_rejects_zero_steps(self):
        with tempfile.TemporaryDirectory(prefix="factor1-native-test-") as td:
            with self.assertRaisesRegex(ValueError, "steps"):
                producer.run_production_smoke(Path(td), steps=0)

    def test_preflight_binds_exact_scale_and_refuses_low_resources(self):
        result = producer.preflight_exact_scale({
            "available_commit_gib": 0.0,
            "available_physical_gib": 0.0,
            "disk_free_gib": 0.0,
        })
        self.assertFalse(result["sufficient"])
        self.assertEqual(result["scale"], "2.2B")
        self.assertIn("commit", " ".join(result["refusal_reasons"]).lower())
        self.assertIn("physical", " ".join(result["refusal_reasons"]).lower())
        self.assertIn("disk", " ".join(result["refusal_reasons"]).lower())

    def test_exact_scale_requires_explicit_execution_after_preflight(self):
        with tempfile.TemporaryDirectory(prefix="factor1-native-test-") as td:
            with self.assertRaisesRegex(PermissionError, "execute=True"):
                producer.run_exact_scale_cpu(Path(td), {
                    "available_commit_gib": 100.0,
                    "available_physical_gib": 100.0,
                    "disk_free_gib": 100.0,
                }, steps=1)

    def test_source_identity_is_not_caller_attested(self):
        identity = producer.source_identity()
        self.assertEqual(identity["producer_basename"], "factor1_cpuoffload_producer.py")
        self.assertRegex(identity["producer_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(identity["optimizer_sha256"], r"^[0-9a-f]{64}$")
        self.assertNotIn("path", identity)

    def test_published_receipt_binds_live_shape_and_external_source_commit(self):
        receipt = __import__("json").loads(
            (ROOT / "receipts" / "factor1-exact-scale-cpu-step1-20260806.json").read_text(encoding="utf-8")
        )
        self.assertEqual(receipt["producer_identity"]["shape_manifest_sha256"], producer.exact_shape_manifest()["shape_sha256"])
        self.assertRegex(receipt["public_binding"]["source_producer_commit_sha256"], r"^[0-9a-f]{40}$")
        self.assertTrue(receipt["public_binding"]["publication_head_bound_externally"])


if __name__ == "__main__":
    unittest.main()


class MicrobenchBindingTests(unittest.TestCase):
    def test_factor1_microbench_binds_current_native_producer(self):
        from scripts import factor1_lever_microbench as bench
        status = bench.production_path_status()
        self.assertTrue(status["available"])
        self.assertEqual(status["status"], "CURRENT_NATIVE_PRODUCER_AVAILABLE")
        self.assertEqual(status["producer_basename"], "factor1_cpuoffload_producer.py")

    def test_fixture_receipt_binds_current_bytes_and_supersedes_stale_identity(self):
        current_path = ROOT / "receipts" / "factor1-lever-microbench-20260806T205607Z.json"
        stale_path = ROOT / "receipts" / "factor1-lever-microbench-20260806T175504Z.json"
        current = __import__("json").loads(current_path.read_text(encoding="utf-8"))
        stale = __import__("json").loads(stale_path.read_text(encoding="utf-8"))
        implementation = ROOT / "scripts" / "factor1_lever_microbench.py"
        expected = hashlib.sha256(implementation.read_bytes()).hexdigest()
        self.assertEqual(current["implementation_sha256"], expected)
        self.assertEqual(stale["disposition"], "SUPERSEDED_STALE_SOURCE_IDENTITY")
        self.assertEqual(stale["superseded_by"], "receipts/factor1-lever-microbench-20260806T205607Z.json")
