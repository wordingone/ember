# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
import sys
sys.path.insert(0, str(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"))
from semantic_contract import semantic_model_contract_sha256
import build_specialist_bundle


class SemanticContractTests(unittest.TestCase):
    def _config(self) -> dict:
        return {
            "contract_version": 3,
            "architecture_revision": "ember-sparse-3b-v2",
            "model": {
                "architecture": "unified_decoder",
                "hidden_size": 2048,
                "layers": 14,
                "attention_heads": 16,
                "vocab_size": 32000,
                "tied_embeddings": True,
                "normalization": "rmsnorm",
                "position_encoding": "rope_1d_2d",
                "expert_routing": "one_active_expert",
                "image_projection": {"input_shape": [48, 48, 3], "output_size": 2048},
                "audio_projection": {"frame_samples": 640, "output_size": 2048},
                "parameter_formula": "instantiated_meta",
                "total_unique_trainable_parameters": 3839161856,
            },
            "training": {
                "gradient_checkpointing": True,
                "optimizer": {"implementation": "PagedAdamW8bit", "state_format": "bnb_paged_8bit"},
                "expert_activation": "exactly_one",
                "memory": {"dtype": "bfloat16"},
                "expected_input_artifact_id": "owned-bootstrap-v2",
                "gpu": {"cap_hours": 24},
                "write_policy": {"checkpoint_interval": 8192},
            },
            "runtime_path": "mutable/receipt/path",
        }

    def test_operational_changes_do_not_change_semantic_hash(self) -> None:
        config = self._config()
        baseline = semantic_model_contract_sha256(config)
        changed = copy.deepcopy(config)
        changed["training"]["gpu"]["cap_hours"] = 1
        changed["training"]["write_policy"]["checkpoint_interval"] = 1
        changed["runtime_path"] = "another/path"
        self.assertEqual(semantic_model_contract_sha256(changed), baseline)

    def test_architecture_and_input_changes_change_semantic_hash(self) -> None:
        config = self._config()
        baseline = semantic_model_contract_sha256(config)
        changed_arch = copy.deepcopy(config)
        changed_arch["model"]["hidden_size"] = 1024
        self.assertNotEqual(semantic_model_contract_sha256(changed_arch), baseline)
        changed_input = copy.deepcopy(config)
        changed_input["training"]["expected_input_artifact_id"] = "different-owned-input"
        self.assertNotEqual(semantic_model_contract_sha256(changed_input), baseline)

    def test_optimizer_placement_changes_semantic_hash(self) -> None:
        config = self._config()
        baseline = semantic_model_contract_sha256(config)
        changed = copy.deepcopy(config)
        changed["training"]["optimizer"] = {
            "implementation": "AdamW8bit",
            "state_format": "bnb_device_resident_8bit",
        }
        self.assertNotEqual(semantic_model_contract_sha256(changed), baseline)

    def test_producer_reference_binds_same_contract_for_all_families(self) -> None:
        from build_specialist_bundle import _model_contract_ref
        config_path = ROOT / "configs" / "ember-restart-3b.json"
        config = json.loads(config_path.read_bytes())
        expected = semantic_model_contract_sha256(config)
        for capability in ("image", "audio", "reasoning", "tool"):
            manifest = {"capability": capability, "model_contract": _model_contract_ref(ROOT, config_path, config)}
            self.assertEqual(manifest["model_contract"]["schema_version"], "ember-semantic-model-contract-v1")
            self.assertEqual(manifest["model_contract"]["semantic_sha256"], expected)
    def test_bound_contract_rejects_tampered_config_bytes(self) -> None:
        from verify_training_data import _bound_semantic_contract
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config.json"
            payload = self._config()
            config.write_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            record = {"schema_version": "ember-semantic-model-contract-v1", "path": "config.json", "semantic_sha256": semantic_model_contract_sha256(payload)}
            config.write_bytes(json.dumps({**payload, "model": {**payload["model"], "hidden_size": 1024}}, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            with self.assertRaisesRegex(ValueError, "semantic model contract sha256"):
                _bound_semantic_contract(root, record)
    def test_bound_contract_requires_closed_schema(self) -> None:
        from verify_training_data import _bound_semantic_contract
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "config.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "binding is missing or malformed"):
                _bound_semantic_contract(root, {"path": "config.json", "semantic_sha256": "0" * 64})
    def test_hash_is_canonical_content_address(self) -> None:
        config = self._config()
        digest = semantic_model_contract_sha256(config)
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertEqual(digest, semantic_model_contract_sha256(json.loads(json.dumps(config))))
