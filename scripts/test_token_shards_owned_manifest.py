# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
from unittest import mock
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("token_shards_v0", ROOT / "scripts" / "token_shards_v0.py")
assert SPEC is not None and SPEC.loader is not None
token_shards_v0 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(token_shards_v0)


class OwnedManifestShardValidatorTests(unittest.TestCase):
    def test_validator_requires_explicit_closed_owned_source_ids_mode(self):
        violations = token_shards_v0.validate_shards_receipt(
            {"ticket": "TOKEN-SHARDS-V0", "premises": {"source_manifest": {"source_ids": ["owned-a", "owned-b"]}}},
            expected_source_ids={"owned-a", "owned-c"},
        )
        self.assertTrue(any("source-manifest source IDs" in item for item in violations))

    def test_owned_validator_does_not_require_legacy_assembly_premise(self):
        violations = token_shards_v0.validate_shards_receipt(
            {"ticket": "TOKEN-SHARDS-V0", "premises": {
                "source_manifest": {"source_ids": ["owned-a"]},
            }},
            expected_source_ids={"owned-a"},
        )

        self.assertFalse(any("premise assembly_receipt" in item
                             for item in violations), violations)

    def test_owned_source_manifest_mode_never_loads_legacy_assembly(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "owned.jsonl"
            raw.write_text('{"text":"owned record"}\n', encoding="utf-8")

            def pinned(_root, name):
                if name == "legacy-assembly.json":
                    raise AssertionError("owned source-manifest mode loaded legacy assembly")
                self.assertEqual(name, "tokenizer-freeze.json")
                return "b" * 64, {
                    "tokenizer_repo_path": "tokenizer/tokenizer.json",
                    "tokenizer_json_sha256": "c" * 64,
                }

            with mock.patch.object(token_shards_v0, "_load_pinned", side_effect=pinned):
                receipt = token_shards_v0.produce_shards_v0(
                    directory,
                    encode_fn=lambda text: [8] * len(text),
                    sources=[("owned-source", [str(raw)])],
                    out_dir="owned-shards",
                    source_manifest_premise={
                        "schema_version": "ember-text-lab-corpus-manifest-v2",
                        "source_ids": ["owned-source"],
                        "sha256": "a" * 64,
                        "train_root_sha256": "d" * 64,
                        "heldout_root_sha256": "e" * 64,
                    },
                    token_cap=512,
                    assembly_name="legacy-assembly.json",
                    tokfreeze_name="tokenizer-freeze.json",
                )

        self.assertNotIn("assembly_receipt", receipt["premises"])
        self.assertEqual(receipt["premises"]["source_manifest"]["source_ids"],
                         ["owned-source"])

    def test_owned_source_manifest_premise_requires_closed_authority_fields(self):
        def pinned(_root, _name):
            return "b" * 64, {
                "tokenizer_repo_path": "tokenizer/tokenizer.json",
                "tokenizer_json_sha256": "c" * 64,
            }

        with mock.patch.object(token_shards_v0, "_load_pinned", side_effect=pinned):
            with self.assertRaisesRegex(ValueError, "owned source-manifest premise"):
                token_shards_v0.produce_shards_v0(
                    ".",
                    encode_fn=lambda _text: [8],
                    sources=[],
                    source_manifest_premise={
                        "schema_version": "ember-text-lab-corpus-manifest-v2",
                        "source_ids": [],
                        "sha256": "a" * 64,
                    },
                    tokfreeze_name="tokenizer-freeze.json",
                )

    def test_l4_transform_premise_binds_closed_train_selection(self):
        premise = {
            "schema_version": "ember-owned-text-l4-transform-receipt-v1",
            "sha256": "a" * 64,
            "source_ids": ["gutenberg-1000"],
            "train_root_sha256": "b" * 64,
            "heldout_root_sha256": "c" * 64,
            "l4_transform_receipt_sha256": "d" * 64,
            "selection_rule": "train_only_l4_transform_v1",
        }
        self.assertEqual(token_shards_v0._owned_source_manifest_errors(premise), [])
        with_extra = dict(premise, extra=True)
        self.assertIn("is not closed", token_shards_v0._owned_source_manifest_errors(with_extra))

if __name__ == "__main__":
    unittest.main()
