# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Final checkpoint publication survives the low-commit trough (#1465).

Two receipted failure shapes from the first certified specialist canary:
DEFERRED_LOW_COMMIT at the mandatory final boundary (a final-only run has no
later interval, so the deferral forfeited the whole trained segment), and a
MemoryError inside the slice receipt's monolithic canonicalization -- the run's
largest host allocation, executed before any commit guard could refuse it.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"))

import checkpoint_artifacts
import run_vertical_slice

# The exact bytes the incident receipts measured at the canary's final boundary.
_INCIDENT_STREAMING_PEAK_BYTES = 198_180_864
_INCIDENT_RESERVE_BYTES = 8_589_934_592
_INCIDENT_REQUIRED_BYTES = _INCIDENT_STREAMING_PEAK_BYTES + _INCIDENT_RESERVE_BYTES
_INCIDENT_FIRST_LOW_BYTES = 6_654_955_520
_INCIDENT_SECOND_LOW_BYTES = 6_825_594_880
_RECOVERED_COMMIT_BYTES = 9_000_000_000


def _edge_case_records() -> list[dict[str, object]]:
    return [
        {
            "token_ids": [0, 1, 2**63 - 1],
            "active_expert": "vision",
            "text": "ünïcode ☃ \U0001F680 \"quoted\" back\\slash\nnewline\ttab",
            "nested": {"z": [1, {"empty": {}, "list": []}], "a": {"deep": {"deeper": [None, True, False]}}},
            "numbers": {"float": 0.1, "negative": -2.5e-3, "large": 10**30, "zero": 0, "neg_zero": -0.0, "big": 1.7976931348623157e308},
            "empty_string": "",
        },
        {"token_ids": [5], "b_key": "б", "a_key": "…", "mixed": [{"k2": 2, "k1": 1}, "π", 3.14159]},
        {"token_ids": [7, 8], "astral": "\U0001F600\U0001F389", "control": "\u0000\u001f"},
    ]


class StreamingSliceCanonicalizationTests(unittest.TestCase):
    def test_streaming_receipt_matches_monolithic_dumps_on_edge_case_records(self) -> None:
        """The receipt's digests are byte-identical to the former monolithic
        json.dumps canonicalization (that exact formula inlined below)."""
        records = _edge_case_records()
        receipt = run_vertical_slice.specialist_execution_slice_receipt(records, source_start_record=0)
        monolithic_records = json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
        monolithic_tokens = json.dumps([list(record["token_ids"]) for record in records], separators=(",", ":")).encode("utf-8")
        self.assertEqual(receipt["records_sha256"], hashlib.sha256(monolithic_records).hexdigest())
        self.assertEqual(receipt["tokens_sha256"], hashlib.sha256(monolithic_tokens).hexdigest())
        self.assertEqual(receipt["record_count"], 3)
        self.assertEqual(receipt["token_count"], 6)
        self.assertEqual(receipt["start_record"], 0)

    def test_canonical_array_helper_is_byte_identical_across_payloads(self) -> None:
        payloads: list[list[object]] = [
            [],
            [{}],
            [[]],
            [
                {"b": 1, "a": 2, "é": "ü", "A": [0.1, -0.0, 1e-9, 10**40]},
                "☃",
                None,
                True,
                False,
                3.5,
                [[]],
                {"nested": {"y": 1, "x": 2}},
            ],
        ]
        for payload in payloads:
            for sort_keys in (False, True):
                with self.subTest(payload=payload, sort_keys=sort_keys):
                    expected = hashlib.sha256(
                        json.dumps(payload, sort_keys=sort_keys, separators=(",", ":")).encode("utf-8")
                    ).hexdigest()
                    self.assertEqual(
                        run_vertical_slice._sha256_of_canonical_json_array(payload, sort_keys=sort_keys),
                        expected,
                    )

    def test_non_vision_capability_receipts_are_byte_identical_pre_post(self) -> None:
        """Audio/reasoning/tool slice receipts equal the former implementation's
        complete output for identical input -- unchanged by construction."""
        for expert in ("audio", "reasoning", "tool"):
            with self.subTest(expert=expert):
                records = [
                    {"token_ids": [1, 2, 3], "active_expert": expert, "payload": {"n": 1}},
                    {"token_ids": [4], "active_expert": expert},
                ]
                receipt = run_vertical_slice.specialist_execution_slice_receipt(records, source_start_record=3)
                legacy = {
                    "schema_version": "ember-specialist-execution-slice-v1",
                    "start_record": 3,
                    "record_count": 2,
                    "token_count": 4,
                    "records_sha256": hashlib.sha256(
                        json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
                    ).hexdigest(),
                    "tokens_sha256": hashlib.sha256(
                        json.dumps([[1, 2, 3], [4]], separators=(",", ":")).encode("utf-8")
                    ).hexdigest(),
                }
                self.assertEqual(receipt, legacy)

    def test_scene_split_receipt_shape_and_validation_unchanged(self) -> None:
        records = [{"token_ids": [1, 2], "active_expert": "vision", "scene_split": "train"}]
        receipt = run_vertical_slice.specialist_execution_slice_receipt(
            records, source_start_record=0, scene_split_record_count=5
        )
        self.assertEqual(receipt["scene_split_record_count"], 5)
        for bad_records in (
            [],
            [{"token_ids": []}],
            [{"token_ids": [1, -2]}],
            [{"token_ids": [True]}],
            [{"no_tokens": [1]}],
        ):
            with self.subTest(bad_records=bad_records), self.assertRaises(ValueError):
                run_vertical_slice.specialist_execution_slice_receipt(bad_records, source_start_record=0)


class FinalPublicationLowCommitRetryTests(unittest.TestCase):
    def _config_and_policy(self, directory: Path, *, max_deferrals: int, max_distance: int) -> tuple[Path, Path]:
        config_path = directory / "config.json"
        config_path.write_text(json.dumps({
            "checkpoints": {"retention": {"max_serialized_gib": 1, "preserve_last_known_good": True}},
        }), encoding="utf-8")
        policy_path = directory / "policy.json"
        policy_path.write_text(json.dumps({
            "low_commit_deferral": {
                "max_deferrals": max_deferrals,
                "max_uncheckpointed_step_distance": max_distance,
            },
        }), encoding="utf-8")
        return config_path, policy_path

    @staticmethod
    def _probe_bound_publish() -> object:
        """Mirror the exact probe->preflight call shape of the production write
        path, so patching the commit probe exercises the real deferral raise."""

        def publish() -> tuple[dict[str, object], dict[str, object]]:
            preflight = checkpoint_artifacts.checkpoint_commit_preflight(
                available_commit_bytes=checkpoint_artifacts.available_host_commit_bytes(),
                streaming_peak_bytes=_INCIDENT_STREAMING_PEAK_BYTES,
                reserve_bytes=_INCIDENT_RESERVE_BYTES,
            )
            return ({"checkpoint": "ok", "host_commit_preflight": preflight}, {"receipt": "ok"})

        return publish

    def test_final_retry_publishes_when_commit_recovers_after_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            config_path, policy_path = self._config_and_policy(directory, max_deferrals=3, max_distance=2000)
            checkpoint_parent = directory / "checkpoints"
            release_calls: list[int] = []

            def release() -> dict[str, object]:
                release_calls.append(1)
                return {"released_record_count": 200}

            state: dict[str, int] = {"count": 0}
            with patch.object(
                checkpoint_artifacts, "available_host_commit_bytes",
                side_effect=[_INCIDENT_FIRST_LOW_BYTES, _RECOVERED_COMMIT_BYTES],
            ) as probe:
                result = run_vertical_slice._publish_checkpoint_with_low_commit_deferral(
                    checkpoint_parent=checkpoint_parent, config_path=config_path, global_step=200,
                    last_checkpointed_step=0, deferral_state=state, publish=self._probe_bound_publish(),
                    telemetry_path=None, telemetry_run_id=None, policy_path=policy_path,
                    release_for_final_retry=release,
                )
            self.assertIsNotNone(result)
            self.assertEqual(result[0]["host_commit_preflight"]["status"], "PASS")
            self.assertEqual(result[0]["host_commit_preflight"]["available_commit_bytes"], _RECOVERED_COMMIT_BYTES)
            self.assertEqual(probe.call_count, 2)
            self.assertEqual(release_calls, [1])
            self.assertEqual(state["count"], 0)
            self.assertFalse((checkpoint_parent / ".checkpoint-deferrals").exists())

    def test_final_retry_still_low_defers_with_additive_retry_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            config_path, policy_path = self._config_and_policy(directory, max_deferrals=3, max_distance=2000)
            checkpoint_parent = directory / "checkpoints"
            telemetry_path = directory / "telemetry.jsonl"
            records = [{"token_ids": [1, 2], "media": "x" * 64} for _ in range(3)]
            segment_view = list(records)

            state: dict[str, int] = {"count": 0}
            with patch.object(
                checkpoint_artifacts, "available_host_commit_bytes",
                side_effect=[_INCIDENT_FIRST_LOW_BYTES, _INCIDENT_SECOND_LOW_BYTES],
            ) as probe:
                result = run_vertical_slice._publish_checkpoint_with_low_commit_deferral(
                    checkpoint_parent=checkpoint_parent, config_path=config_path, global_step=200,
                    last_checkpointed_step=0, deferral_state=state, publish=self._probe_bound_publish(),
                    telemetry_path=telemetry_path, telemetry_run_id="run-1", policy_path=policy_path,
                    release_for_final_retry=lambda: run_vertical_slice._release_final_publication_ballast(records),
                )
            self.assertIsNone(result)
            self.assertEqual(probe.call_count, 2)
            self.assertEqual(state["count"], 1)
            # The release emptied the shared record dicts in place, so aliased
            # frames (the segment's bounded slice, scene-split lists) freed too.
            self.assertEqual(records, [])
            self.assertTrue(all(record == {} for record in segment_view))
            receipts = list((checkpoint_parent / ".checkpoint-deferrals").glob("*.json"))
            self.assertEqual(len(receipts), 1)
            receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
            self.assertEqual(receipt["schema_version"], "ember-checkpoint-deferred-low-commit-v1")
            self.assertEqual(receipt["status"], "DEFERRED_LOW_COMMIT")
            # Both boundary measurements are receipted: pre-teardown
            # (available_commit_bytes) and post-teardown
            # (retry_observed_commit_bytes), so analysis can read exactly how
            # much the teardown returned.
            self.assertEqual(receipt["available_commit_bytes"], _INCIDENT_FIRST_LOW_BYTES)
            self.assertEqual(receipt["required_commit_bytes"], _INCIDENT_REQUIRED_BYTES)
            self.assertEqual(receipt["retry_observed_commit_bytes"], _INCIDENT_SECOND_LOW_BYTES)
            self.assertEqual(receipt["retry_required_commit_bytes"], _INCIDENT_REQUIRED_BYTES)
            self.assertEqual(receipt["released_record_count"], 3)
            events = [json.loads(line) for line in telemetry_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["payload"]["retry_observed_commit_bytes"], _INCIDENT_SECOND_LOW_BYTES)

    def test_final_retry_exhausted_raises_todays_fail_closed_bound_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            config_path, policy_path = self._config_and_policy(directory, max_deferrals=0, max_distance=2000)
            checkpoint_parent = directory / "checkpoints"
            state: dict[str, int] = {"count": 0}
            with patch.object(
                checkpoint_artifacts, "available_host_commit_bytes",
                side_effect=[_INCIDENT_FIRST_LOW_BYTES, _INCIDENT_SECOND_LOW_BYTES],
            ):
                with self.assertRaisesRegex(RuntimeError, "checkpoint low-commit deferral bound exceeded"):
                    run_vertical_slice._publish_checkpoint_with_low_commit_deferral(
                        checkpoint_parent=checkpoint_parent, config_path=config_path, global_step=200,
                        last_checkpointed_step=0, deferral_state=state, publish=self._probe_bound_publish(),
                        telemetry_path=None, telemetry_run_id=None, policy_path=policy_path,
                        release_for_final_retry=lambda: {"released_record_count": 0},
                    )
            self.assertEqual(len(list((checkpoint_parent / ".checkpoint-deferrals").glob("*.json"))), 1)

    def test_non_final_boundary_keeps_todays_single_attempt_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            config_path, policy_path = self._config_and_policy(directory, max_deferrals=3, max_distance=2000)
            checkpoint_parent = directory / "checkpoints"
            state: dict[str, int] = {"count": 0}
            with patch.object(
                checkpoint_artifacts, "available_host_commit_bytes",
                side_effect=[_INCIDENT_FIRST_LOW_BYTES],
            ) as probe:
                result = run_vertical_slice._publish_checkpoint_with_low_commit_deferral(
                    checkpoint_parent=checkpoint_parent, config_path=config_path, global_step=100,
                    last_checkpointed_step=0, deferral_state=state, publish=self._probe_bound_publish(),
                    telemetry_path=None, telemetry_run_id=None, policy_path=policy_path,
                )
            self.assertIsNone(result)
            self.assertEqual(probe.call_count, 1)
            self.assertEqual(state["count"], 1)
            receipts = list((checkpoint_parent / ".checkpoint-deferrals").glob("*.json"))
            self.assertEqual(len(receipts), 1)
            receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
            self.assertNotIn("retry_observed_commit_bytes", receipt)
            self.assertNotIn("retry_required_commit_bytes", receipt)
            self.assertNotIn("released_record_count", receipt)

    def test_release_helper_frees_gradients_and_aliased_record_dicts(self) -> None:
        import torch

        records = [{"token_ids": [1], "payload": "y" * 32} for _ in range(4)]
        segment_view = list(records)
        scene_split_view = [records[0], records[2]]
        model = torch.nn.Linear(2, 2)
        model(torch.ones(1, 2)).sum().backward()
        self.assertTrue(any(parameter.grad is not None for parameter in model.parameters()))
        evidence = run_vertical_slice._release_final_publication_ballast(records, model=model)
        self.assertEqual(evidence, {"released_record_count": 4})
        # Gradients are the several-GiB structural ballast in production and are
        # never part of any checkpoint artifact; parameters stay untouched.
        self.assertTrue(all(parameter.grad is None for parameter in model.parameters()))
        self.assertEqual(records, [])
        self.assertTrue(all(record == {} for record in segment_view))
        self.assertTrue(all(record == {} for record in scene_split_view))

    def test_run_wires_release_only_at_the_final_boundary_and_keeps_fatal_raise(self) -> None:
        source = inspect.getsource(run_vertical_slice.run)
        self.assertIn("segment_final_record_index", source)
        self.assertIn("release_for_final_retry=", source)
        self.assertIn("_release_final_publication_ballast(records, model=model)", source)
        self.assertIn('int(data_cursor["record_index"]) >= segment_final_record_index', source)
        # Today's fail-closed contract stays: a run whose retry also lands short
        # still ends in this exact raise.
        self.assertIn("training segment completed without a durable verified checkpoint", source)
        # The slice receipt (the only receipt input derived from record content)
        # is bound before the guarded publication that may release the records.
        self.assertLess(
            source.index("specialist_execution_slice_receipt("),
            source.index("_publish_checkpoint_with_low_commit_deferral("),
        )

    def test_commit_guard_orders_before_serializer_work(self) -> None:
        """The reserve check runs before any staging directory or serializer
        allocation in the write path -- the deferral raise stays zero-byte."""
        source = inspect.getsource(checkpoint_artifacts._write_checkpoint_artifacts_impl)
        preflight_index = source.index("checkpoint_commit_preflight(")
        self.assertLess(preflight_index, source.index("root.mkdir()"))
        self.assertLess(preflight_index, source.index("model.state_dict()"))


class PublicationProjectionTeardownOrderingTests(unittest.TestCase):
    """#1473 verified at the bytes: the #1469 final-retry teardown frees
    gradients and record buffers ONLY -- optimizer moments, the storage
    projection's input, are checkpointable state the release never touches.
    The first pin fails if a future teardown extension starts freeing
    optimizer state ahead of the retried publication; the second pins the
    issue-title shape (publication against actually torn-down optimizer
    state) to the exact contract refusal."""

    def _vision_step_fixture(self) -> tuple[object, object, dict[str, object], dict[str, int]]:
        import torch
        from model import RestartDecoderConfig, UnifiedDecoder

        config = RestartDecoderConfig.small_for_tests(
            hidden_size=32, layers=2, attention_heads=4, vocab_size=64
        )
        model = UnifiedDecoder(config, genesis_seed=192)
        model._activate_expert("vision")
        optimizer = torch.optim.AdamW(
            (parameter for parameter in model.parameters() if parameter.requires_grad),
            lr=1e-4,
        )
        model(
            torch.tensor([[1, 2, 3]], dtype=torch.long),
            active_expert="vision",
        ).float().square().mean().backward()
        optimizer.step()
        optimizer_payload = {"optimizer": optimizer.state_dict()}
        floor = checkpoint_artifacts._unique_tensor_storage_bytes(optimizer_payload)
        bounds = {
            "shared-model.pt": 100,
            "optimizer-state.pt": floor,
            "replay-state.pt": 100,
            **{f"expert-{name}.pt": 100 for name in checkpoint_artifacts.EXPERT_NAMES},
        }
        return model, optimizer, optimizer_payload, bounds

    def _derive(self, model: object, optimizer: object, optimizer_payload: dict[str, object], bounds: dict[str, int]) -> dict[str, object]:
        return checkpoint_artifacts._derive_checkpoint_storage_projection(
            model=model,
            optimizer=optimizer,
            optimizer_file_payload=optimizer_payload,
            shard_storage_lower_bounds=bounds,
            shard_sha256={path: "a" * 64 for path in bounds},
            publication_modes={path: "written" for path in bounds},
            global_step=1,
            max_transient_scratch_bytes=1024**3,
            max_serialized_bytes=1024**3,
            specialist_parent_optimizer_routes=(),
        )

    def test_ballast_release_never_invalidates_projection_optimizer_inputs(self) -> None:
        model, optimizer, optimizer_payload, bounds = self._vision_step_fixture()
        routes_before = checkpoint_artifacts._optimizer_tensor_storage_by_route(model, optimizer)
        records = [{"token_ids": [1], "payload": "y" * 32} for _ in range(3)]

        run_vertical_slice._release_final_publication_ballast(records, model=model)

        self.assertEqual(records, [])
        self.assertTrue(all(parameter.grad is None for parameter in model.parameters()))
        self.assertEqual(
            checkpoint_artifacts._optimizer_tensor_storage_by_route(model, optimizer),
            routes_before,
        )
        projection = self._derive(model, optimizer, {"optimizer": optimizer.state_dict()}, bounds)
        self.assertEqual(projection["optimizer_state_active_expert_ids"], ["vision"])
        self.assertGreater(
            projection["optimizer_state_tensor_storage_lower_bound_bytes"], 0
        )

    def test_projection_rejects_actually_torn_down_optimizer_state(self) -> None:
        model, optimizer, _optimizer_payload, bounds = self._vision_step_fixture()
        optimizer.state.clear()
        bounds = {**bounds, "optimizer-state.pt": 0}
        with self.assertRaisesRegex(
            ValueError,
            "checkpoint storage projection requires one post-update optimizer state",
        ):
            self._derive(model, optimizer, {"optimizer": optimizer.state_dict()}, bounds)


if __name__ == "__main__":
    unittest.main()
