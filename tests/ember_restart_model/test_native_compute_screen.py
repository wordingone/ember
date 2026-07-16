# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Contract tests for the clean-genesis native full-step compute screen."""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from native_compute_screen import (
    _assert_source_closure_stable,
    _dispatch_binding,
    _power_efficiency,
    _power_sample,
    _validate_disk_preflight,
    _validate_schedule_receipt,
    disk_preflight_receipt,
    screen_plan,
    screen_receipt,
    write_disk_preflight,
    main,
)


class NativeComputeScreenTests(unittest.TestCase):
    @staticmethod
    def _valid_schedule_payload() -> dict[str, object]:
        now_ms = int(time.time() * 1000)
        identity = {"binary_sha256": "a" * 64, "source_sha256": "b" * 64}
        return {
            "schema_version": "emberd-schedule-alarm-state-v1",
            "generated_at_ms": now_ms,
            "emberd_identity": identity,
            "runs": [{
                "job_id": "ember-02b-native-clean-genesis-screen-b1-b2-seed83",
                "artifact_class": "compute-primitive",
                "predicted_tokens": 3072,
                "predicted_duration_ms": 720000,
                "predicted_at_ms": now_ms,
                "predicted_program_completion_ms": now_ms + 720000,
                "absolute_deadline_ms": now_ms + 720001,
                "prediction_daemon_identity": identity,
            }],
        }
    def test_same_run_power_trace_derives_board_energy_and_tok_per_joule(self) -> None:
        trace = {"sampling_cadence_s": 1.0, "started_monotonic_s": 0.0, "stopped_monotonic_s": 2.0, "missing_sample_count": 0, "errors": [], "samples": [{"monotonic_s": 0.5, "watts": 100.0, "power_limit_w": 250.0, "memory_used_mib": 12000.0, "driver_version": "1", "gpu_name": "GPU", "gpu_uuid": "GPU-abc", "gpu_index": 0}, {"monotonic_s": 1.5, "watts": 120.0, "power_limit_w": 250.0, "memory_used_mib": 13000.0, "driver_version": "1", "gpu_name": "GPU", "gpu_uuid": "GPU-abc", "gpu_index": 0}]}
        receipt = _power_efficiency(trace=trace, wall_s=2.0, tokens_processed=3072, active_parameters=1_020_589_568, total_parameters=3_839_161_856, allocator_peak_vram_bytes=13_000_000_000, target_vector_sha256="a" * 64, checkpoint_manifest_sha256="b" * 64)
        self.assertEqual(receipt["result"], "MEASURED")
        self.assertEqual(receipt["energy_scope"], "GPU_BOARD_ONLY")
        self.assertEqual(receipt["gpu_joules"], 220.0)
        self.assertGreater(receipt["tok_per_gpu_joule"], 0)
        self.assertEqual(receipt["gpu_uuid"], "GPU-abc")
        self.assertEqual(receipt["gpu_index"], 0)
        self.assertEqual(receipt["compute_dtype"], "torch.bfloat16")
        self.assertEqual(receipt["peak_flops"], 165e12)
        self.assertEqual(receipt["allocator_peak_vram_bytes"], 13_000_000_000)
        self.assertEqual(receipt["driver_peak_vram_bytes"], 13000 * 1024**2)
        self.assertGreater(receipt["mfu"], 0)
        self.assertIn("RTX_4090", receipt["peak_flops_provenance"])

    def test_power_measurement_below_coverage_floor_withholds_credit(self) -> None:
        trace = {"sampling_cadence_s": 1.0, "started_monotonic_s": 0.0, "stopped_monotonic_s": 2.0, "missing_sample_count": 0, "errors": [], "samples": [{"monotonic_s": 1.0, "watts": 100.0, "power_limit_w": 250.0, "memory_used_mib": 1.0, "driver_version": "1", "gpu_name": "GPU", "gpu_uuid": "GPU-abc", "gpu_index": 0}]}
        receipt = _power_efficiency(trace=trace, wall_s=2.0, tokens_processed=3072, active_parameters=1_020_589_568, total_parameters=3_839_161_856, allocator_peak_vram_bytes=1, target_vector_sha256="a" * 64, checkpoint_manifest_sha256="b" * 64)
        self.assertEqual(receipt["result"], "UNAVAILABLE")
        self.assertLess(receipt["coverage_ratio"], 0.9)
    def test_missing_same_run_power_samples_withholds_energy_credit(self) -> None:
        receipt = _power_efficiency(trace={"sampling_cadence_s": 1.0, "started_monotonic_s": 0.0, "stopped_monotonic_s": 2.0, "missing_sample_count": 1, "errors": ["missing"], "samples": []}, wall_s=2.0, tokens_processed=3072, active_parameters=1, total_parameters=2, allocator_peak_vram_bytes=1, target_vector_sha256="a" * 64, checkpoint_manifest_sha256="b" * 64)
        self.assertEqual(receipt["result"], "UNAVAILABLE")
        self.assertEqual(receipt["energy_scope"], "GPU_BOARD_ONLY")
    def test_temporal_gap_or_missing_trace_anchors_withholds_credit(self) -> None:
        common = {"watts": 100.0, "power_limit_w": 250.0, "memory_used_mib": 1.0, "driver_version": "1", "gpu_name": "GPU", "gpu_uuid": "GPU-abc", "gpu_index": 0}
        for trace in (
            {"sampling_cadence_s": 1.0, "missing_sample_count": 0, "errors": [], "samples": [{**common, "monotonic_s": 0.1}, {**common, "monotonic_s": 1.9}]},
            {"sampling_cadence_s": 1.0, "started_monotonic_s": 0.0, "stopped_monotonic_s": 4.0, "missing_sample_count": 0, "errors": [], "samples": [{**common, "monotonic_s": 0.1}, {**common, "monotonic_s": 3.9}]},
        ):
            receipt = _power_efficiency(trace=trace, wall_s=2.0, tokens_processed=10, active_parameters=2, total_parameters=4, allocator_peak_vram_bytes=1, target_vector_sha256="a" * 64, checkpoint_manifest_sha256="b" * 64)
            self.assertEqual(receipt["result"], "UNAVAILABLE")

    def test_driver_sample_binds_uuid_index_and_memory(self) -> None:
        completed = mock.Mock(returncode=0, stdout="GPU-abc, 0, 1234, 100, 250, 560.1, RTX 4090\n", stderr="")
        with mock.patch("native_compute_screen.subprocess.run", return_value=completed) as run:
            sample = _power_sample()
        query = run.call_args.args[0]
        self.assertIn("uuid,index,memory.used", query[1])
        self.assertEqual(sample["gpu_uuid"], "GPU-abc")
        self.assertEqual(sample["gpu_index"], 0)
        self.assertEqual(sample["memory_used_mib"], 1234.0)
    def test_plan_requires_the_two_full_step_arms_and_bounds_probe_arms(self) -> None:
        plan = screen_plan(total_vram_bytes=24 * 1024**3)

        self.assertEqual(plan["sequence_length"], 1024)
        self.assertEqual(plan["required_batches"], [1, 2])
        self.assertEqual(plan["memory_gate_only_batches"], [4, 8])
        self.assertEqual(plan["max_peak_allocated_bytes"], int(24 * 1024**3 * 0.8))
        self.assertEqual(plan["minimum_free_margin_bytes"], int(1.5 * 1024**3))

    def test_receipt_rejects_a_measurement_above_the_vram_governor(self) -> None:
        with self.assertRaisesRegex(MemoryError, "0.8 VRAM governor"):
            screen_receipt(
                model_config_sha256="a" * 64,
                optimizer_contract_sha256="b" * 64,
                tokenizer_sha256="c" * 64,
                checkpoint_manifest_sha256="d" * 64,
                source_sha256="e" * 64,
                total_vram_bytes=24 * 1024**3,
                batch_measurements=[
                    {"batch_size": 1, "elapsed_seconds": 1.0, "peak_allocated_bytes": int(24 * 1024**3 * 0.8) + 1, "peak_reserved_bytes": 1}
                ],
            )

    def test_receipt_rejects_peak_that_leaves_less_than_the_required_free_margin(self) -> None:
        total = 24 * 1024**3
        with self.assertRaisesRegex(MemoryError, "1.5 GiB"):
            screen_receipt(
                model_config_sha256="a" * 64,
                optimizer_contract_sha256="b" * 64,
                tokenizer_sha256="c" * 64,
                checkpoint_manifest_sha256="d" * 64,
                source_sha256="e" * 64,
                total_vram_bytes=total,
                available_vram_bytes=int(total * 0.75) + 1024**3,
                batch_measurements=[
                    {"batch_size": 1, "elapsed_seconds": 1.0, "peak_allocated_bytes": int(total * 0.75), "peak_reserved_bytes": int(total * 0.75)},
                    {"batch_size": 2, "elapsed_seconds": 1.0, "peak_allocated_bytes": int(total * 0.75), "peak_reserved_bytes": int(total * 0.75)},
                ],
            )
    def test_receipt_rejects_missing_required_batch_two(self) -> None:
        with self.assertRaisesRegex(ValueError, "batch-1 then batch-2"):
            screen_receipt(
                model_config_sha256="a" * 64, optimizer_contract_sha256="b" * 64,
                tokenizer_sha256="c" * 64, checkpoint_manifest_sha256="d" * 64,
                source_sha256="e" * 64, total_vram_bytes=24 * 1024**3,
                batch_measurements=[{"batch_size": 1, "elapsed_seconds": 1.0, "peak_allocated_bytes": 10, "peak_reserved_bytes": 11}],
            )
    def test_receipt_rejects_missing_runtime_source_schedule_and_disk_custody(self) -> None:
        with self.assertRaisesRegex(ValueError, "custody"):
            screen_receipt(
                model_config_sha256="a" * 64,
                optimizer_contract_sha256="b" * 64,
                tokenizer_sha256="c" * 64,
                checkpoint_manifest_sha256="d" * 64,
                source_sha256="e" * 64,
                total_vram_bytes=24 * 1024**3,
                available_vram_bytes=23 * 1024**3,
                batch_measurements=[
                    {"batch_size": 1, "elapsed_seconds": 1.0, "peak_allocated_bytes": 10, "peak_reserved_bytes": 11},
                    {"batch_size": 2, "elapsed_seconds": 1.0, "peak_allocated_bytes": 12, "peak_reserved_bytes": 13},
                ],
                custody={},
            )
    def test_external_custody_rejects_wrong_schedule_job_and_disk_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            schedule = root / "schedule.json"
            payload = self._valid_schedule_payload(); payload["runs"][0]["job_id"] = "other"; schedule.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "native B1/B2"):
                _validate_schedule_receipt(schedule)
            disk = root / "disk.json"
            disk.write_text(json.dumps({"schema_version": "ember-native-screen-disk-preflight-v1", "job_id": "ember-02b-native-clean-genesis-screen-b1-b2-seed83", "result": "PASSED", "max_b_write_gib": 1.0, "max_c_write_gib": 0.1, "operating_floors_gib": {"B": 250.0, "C": 150.0}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "approved B/C"):
                _validate_disk_preflight(disk)
    def test_schedule_rejects_wrong_duration_and_missing_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.json"
            payload = self._valid_schedule_payload()
            payload["runs"][0]["predicted_duration_ms"] = 1
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "native B1/B2"):
                _validate_schedule_receipt(path)
            payload = self._valid_schedule_payload()
            del payload["runs"][0]["absolute_deadline_ms"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "timestamps and deadline"):
                _validate_schedule_receipt(path)
    def test_schedule_rejects_missing_prediction_identity_and_deadline_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.json"
            payload = self._valid_schedule_payload()
            del payload["runs"][0]["prediction_daemon_identity"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "prediction identity"):
                _validate_schedule_receipt(path)

    def test_schedule_rejects_a_prediction_whose_deadline_has_elapsed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.json"
            payload = self._valid_schedule_payload()
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "deadline has elapsed"):
                _validate_schedule_receipt(path, now_ms=payload["runs"][0]["absolute_deadline_ms"])

    def test_schedule_rejects_prediction_issued_beyond_bounded_future_clock_skew(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.json"
            payload = self._valid_schedule_payload()
            now_ms = payload["runs"][0]["predicted_at_ms"]
            future_ms = now_ms + 60_001
            payload["generated_at_ms"] = future_ms
            payload["runs"][0]["predicted_at_ms"] = future_ms
            payload["runs"][0]["predicted_program_completion_ms"] = future_ms + 720000
            payload["runs"][0]["absolute_deadline_ms"] = future_ms + 720001
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "future clock skew"):
                _validate_schedule_receipt(path, now_ms=now_ms)

    def test_schedule_accepts_a_live_prediction_within_the_issued_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.json"
            payload = self._valid_schedule_payload()
            path.write_text(json.dumps(payload), encoding="utf-8")
            binding = _validate_schedule_receipt(path, now_ms=payload["runs"][0]["predicted_at_ms"])
            self.assertEqual(binding["absolute_deadline_ms"], payload["runs"][0]["absolute_deadline_ms"])
    def test_disk_preflight_persists_the_canonical_output_bound_dispatch(self) -> None:
        closure = {name: "c" * 64 for name in ("model.py", "batch.py", "semantic_stream.py", "run_vertical_slice.py", "parameter_counter.py", "native_compute_screen.py")}
        dispatch = _dispatch_binding(output=Path("B:/receipts/screen.json"), seed=83)
        receipt = disk_preflight_receipt(
            free_bytes_by_drive={"B": 251 * 1024**3, "C": 151 * 1024**3},
            source_closure_sha256=closure,
            emberd_schedule_receipt_sha256="a" * 64,
            dispatch_sha256=dispatch["sha256"],
            dispatch=dispatch["payload"],
        )
        self.assertEqual(receipt["dispatch"], dispatch["payload"])
        self.assertEqual(receipt["dispatch_sha256"], dispatch["sha256"])
    def test_disk_preflight_rejects_a_different_dispatch_fingerprint(self) -> None:
        closure = {name: "c" * 64 for name in ("model.py", "batch.py", "semantic_stream.py", "run_vertical_slice.py", "parameter_counter.py", "native_compute_screen.py")}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preflight.json"
            path.write_text(json.dumps(disk_preflight_receipt(
                free_bytes_by_drive={"B": 251 * 1024**3, "C": 151 * 1024**3},
                source_closure_sha256=closure,
                emberd_schedule_receipt_sha256="a" * 64,
                dispatch_sha256=_dispatch_binding(output=Path("B:/receipts/screen.json"), seed=83)["sha256"],
                dispatch=_dispatch_binding(output=Path("B:/receipts/screen.json"), seed=83)["payload"],
            )), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "dispatch"):
                _validate_disk_preflight(path, expected_dispatch_sha256="e" * 64)
    def test_receipt_rejects_noncanonical_hash_or_empty_runtime_identity(self) -> None:
        custody = {
            "hardware_runtime": {"gpu_name": "", "compute_capability": "8.9", "torch_version": "x", "cuda_version": "x", "cudnn_version": "x", "optimizer_implementation": "x", "optimizer_version": "x"},
            "source_closure_sha256": {name: "F" * 64 for name in ("model.py", "batch.py", "semantic_stream.py", "run_vertical_slice.py", "parameter_counter.py", "native_compute_screen.py")},
            "emberd_schedule_receipt_sha256": "a" * 64,
            "disk_budget_receipt_sha256": "b" * 64,
        }
        with self.assertRaisesRegex(ValueError, "runtime identity|hash|source closure"):
            screen_receipt(model_config_sha256="a" * 64, optimizer_contract_sha256="b" * 64, tokenizer_sha256="c" * 64, checkpoint_manifest_sha256="d" * 64, source_sha256="e" * 64, total_vram_bytes=24 * 1024**3, custody=custody, batch_measurements=[{"batch_size": 1, "elapsed_seconds": 1.0, "peak_allocated_bytes": 10, "peak_reserved_bytes": 11}, {"batch_size": 2, "elapsed_seconds": 1.0, "peak_allocated_bytes": 12, "peak_reserved_bytes": 13}])
    def test_receipt_rejects_an_empty_runtime_identity_with_valid_other_custody(self) -> None:
        custody = {
            "hardware_runtime": {"gpu_name": "", "compute_capability": "8.9", "torch_version": "x", "cuda_version": "x", "cudnn_version": "x", "optimizer_implementation": "x", "optimizer_version": "x"},
            "source_closure_sha256": {name: "f" * 64 for name in ("model.py", "batch.py", "semantic_stream.py", "run_vertical_slice.py", "parameter_counter.py", "native_compute_screen.py")},
            "emberd_schedule_receipt_sha256": "a" * 64,
            "disk_budget_receipt_sha256": "b" * 64,
        }
        with self.assertRaisesRegex(ValueError, "runtime identity"):
            screen_receipt(
                model_config_sha256="a" * 64,
                optimizer_contract_sha256="b" * 64,
                tokenizer_sha256="c" * 64,
                checkpoint_manifest_sha256="d" * 64,
                source_sha256="e" * 64,
                total_vram_bytes=24 * 1024**3,
                custody=custody,
                batch_measurements=[{"batch_size": 1, "elapsed_seconds": 1.0, "peak_allocated_bytes": 10, "peak_reserved_bytes": 11}, {"batch_size": 2, "elapsed_seconds": 1.0, "peak_allocated_bytes": 12, "peak_reserved_bytes": 13}],
            )
    def test_receipt_binds_full_steps_and_native_identities(self) -> None:
        receipt = screen_receipt(
            model_config_sha256="a" * 64,
            optimizer_contract_sha256="b" * 64,
            tokenizer_sha256="c" * 64,
            checkpoint_manifest_sha256="d" * 64,
            source_sha256="e" * 64,
            total_vram_bytes=24 * 1024**3,
            custody={
                "hardware_runtime": {"gpu_name": "gpu", "compute_capability": "8.9", "torch_version": "x", "cuda_version": "x", "cudnn_version": "x", "optimizer_implementation": "x", "optimizer_version": "x"},
                "source_closure_sha256": {name: "f" * 64 for name in ("model.py", "batch.py", "semantic_stream.py", "run_vertical_slice.py", "parameter_counter.py", "native_compute_screen.py")},
                "emberd_schedule_receipt_sha256": "a" * 64,
                "disk_budget_receipt_sha256": "b" * 64,
            },
            batch_measurements=[
                {"batch_size": 1, "elapsed_seconds": 1.0, "peak_allocated_bytes": 10, "peak_reserved_bytes": 11},
                {"batch_size": 2, "elapsed_seconds": 2.0, "peak_allocated_bytes": 12, "peak_reserved_bytes": 13},
            ],
        )

        self.assertEqual(receipt["result"], "MEASURED")
        self.assertEqual(receipt["admission"], "NON_ADMISSIBLE_COMPUTE_PRIMITIVE")
        self.assertEqual(receipt["operation"], "CLEAN_GENESIS_FULL_FORWARD_BACKWARD_OPTIMIZER_STEP")
        self.assertEqual(receipt["sequence_length"], 1024)
        self.assertEqual([item["batch_size"] for item in receipt["steps"]], [1, 2])
        self.assertEqual(receipt["checkpoint_manifest_sha256"], "d" * 64)
        self.assertEqual(receipt["optimizer_contract_sha256"], "b" * 64)

    def test_disk_preflight_binds_schedule_source_and_projected_operating_floors(self) -> None:
        closure = {name: "c" * 64 for name in ("model.py", "batch.py", "semantic_stream.py", "run_vertical_slice.py", "parameter_counter.py", "native_compute_screen.py")}
        receipt = disk_preflight_receipt(
            free_bytes_by_drive={"B": 251 * 1024**3, "C": 151 * 1024**3},
            source_closure_sha256=closure,
            emberd_schedule_receipt_sha256="a" * 64,
            dispatch_sha256=_dispatch_binding(output=Path("B:/receipts/screen.json"), seed=83)["sha256"],
                dispatch=_dispatch_binding(output=Path("B:/receipts/screen.json"), seed=83)["payload"],
        )
        self.assertEqual(receipt["result"], "PASSED")
        self.assertEqual(receipt["projected_end_free_gib"], {"B": 250.9, "C": 150.9})
        self.assertEqual(receipt["source_closure_sha256"], closure)

    def test_disk_preflight_rejects_a_projected_operating_floor_breach(self) -> None:
        closure = {name: "c" * 64 for name in ("model.py", "batch.py", "semantic_stream.py", "run_vertical_slice.py", "parameter_counter.py", "native_compute_screen.py")}
        with self.assertRaisesRegex(ValueError, "operating floor"):
            disk_preflight_receipt(
                free_bytes_by_drive={"B": int(250.05 * 1024**3), "C": 151 * 1024**3},
                source_closure_sha256=closure,
                emberd_schedule_receipt_sha256="a" * 64,
            dispatch_sha256=_dispatch_binding(output=Path("B:/receipts/screen.json"), seed=83)["sha256"],
                dispatch=_dispatch_binding(output=Path("B:/receipts/screen.json"), seed=83)["payload"],
            )

    def test_main_can_emit_a_disk_preflight_without_entering_cuda_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            schedule = root / "schedule.json"
            schedule.write_text(json.dumps(self._valid_schedule_payload()), encoding="utf-8")
            output = root / "preflight.json"
            self.assertEqual(main(["--emit-disk-preflight", str(output), "--emberd-schedule-receipt", str(schedule), "--output", str(root / "screen.json"), "--seed", "83"]), 0)
            self.assertTrue(output.is_file())
    def test_write_disk_preflight_persists_the_exact_semantic_receipt(self) -> None:
        closure = {name: "c" * 64 for name in ("model.py", "batch.py", "semantic_stream.py", "run_vertical_slice.py", "parameter_counter.py", "native_compute_screen.py")}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preflight.json"
            receipt = write_disk_preflight(
                path=path,
                source_closure_sha256=closure,
                emberd_schedule_receipt_sha256="a" * 64,
            dispatch_sha256=_dispatch_binding(output=Path("B:/receipts/screen.json"), seed=83)["sha256"],
                dispatch=_dispatch_binding(output=Path("B:/receipts/screen.json"), seed=83)["payload"],
                free_bytes_by_drive={"B": 251 * 1024**3, "C": 151 * 1024**3},
            )
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), receipt)
    def test_source_closure_drift_is_rejected_before_receipt_publication(self) -> None:
        before = {"model.py": "a" * 64}
        with self.assertRaisesRegex(RuntimeError, "source closure changed"):
            _assert_source_closure_stable(before, {"model.py": "b" * 64})


if __name__ == "__main__":
    unittest.main()
