# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TDD integration boundary for issue #812 input identity forwarding."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

import torch

from model import RestartDecoderConfig, UnifiedDecoder  # noqa: E402
from pretrain import run_pretraining_segment  # noqa: E402
from train import run_launch  # noqa: E402

from input_identity import (  # noqa: E402
    InputIdentityError,
    build_launch_packet,
    emit_integration_receipt,
    validate_launch_packet,
)


class InputIdentityTests(unittest.TestCase):
    def _layout(self, root: Path) -> tuple[Path, Path]:
        shard = root / "data" / "ember-restart-3b" / "shards" / "owned.bin"
        shard.parent.mkdir(parents=True)
        shard.write_bytes(b"owned clean genesis training bytes")
        digest = hashlib.sha256(shard.read_bytes()).hexdigest()
        identity = root / "data" / "ember-restart-3b" / "input-identity.json"
        identity.write_text(json.dumps({
            "schema_version": "ember-input-identity-v1",
            "artifact_id": "owned-clean-shard-v1",
            "shard_path": "data/ember-restart-3b/shards/owned.bin",
            "sha256": digest,
            "bytes": shard.stat().st_size,
        }), encoding="utf-8")
        config = root / "configs" / "ember-restart-3b.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({
            "training": {
                "input_identity_manifest": "data/ember-restart-3b/input-identity.json",
                "expected_input_artifact_id": "owned-clean-shard-v1",
            }
        }), encoding="utf-8")
        return config, identity

    def test_none_uses_contract_default_worktree_invariantly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "main"
            config, identity = self._layout(root)
            old_cwd = Path.cwd()
            try:
                os.chdir(tempfile.gettempdir())
                packet = build_launch_packet(repo_root=root, config_path=config, input_identity_arg=None)
            finally:
                os.chdir(old_cwd)
            self.assertEqual(packet["requested_input_identity"], "data/ember-restart-3b/input-identity.json")
            self.assertEqual(packet["selection_source"], "contract_default")
            self.assertEqual(packet["input_identity"]["identity_manifest"], identity.relative_to(root).as_posix())
            self.assertEqual(validate_launch_packet(packet, repo_root=root)["decision"], "ACCEPTED")

    def test_main_and_separate_worktree_resolve_same_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            main = Path(directory) / "main"
            config, _ = self._layout(main)
            worktree = Path(directory) / "clean-worktree"
            shutil.copytree(main, worktree)
            first = build_launch_packet(repo_root=main, config_path=config)
            second = build_launch_packet(repo_root=worktree, config_path=worktree / "configs" / "ember-restart-3b.json")
            self.assertEqual(first["input_identity"]["sha256"], second["input_identity"]["sha256"])
            self.assertEqual(validate_launch_packet(first, repo_root=main)["decision"], "ACCEPTED")
            self.assertEqual(validate_launch_packet(second, repo_root=worktree)["decision"], "ACCEPTED")

    def test_missing_wrong_and_byte_drift_fail_closed_distinctly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            config, identity = self._layout(root)
            with self.assertRaisesRegex(InputIdentityError, "missing_input"):
                build_launch_packet(repo_root=root, config_path=config, input_identity_arg="data/ember-restart-3b/missing.json")
            payload = json.loads(identity.read_text(encoding="utf-8"))
            payload["artifact_id"] = "wrong-artifact"
            identity.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(InputIdentityError, "wrong_identity"):
                build_launch_packet(repo_root=root, config_path=config)
            payload["artifact_id"] = "owned-clean-shard-v1"
            identity.write_text(json.dumps(payload), encoding="utf-8")
            (root / payload["shard_path"]).write_bytes(b"drifted bytes")
            with self.assertRaisesRegex(InputIdentityError, "byte_drift"):
                build_launch_packet(repo_root=root, config_path=config)

    def test_forwarded_identity_is_consumed_not_decorative(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            config, _ = self._layout(root)
            packet = build_launch_packet(repo_root=root, config_path=config)
            missing = dict(packet)
            missing.pop("input_identity")
            with self.assertRaisesRegex(InputIdentityError, "caller_omission"):
                validate_launch_packet(missing, repo_root=root)
            decorative = dict(packet)
            decorative["input_identity"] = dict(packet["input_identity"])
            decorative["input_identity"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(InputIdentityError, "decorative_argument"):
                validate_launch_packet(decorative, repo_root=root)

    def test_live_caller_forwards_default_to_gate_and_validator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            self._layout(root)
            packet, validation, receipt = run_launch(repo_root=root, code_commit="b" * 40)
            self.assertEqual(packet["selection_source"], "contract_default")
            self.assertEqual(validation["decision"], "ACCEPTED")
            self.assertEqual(receipt["input_artifact_sha256"], packet["input_identity"]["sha256"])

    def test_checked_in_bound_bootstrap_record_executes_real_reasoning_segment(self) -> None:
        record = json.loads((ROOT / "data" / "ember-restart-3b" / "owned-bootstrap-v1.json").read_text(encoding="utf-8"))
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=53)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        result = run_pretraining_segment(
            model=model, optimizer=optimizer, records=[record], config=config, device=torch.device("cpu"),
            checkpoint_every=1, checkpoint_callback=lambda _step, _result: None,
            data_shard_id="owned-bootstrap-v1", require_complete_coverage=False,
        )
        self.assertEqual(result["expert_examples"]["reasoning"], 1)
        self.assertEqual(result["modality_examples"]["reasoning"], 1)
        self.assertEqual(result["modality_examples"]["image"], 0)
        self.assertEqual(result["data_cursor"]["record_index"], 1)
    def test_receipt_binds_commit_config_input_validator_and_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            config, _ = self._layout(root)
            packet = build_launch_packet(repo_root=root, config_path=config)
            result = validate_launch_packet(packet, repo_root=root)
            receipt = emit_integration_receipt(packet, result, code_commit="a" * 40)
            self.assertEqual(receipt["code_commit"], "a" * 40)
            self.assertEqual(receipt["config_sha256"], packet["config_sha256"])
            self.assertEqual(receipt["input_artifact_sha256"], packet["input_identity"]["sha256"])
            self.assertEqual(receipt["launch_decision"], "ACCEPTED")
            self.assertRegex(receipt["validator_sha256"], r"^[0-9a-f]{64}$")
            with self.assertRaisesRegex(InputIdentityError, "wrong_identity"):
                emit_integration_receipt(packet, result, code_commit="Z" * 40)


if __name__ == "__main__":
    unittest.main()
