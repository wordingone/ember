# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed checkpoint publication and restore tests."""

from __future__ import annotations

import sys
import base64
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from checkpoint_artifacts import load_checkpoint_artifacts, write_checkpoint_artifacts as _write_checkpoint_artifacts
from pretrain import run_pretraining_segment
from verify_capability_record import expected_receipt
from model import RestartDecoderConfig, UnifiedDecoder


def write_checkpoint_artifacts(*args, **kwargs):
    """Make this module's synthetic checkpoint publications explicitly non-production."""
    kwargs.setdefault("test_only_allow_unverified", True)
    return _write_checkpoint_artifacts(*args, **kwargs)


class CheckpointIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        self.model = UnifiedDecoder(self.config, genesis_seed=7)
        self.optimizer = torch.optim.AdamW(self.model.parameters(), lr=1e-4)

    @staticmethod
    def _cursor(record_index: int, *, global_step: int = 0, tokens_seen: int = 0) -> dict[str, object]:
        return {
            "shard": "owned-bootstrap-v1",
            "record_index": record_index,
            "global_step": global_step,
            "tokens_seen": tokens_seen,
        }

    def _record(self, expert: str) -> dict[str, object]:
        image = bytes(index % 251 for index in range(48 * 48 * 3))
        audio = (torch.arange(640, dtype=torch.int16) - 320).numpy().tobytes()
        record: dict[str, object] = {
            "schema_version": "ember-owned-bootstrap-batch-v1", "sample_id": f"owned-resume-{expert}",
            "active_expert": expert, "capability_evidence": {},
        }
        if expert == "vision":
            record.update({"token_ids": [1, self.config.image_token_id, 2], "target_ids": [2, 3, 4], "image_patches_u8_base64": [base64.b64encode(image).decode("ascii")], "image_coordinates": [[0, 0]], "multimodal_spans": [{"start": 1, "length": 1, "modality": "image", "attention_mode": "isolated"}]})
        elif expert == "audio":
            record.update({"token_ids": [1, self.config.audio_token_id, 2], "target_ids": [2, 3, 4], "audio_frames_i16le_base64": [base64.b64encode(audio).decode("ascii")], "image_coordinates": [], "multimodal_spans": [{"start": 1, "length": 1, "modality": "audio", "attention_mode": "causal"}]})
        else:
            record.update({"token_ids": [1, 2, 3], "target_ids": [2, 3, 4], "image_coordinates": [], "multimodal_spans": []})
            if expert == "reasoning":
                record["capability_evidence"] = {"reasoning": {"operands": [1, 2], "target": 3, "trace": [1, 2, 3]}}
            else:
                record["capability_evidence"] = {"tool": {"name": "owned_calculator", "arguments": {"expression": "1+2"}, "observation": {"value": 3}}}
            record["capability_receipt"] = expected_receipt(record)
        return record
    def _assert_equal_state(self, first: object, second: object) -> None:
        if isinstance(first, torch.Tensor):
            self.assertIsInstance(second, torch.Tensor)
            self.assertTrue(torch.equal(first, second))
        elif isinstance(first, dict):
            self.assertEqual(set(first), set(second))
            for key in first:
                self._assert_equal_state(first[key], second[key])
        elif isinstance(first, (list, tuple)):
            self.assertEqual(len(first), len(second))
            for left, right in zip(first, second):
                self._assert_equal_state(left, right)
        else:
            self.assertEqual(first, second)
    def _write(self, root: Path) -> dict[str, object]:
        return write_checkpoint_artifacts(
            self.model, self.optimizer, root, launch_seed=7,
            rng_state={"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
            data_cursor=self._cursor(0),
            model_config_sha256="c" * 64, contract_sha256="d" * 64, expert_genesis_sha256=self.model.expert_bank_genesis_hashes(),
        )

    def test_manifest_is_newline_terminated_and_binds_replay_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "checkpoint-0001"
            receipt = self._write(root)
            raw_manifest = (root / "checkpoint-manifest.json").read_bytes()
        self.assertTrue(raw_manifest.endswith(b"\n"))
        self.assertRegex(receipt["rng_state_sha256"]["cpu"], r"^[0-9a-f]{64}$")
        self.assertEqual(receipt["data_cursor"]["record_index"], 0)
        self.assertEqual(receipt["model_config_sha256"], "c" * 64)
        self.assertEqual(receipt["contract_sha256"], "d" * 64)
        self.assertRegex(receipt["checkpoint_manifest_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(len(receipt["shards"]), 6)


    def test_restore_recovers_actual_rng_state_and_data_cursor(self) -> None:
        cpu_rng = torch.get_rng_state().clone()
        cuda_rng = torch.tensor([7, 8, 9], dtype=torch.uint8)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "checkpoint-0001"
            receipt = write_checkpoint_artifacts(
                self.model, self.optimizer, root, launch_seed=7,
                rng_state={"cpu": cpu_rng, "cuda": cuda_rng},
                data_cursor=self._cursor(3, global_step=3, tokens_seen=12),
                model_config_sha256="c" * 64, contract_sha256="d" * 64,
                expert_genesis_sha256=self.model.expert_bank_genesis_hashes(),
            )
            restored = UnifiedDecoder(self.config, genesis_seed=99)
            restore_optimizer = torch.optim.AdamW(restored.parameters(), lr=1e-4)
            torch.manual_seed(999)
            with unittest.mock.patch.object(torch.cuda, "set_rng_state") as set_cuda:
                replay = load_checkpoint_artifacts(restored, restore_optimizer, root, receipt)
        self.assertTrue(torch.equal(torch.get_rng_state(), cpu_rng))
        set_cuda.assert_called_once()
        self.assertEqual(replay["data_cursor"], self._cursor(3, global_step=3, tokens_seen=12))
        self.assertIn("replay-state.pt", {record["path"] for record in receipt["shards"]})

    def test_rejects_cursor_without_global_step_tokens_and_record_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "data cursor"):
                write_checkpoint_artifacts(
                    self.model, self.optimizer, Path(directory) / "checkpoint-0001", launch_seed=7,
                    rng_state={"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
                    data_cursor={"shard": "owned-bootstrap-v1", "record_index": 0},
                    model_config_sha256="c" * 64, contract_sha256="d" * 64,
                    expert_genesis_sha256=self.model.expert_bank_genesis_hashes(),
                )

    def test_interruption_restore_resume_matches_continuous_training(self) -> None:
        records = [self._record(expert) for expert in ("vision", "audio", "reasoning", "tool")]
        continuous = UnifiedDecoder(self.config, genesis_seed=71)
        continuous_optimizer = torch.optim.AdamW(continuous.parameters(), lr=1e-4)
        continuous_result = run_pretraining_segment(
            model=continuous, optimizer=continuous_optimizer, records=records, config=self.config,
            device=torch.device("cpu"), checkpoint_every=4, checkpoint_callback=lambda _step, _result: None,
            data_shard_id="owned-resume-v1",
        )
        continuous_rng = torch.get_rng_state().clone()

        interrupted = UnifiedDecoder(self.config, genesis_seed=71)
        interrupted_optimizer = torch.optim.AdamW(interrupted.parameters(), lr=1e-4)
        first_half = run_pretraining_segment(
            model=interrupted, optimizer=interrupted_optimizer, records=records[:2], config=self.config,
            device=torch.device("cpu"), checkpoint_every=2, checkpoint_callback=lambda _step, _result: None,
            data_shard_id="owned-resume-v1", require_complete_coverage=False,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "checkpoint-0002"
            receipt = write_checkpoint_artifacts(
                interrupted, interrupted_optimizer, root, launch_seed=71,
                rng_state={"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([7, 8, 9], dtype=torch.uint8)},
                data_cursor=first_half["data_cursor"], model_config_sha256="c" * 64, contract_sha256="d" * 64,
                expert_genesis_sha256=interrupted.expert_bank_genesis_hashes(),
            )
            restored = UnifiedDecoder(self.config, genesis_seed=99)
            restored_optimizer = torch.optim.AdamW(restored.parameters(), lr=1e-4)
            with unittest.mock.patch.object(torch.cuda, "set_rng_state"):
                cursor = load_checkpoint_artifacts(restored, restored_optimizer, root, receipt)["data_cursor"]
            resumed = run_pretraining_segment(
                model=restored, optimizer=restored_optimizer,
                records=records, config=self.config, device=torch.device("cpu"),
                checkpoint_every=4, checkpoint_callback=lambda _step, _result: None,
                initial_global_step=cursor["global_step"], initial_tokens_seen=cursor["tokens_seen"],
                initial_data_cursor=cursor["record_index"], data_shard_id=cursor["shard"],
                require_complete_coverage=False,
            )
        self.assertEqual(resumed["data_cursor"], continuous_result["data_cursor"])
        self._assert_equal_state(continuous.state_dict(), restored.state_dict())
        self._assert_equal_state(continuous_optimizer.state_dict(), restored_optimizer.state_dict())
        self.assertTrue(torch.equal(torch.get_rng_state(), continuous_rng))
    def test_refuses_to_overwrite_a_published_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "checkpoint-0001" / "checkpoint-0001"
            receipt = self._write(root)
            manifest_before = (root / "checkpoint-manifest.json").read_bytes()
            with self.assertRaisesRegex(FileExistsError, "published checkpoint bundle"):
                self._write(root)
            self.assertEqual((root / "checkpoint-manifest.json").read_bytes(), manifest_before)
            self.assertTrue((root / "replay-state.pt").is_file())
            self.assertRegex(receipt["checkpoint_manifest_sha256"], r"^[0-9a-f]{64}$")
    def test_restore_does_not_mutate_model_when_any_shard_fails_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "checkpoint-0001"
            receipt = self._write(root)
            (root / "expert-tool.pt").write_bytes(b"corrupted")
            restored = UnifiedDecoder(self.config, genesis_seed=99)
            before = next(restored.parameters()).detach().clone()
            restore_optimizer = torch.optim.AdamW(restored.parameters(), lr=1e-4)
            with self.assertRaisesRegex(ValueError, "expert shard hash mismatch: tool"):
                load_checkpoint_artifacts(restored, restore_optimizer, root, receipt)
            self.assertTrue(torch.equal(before, next(restored.parameters()).detach()))


if __name__ == "__main__":
    unittest.main()
