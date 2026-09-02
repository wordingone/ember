# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Issue #896 clause 7: real short checkpoint/resume smoke through the production
low-commit deferral path.

This is a RUN, not a unit test of the deferral helper: a real CPU
``run_pretraining_segment`` drives its checkpoint boundaries through the real
``_publish_checkpoint_with_low_commit_deferral`` into the real
``checkpoint_artifacts.write_checkpoint_artifacts`` (production module, not the
test fixture), with the real Windows host-commit probe. The low-commit condition
is injected through the production seam the runner itself uses --
``host_commit_reserve_bytes`` (sourced from config by
``checkpoint_host_commit_reserve_bytes``) -- by making the first boundary's
reserve larger than any host's headroom. No publish/probe code is mocked.
"""

from __future__ import annotations

import json
import sys
import base64
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import torch

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))
sys.path.insert(0, str(ROOT / "tests" / "ember_restart_model" / "domain-governance"))

import run_vertical_slice
from checkpoint_artifacts import load_checkpoint_artifacts, write_checkpoint_artifacts
from pretrain import run_pretraining_segment
from verify_capability_record import expected_receipt
from checkpoint_fixture import fixture_counter_receipt
from model import RestartDecoderConfig, UnifiedDecoder

# Larger than any real host's commit headroom: forces the REAL preflight
# (real available_host_commit_bytes() probe) into CheckpointDeferredLowCommit.
_IMPOSSIBLE_RESERVE_BYTES = 1 << 62


class CheckpointResumeSmokeTests(unittest.TestCase):
    def _record(self, config: RestartDecoderConfig, expert: str) -> dict[str, object]:
        image = bytes(index % 251 for index in range(48 * 48 * 3))
        audio = (torch.arange(640, dtype=torch.int16) - 320).numpy().tobytes()
        record: dict[str, object] = {
            "schema_version": "ember-owned-bootstrap-batch-v1", "sample_id": f"owned-smoke-{expert}",
            "active_expert": expert, "capability_evidence": {},
        }
        if expert == "vision":
            record.update({"token_ids": [1, config.image_token_id, 2], "target_ids": [2, 3, 4], "image_patches_u8_base64": [base64.b64encode(image).decode("ascii")], "image_coordinates": [[0, 0]], "multimodal_spans": [{"start": 1, "length": 1, "modality": "image", "attention_mode": "isolated"}]})
        elif expert == "audio":
            record.update({"token_ids": [1, config.audio_token_id, 2], "target_ids": [2, 3, 4], "audio_frames_i16le_base64": [base64.b64encode(audio).decode("ascii")], "image_coordinates": [], "multimodal_spans": [{"start": 1, "length": 1, "modality": "audio", "attention_mode": "causal"}]})
        else:
            record.update({"token_ids": [1, 2, 3], "target_ids": [2, 3, 4], "image_coordinates": [], "multimodal_spans": []})
            if expert == "reasoning":
                record["capability_evidence"] = {"reasoning": {"operands": [1, 2], "target": 3, "trace": [1, 2, 3]}}
            else:
                record["capability_evidence"] = {"tool": {"name": "owned_calculator", "arguments": {"expression": "1+2"}, "observation": {"value": 3}}}
            record["capability_receipt"] = expected_receipt(record)
        return record

    def test_short_run_defers_low_commit_boundary_then_publishes_and_resumes(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=71)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        records = [self._record(config, expert) for expert in ("vision", "audio", "reasoning", "tool")]
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            config_path = directory / "config.json"
            config_path.write_text(json.dumps({
                "checkpoints": {"retention": {"max_serialized_gib": 1, "preserve_last_known_good": True}},
            }), encoding="utf-8")
            checkpoint_parent = directory / "checkpoints"
            checkpoint_parent.mkdir()

            deferral_state = {"count": 0}
            published: dict[str, object] = {}
            boundary_reserves: dict[int, int] = {2: _IMPOSSIBLE_RESERVE_BYTES, 4: 0}
            last_checkpointed = {"step": 0}

            def checkpoint_callback(global_step: int, state: dict[str, object]) -> None:
                cursor = dict(state["data_cursor"])
                target = checkpoint_parent / f"checkpoint-smoke-step-{global_step}"

                def publish() -> tuple[dict[str, object], dict[str, object]]:
                    receipt = write_checkpoint_artifacts(
                        model, optimizer, target, launch_seed=71,
                        rng_state={"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([7, 8, 9], dtype=torch.uint8)},
                        data_cursor=cursor, model_config_sha256="c" * 64, contract_sha256="d" * 64,
                        expert_genesis_sha256=model.expert_bank_genesis_hashes(),
                        host_commit_reserve_bytes=boundary_reserves[global_step],
                        pre_publish_verifier=fixture_counter_receipt,
                    )
                    return receipt, {"smoke_boundary_step": global_step}

                result = run_vertical_slice._publish_checkpoint_with_low_commit_deferral(
                    checkpoint_parent=checkpoint_parent, config_path=config_path,
                    global_step=global_step, last_checkpointed_step=last_checkpointed["step"],
                    deferral_state=deferral_state, publish=publish,
                    telemetry_path=None, telemetry_run_id=None,
                )
                if result is None:
                    return
                published["receipt"], published["verify"] = result
                published["root"] = target
                last_checkpointed["step"] = global_step

            run_pretraining_segment(
                model=model, optimizer=optimizer, records=records, config=config,
                device=torch.device("cpu"), checkpoint_every=2,
                checkpoint_callback=checkpoint_callback, data_shard_id="owned-smoke-v1",
            )

            # (b) the step-2 boundary was DEFERRED, not aborted, through the real probe.
            self.assertEqual(deferral_state["count"], 1)
            # The deferred candidate was never selectable: no bytes ever staged/published.
            self.assertFalse((checkpoint_parent / "checkpoint-smoke-step-2").exists())
            deferral_receipts = list((checkpoint_parent / ".checkpoint-deferrals").glob("deferred-low-commit-step-2-*.json"))
            self.assertEqual(len(deferral_receipts), 1)
            receipt_payload = json.loads(deferral_receipts[0].read_text(encoding="utf-8"))
            self.assertEqual(receipt_payload["status"], "DEFERRED_LOW_COMMIT")
            # (c) the later boundary published normally.
            self.assertEqual(published["root"], checkpoint_parent / "checkpoint-smoke-step-4")
            self.assertTrue((published["root"] / "checkpoint-manifest.json").is_file())
            self.assertEqual(
                [path.name for path in checkpoint_parent.iterdir() if path.is_dir() and path.name.startswith("checkpoint-")],
                ["checkpoint-smoke-step-4"],
            )
            # (d) resume from the published checkpoint preserves training truth.
            restored = UnifiedDecoder(config, genesis_seed=99)
            restored_optimizer = torch.optim.AdamW(restored.parameters(), lr=1e-4)
            with unittest.mock.patch.object(torch.cuda, "set_rng_state"):
                cursor = load_checkpoint_artifacts(restored, restored_optimizer, published["root"], published["receipt"])["data_cursor"]
            self.assertEqual(cursor["global_step"], 4)
            self.assertEqual(cursor["record_index"], 4)
            live = model.state_dict()
            for name, tensor in restored.state_dict().items():
                self.assertTrue(torch.equal(tensor, live[name]), f"restored parameter differs: {name}")


if __name__ == "__main__":
    unittest.main()
