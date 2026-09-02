# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
import json
import tempfile
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts" / "r3_feasibility_probe.py"
REVALIDATOR = ROOT / "scripts" / "land210j_public_revalidation.py"
HISTORICAL = (
    ROOT / "receipts" / "ember-c-scale"
    / "land210j-family3-stragglers-receipt.json"
)
SUBJECT = "33027681a36ed351478e13ab05418b0698a00e15"


def load_probe():
    spec = importlib.util.spec_from_file_location("land210j_r3_probe", PROBE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_revalidator():
    spec = importlib.util.spec_from_file_location("land210j_revalidator", REVALIDATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_dryrun_receipt() -> dict:
    return {
        "ticket": "R3-FEASIBILITY-PROBE",
        "mode": "dry_run",
        "model_id": "ember-owned-synthetic-random-init-v1",
        "model_source": {
            "source_kind": "OWNED_RANDOM_INIT",
            "architecture": "LlamaForCausalLM",
            "config": {"vocab_size": 256},
            "external_checkpoint": None,
            "external_model_id": None,
        },
        "all_assertions_passed": True,
        "paid_api_surface_used": False,
        "leg1_base_loaded_4bit_frozen": False,
        "leg3_training_step": {
            "grad_norm": 0.5,
            "grad_norm_nonzero_assert_passed": True,
        },
        "leg4_inference_pass": {
            "n_new_tokens": 64,
            "min_tokens_assert_passed": True,
        },
    }


def write_receipt(directory: str, receipt: dict) -> Path:
    path = Path(directory) / "dryrun.json"
    path.write_text(json.dumps(receipt), encoding="utf-8", newline="\n")
    return path


class Land210jOwnedDryRunTests(unittest.TestCase):
    def test_dry_run_model_is_owned_random_init_and_never_from_pretrained(self) -> None:
        probe = load_probe()
        calls: dict[str, object] = {}

        class FakeConfig:
            def __init__(self, **kwargs):
                calls["config"] = kwargs

        class FakeModel:
            def __init__(self, config):
                calls["model_config"] = config

        fake_transformers = types.SimpleNamespace(
            LlamaConfig=FakeConfig,
            LlamaForCausalLM=FakeModel,
        )
        with patch.dict(sys.modules, {"transformers": fake_transformers}):
            model, provenance = probe.build_owned_synthetic_dryrun_model()

        self.assertIsInstance(model, FakeModel)
        self.assertEqual(provenance["source_kind"], "OWNED_RANDOM_INIT")
        self.assertEqual(provenance["external_checkpoint"], None)
        self.assertEqual(provenance["external_model_id"], None)
        self.assertEqual(provenance["architecture"], "LlamaForCausalLM")
        self.assertEqual(calls["config"]["vocab_size"], 256)
        self.assertEqual(calls["config"]["num_hidden_layers"], 2)

    def test_probe_source_has_no_borrowed_dry_run_model_or_download_path(self) -> None:
        source = PROBE.read_text(encoding="utf-8", errors="strict")
        self.assertNotIn("DRYRUN_SUBSTITUTE_MODEL", source)
        self.assertNotIn("Qwen/Qwen", source)
        dry_run_start = source.index("if args.dry_run:", source.index("# --- Leg 1"))
        real_start = source.index("else:", dry_run_start)
        dry_run_branch = source[dry_run_start:real_start]
        self.assertNotIn("from_pretrained", dry_run_branch)
        self.assertIn("build_owned_synthetic_dryrun_model", dry_run_branch)

    def test_owned_synthetic_configuration_is_small_and_deterministic(self) -> None:
        probe = load_probe()
        first = probe.owned_synthetic_dryrun_config()
        second = probe.owned_synthetic_dryrun_config()
        self.assertEqual(first, second)
        self.assertEqual(first["vocab_size"], 256)
        self.assertEqual(first["hidden_size"], 64)
        self.assertEqual(first["intermediate_size"], 128)
        self.assertEqual(first["num_hidden_layers"], 2)
        self.assertEqual(first["num_attention_heads"], 4)
        self.assertEqual(first["num_key_value_heads"], 2)
        self.assertGreaterEqual(first["max_position_embeddings"], 80)

    def test_exact_public_lineage_and_owned_cpu_receipt(self) -> None:
        revalidator = load_revalidator()
        with tempfile.TemporaryDirectory() as directory:
            dryrun = write_receipt(directory, valid_dryrun_receipt())
            receipt = revalidator.build_receipt(
                ROOT,
                HISTORICAL,
                dryrun,
                subject_commit=SUBJECT,
                timestamp="2026-07-29T13:51:00Z",
            )
        self.assertEqual(receipt["public_lineage"]["candidate_count"], 7)
        current = receipt["current_source_revalidation"]
        self.assertEqual(current["compiled_files"], 7)
        self.assertEqual(current["repaired_files"], 1)
        self.assertEqual(current["unchanged_files"], 6)
        replay = receipt["owned_synthetic_cpu_replay"]
        self.assertEqual(replay["model_source"]["source_kind"], "OWNED_RANDOM_INIT")
        self.assertTrue(replay["all_assertions_passed"])
        self.assertEqual(replay["generated_tokens"], 64)
        boundary = receipt["claim_boundary"]
        self.assertFalse(boundary["external_checkpoint_loaded"])
        self.assertFalse(boundary["borrowed_model_credit_claim"])
        self.assertFalse(boundary["gpu_used"])
        self.assertFalse(boundary["real_27b_feasibility_claim"])
        self.assertFalse(boundary["issue_700_completion_claim"])

    def test_revalidator_rejects_external_model_and_false_step(self) -> None:
        revalidator = load_revalidator()
        receipt = valid_dryrun_receipt()

        foreign = json.loads(json.dumps(receipt))
        foreign["model_source"]["external_model_id"] = "foreign/model"
        with self.assertRaisesRegex(ValueError, "external model id"):
            with patch.object(revalidator, "load_json", return_value=foreign):
                revalidator.validate_dryrun_receipt(PROBE)

        vacuous = json.loads(json.dumps(receipt))
        vacuous["leg3_training_step"]["grad_norm_nonzero_assert_passed"] = False
        with self.assertRaisesRegex(ValueError, "training proof"):
            with patch.object(revalidator, "load_json", return_value=vacuous):
                revalidator.validate_dryrun_receipt(PROBE)

    def test_revalidator_rejects_bad_subject_and_current_source_drift(self) -> None:
        revalidator = load_revalidator()
        _, digests = revalidator.validate_historical(HISTORICAL)
        with self.assertRaisesRegex(ValueError, "reviewed public base"):
            revalidator.validate_public_lineage(ROOT, "0" * 40, digests)

        changed = dict(digests)
        changed["src/ember/governance/scripts/ember_cbase_launch.py"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "unexpected current byte drift"):
            revalidator.validate_current_sources(ROOT, changed)


if __name__ == "__main__":
    unittest.main()
