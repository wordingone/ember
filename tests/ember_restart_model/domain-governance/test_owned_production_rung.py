# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Verify the checked-in owned four-domain vertical-rung input."""

from __future__ import annotations

import sys
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"))

from input_identity import InputIdentityError  # noqa: E402
from train import run_launch  # noqa: E402
from production_rung import (  # noqa: E402
    RECEIPT_RELATIVE,
    SHARD_RELATIVE,
    verify_bound_rung,
    verify_checked_in_production_rung,
)


class OwnedProductionRungTests(unittest.TestCase):
    def test_checked_in_rung_replays_raw_owned_sources_and_is_explicitly_not_sufficient_pretraining(self) -> None:
        receipt = verify_checked_in_production_rung(ROOT)
        self.assertEqual(receipt["result"], "VERIFIED")
        self.assertEqual(receipt["data_class"], "MEASURED_RUNG_NOT_SUFFICIENT_PRETRAINING")
        self.assertEqual(receipt["domain_record_counts"], {"vision": 1, "audio": 1, "reasoning": 1, "tool": 1})
        self.assertEqual(receipt["provenance"], {
            "borrowed_model_outputs": False,
            "borrowed_labels": False,
            "generated_labels": False,
            "model_derived_data": False,
            "teacher_outputs": False,
        })
    def test_changed_shard_or_receipt_cannot_pass_the_canonical_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            for relative in (
                "configs",
                "domains/model/tokenizer",
                "data/ember-restart-3b",
            ):
                shutil.copytree(ROOT / relative, root / relative)
            tools = root / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"
            tools.mkdir(parents=True)
            for name in (
                "build_owned_audio_frames.py",
                "build_owned_reasoning_tool_trajectories.py",
                "build_owned_vision_scenes.py",
                "semantic_contract.py",
                "specialist_semantics.py",
                "verify_capability_record.py",
                "production_rung.py",
            ):
                shutil.copy2(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b" / name, tools / name)
            shard = root / SHARD_RELATIVE
            receipt = root / RECEIPT_RELATIVE
            payload = json.loads(shard.read_bytes())
            payload["records"][0]["target_text"] = "forged target"
            shard.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "raw-spatial|canonical"):
                verify_bound_rung(root=root, shard_path=shard, receipt_path=receipt)
            shutil.copy2(ROOT / SHARD_RELATIVE, shard)
            forged_receipt = json.loads(receipt.read_bytes())
            forged_receipt["result"] = "FORGED"
            receipt.write_text(json.dumps(forged_receipt), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "receipt"):
                verify_bound_rung(root=root, shard_path=shard, receipt_path=receipt)
            with self.assertRaisesRegex(InputIdentityError, "receipt hash differs|production rung receipt verification failed"):
                run_launch(repo_root=root, code_commit="a" * 40)


if __name__ == "__main__":
    unittest.main()
