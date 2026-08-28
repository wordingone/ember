# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from issue1946_complete_update_profile import (  # noqa: E402
    build_arm_receipt,
    build_comparison_receipt,
    build_oom_arm_receipt,
    build_preflight_receipt,
    gpu_covariate,
    load_accounting_spec,
    load_authority_crosswalk,
    validate_arm_a_receipt,
    validate_preflight_receipt,
    verified_execution_source_commit,
)


def _self_hash(receipt: dict[str, object]) -> str:
    unsigned = dict(receipt)
    claimed = str(unsigned.pop("self_sha256"))
    canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert claimed == hashlib.sha256(canonical).hexdigest()
    return claimed


def _with_runtime_custody(
    receipt: dict[str, object], *, process_id: int, gpu_uuid: str = "GPU-bound"
) -> dict[str, object]:
    receipt.pop("self_sha256")
    receipt["runtime_custody"] = {
        "process_id": process_id,
        "fresh_process_and_cuda_context_required": True,
        "gpu_uuid": gpu_uuid,
        "preflight_raw_sha256": "7" * 64,
        "preflight_self_sha256": "8" * 64,
    }
    receipt["self_sha256"] = hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return receipt


def _raw_sha(receipt: dict[str, object]) -> str:
    raw = json.dumps(receipt, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    return hashlib.sha256(raw).hexdigest()


def _bind_arm_b(arm_b: dict[str, object], arm_a: dict[str, object]) -> dict[str, object]:
    arm_b.pop("self_sha256")
    custody = arm_b["runtime_custody"]
    custody["arm_a_raw_sha256"] = _raw_sha(arm_a)
    custody["arm_a_self_sha256"] = arm_a["self_sha256"]
    arm_b["self_sha256"] = hashlib.sha256(
        json.dumps(arm_b, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return arm_b


class Issue1946CompleteUpdateProfileTests(unittest.TestCase):
    def test_gpu_covariate_uses_the_real_driver_row(self) -> None:
        completed = Mock(returncode=0, stdout="GPU-uuid, 2505, 10501, 61, 311.5, 21000, 24564\n", stderr="")
        with patch("issue1946_complete_update_profile.subprocess.run", return_value=completed) as invoke:
            row = gpu_covariate()
        self.assertEqual(row["gpu_uuid"], "GPU-uuid")
        self.assertEqual(row["temperature_c"], 61.0)
        self.assertEqual(row["power_w"], 311.5)
        self.assertFalse(invoke.call_args.kwargs["shell"])

    def test_execution_source_requires_exact_clean_tracked_head(self) -> None:
        head = Mock(returncode=0, stdout="a" * 40 + "\n", stderr="")
        clean = Mock(returncode=0, stdout="", stderr="")
        with patch(
            "issue1946_complete_update_profile.subprocess.run",
            side_effect=[head, clean],
        ) as invoke:
            self.assertEqual(verified_execution_source_commit(ROOT, "a" * 40), "a" * 40)
        self.assertEqual(invoke.call_args_list[0].args[0][-2:], ["rev-parse", "HEAD"])
        self.assertEqual(
            invoke.call_args_list[1].args[0][-3:],
            ["status", "--porcelain", "--untracked-files=no"],
        )

        with patch(
            "issue1946_complete_update_profile.subprocess.run",
            return_value=Mock(returncode=0, stdout="b" * 40 + "\n", stderr=""),
        ):
            with self.assertRaisesRegex(ValueError, "does not match repo HEAD"):
                verified_execution_source_commit(ROOT, "a" * 40)

        dirty = Mock(returncode=0, stdout=" M tools/ember-restart-3b/pretrain.py\n", stderr="")
        with patch(
            "issue1946_complete_update_profile.subprocess.run",
            side_effect=[head, dirty],
        ):
            with self.assertRaisesRegex(ValueError, "tracked or index drift"):
                verified_execution_source_commit(ROOT, "a" * 40)

    def test_accounting_spec_is_closed_and_audio64_bound(self) -> None:
        path = ROOT / "tools" / "ember-restart-3b" / "issue1946-complete-update-accounting.json"
        spec = load_accounting_spec(path)
        self.assertEqual(spec["authority"]["workstream_id"], "EMBER-02B")
        self.assertEqual(spec["numerator"]["tokens_per_update"], 960)
        self.assertEqual(spec["route"], {"pack_records": 64, "selected_record_count": 4096, "warmup_updates": 16, "measured_updates": 48, "profiler_updates": 8})
        self.assertEqual(spec["denominator"]["opens_before"], ["data_readiness", "reference_forward"])
        self.assertEqual(spec["denominator"]["closes_after"], ["optimizer", "mandatory_synchronization", "telemetry", "charged_checkpoint"])
        stripped = json.loads(path.read_text(encoding="utf-8"))
        stripped.pop("authority")
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "accounting.json"
            candidate.write_text(json.dumps(stripped), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "closed #1946"):
                load_accounting_spec(candidate)

    def test_authority_crosswalk_reopens_every_historical_input_by_raw_hash(self) -> None:
        path = ROOT / "tools" / "ember-restart-3b" / "issue1946-authority-crosswalk.json"
        crosswalk = load_authority_crosswalk(ROOT, path)
        self.assertEqual(crosswalk["authority"]["workstream_id"], "EMBER-02B")
        self.assertEqual(
            {row["role"] for row in crosswalk["artifacts"]},
            {"fp33_profiler", "c04_muon_bf16ns5_qat", "eager_compile", "cuda_graph", "r1_e8", "energy"},
        )
        self.assertTrue(all(len(row["raw_sha256"]) == 64 for row in crosswalk["artifacts"]))
        stripped = json.loads(path.read_text(encoding="utf-8"))
        stripped.pop("authority")
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "crosswalk.json"
            candidate.write_text(json.dumps(stripped), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "closed #1946"):
                load_authority_crosswalk(ROOT, candidate)

    def test_preflight_requires_all_instruments_and_charged_stall(self) -> None:
        receipt = build_preflight_receipt(
            identity={"execution_source_commit": "a" * 40, "accounting_spec_sha256": "b" * 64},
            update_seconds=0.31,
            phase_seconds={"data_readiness": 0.11, "reference_forward": 0.01, "forward": 0.04, "backward": 0.08, "gradient_clipping": 0.01, "optimizer": 0.03, "mandatory_synchronization": 0.01, "telemetry_checkpoint": 0.015, "explicit_remainder": 0.005},
            injected_data_stall_seconds=0.1,
            instruments={name: {"status": "PASS"} for name in ("profiler", "allocator", "power", "event", "identity", "receipt")},
        )
        self.assertEqual(receipt["result"], "PASS")
        _self_hash(receipt)
        with self.assertRaisesRegex(ValueError, "data-stall"):
            build_preflight_receipt(
                identity={"execution_source_commit": "a" * 40, "accounting_spec_sha256": "b" * 64},
                update_seconds=0.2,
                phase_seconds={"data_readiness": 0.09},
                injected_data_stall_seconds=0.1,
                instruments={name: {"status": "PASS"} for name in ("profiler", "allocator", "power", "event", "identity", "receipt")},
            )

    def test_preflight_and_arm_a_receipts_gate_the_expensive_successors(self) -> None:
        instruments = {
            name: {"status": "PASS"}
            for name in ("profiler", "allocator", "power", "event", "identity", "receipt")
        }
        instruments["power"]["row"] = {"gpu_uuid": "GPU-bound"}
        preflight = build_preflight_receipt(
            identity={"execution_source_commit": "a" * 40, "accounting_spec_sha256": "b" * 64},
            update_seconds=0.31,
            phase_seconds={"data_readiness": 0.11, "reference_forward": 0.01, "forward": 0.04, "backward": 0.08, "gradient_clipping": 0.01, "optimizer": 0.03, "mandatory_synchronization": 0.01, "telemetry_checkpoint": 0.015, "explicit_remainder": 0.005},
            injected_data_stall_seconds=0.1,
            instruments=instruments,
        )
        preflight.pop("self_sha256")
        preflight["complete_update_timing_boundary"] = {
            "data_readiness_mode": "STREAMED_INSIDE_GOVERNED_WALL",
        }
        preflight["self_sha256"] = hashlib.sha256(
            json.dumps(preflight, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        validated = validate_preflight_receipt(
            preflight,
            execution_source_commit="a" * 40,
            accounting_spec_sha256="b" * 64,
            gpu_uuid="GPU-bound",
        )
        self.assertEqual(validated["identity"]["execution_source_commit"], "a" * 40)
        with self.assertRaisesRegex(ValueError, "execution source"):
            validate_preflight_receipt(
                preflight,
                execution_source_commit="c" * 40,
                accounting_spec_sha256="b" * 64,
                gpu_uuid="GPU-bound",
            )

        arm_a = self._arm("WHOLE_LAYER_RECOMPUTE", 0.20, 60.0)
        validated_arm = validate_arm_a_receipt(
            arm_a,
            execution_source_commit="a" * 40,
            gpu_uuid="GPU-bound",
            current_process_id=999,
        )
        self.assertEqual(validated_arm["runtime_custody"]["process_id"], 101)
        with self.assertRaisesRegex(ValueError, "distinct positive"):
            validate_arm_a_receipt(
                arm_a,
                execution_source_commit="a" * 40,
                gpu_uuid="GPU-bound",
                current_process_id=101,
            )

    @staticmethod
    def _arm(policy: str, measured_seconds: float, temperature: float) -> dict[str, object]:
        timings = [0.2] * 16 + [measured_seconds] * 48
        weights = {"data_readiness": 0.05, "reference_forward": 0.05, "forward": 0.15, "backward": 0.45, "gradient_clipping": 0.05, "optimizer": 0.15, "mandatory_synchronization": 0.025, "telemetry_checkpoint": 0.05, "explicit_remainder": 0.025}
        phases = [{name: seconds * fraction for name, fraction in weights.items()} for seconds in timings]
        receipt = build_arm_receipt(
            policy=policy,
            identity={"execution_source_commit": "a" * 40, "parameter_sha256": "b" * 64, "optimizer_initial_state_sha256": "e" * 64, "cpu_rng_state_sha256": "f" * 64, "cuda_rng_state_sha256": "1" * 64, "config_sha256": "2" * 64, "seed": 1946, "initial_cursor": 0, "selection_receipt_sha256": "c" * 64},
            update_seconds=timings,
            phase_seconds=phases,
            profiler_update_indexes=list(range(16, 24)),
            allocator_rows=[{"allocated": 10, "reserved": 12, "workspace": 1, "graph_pool": 0, "fragmentation": 2}] * 64,
            power_rows=[{"temperature_c": temperature, "power_w": 300.0, "sm_clock_mhz": 2500, "memory_clock_mhz": 10500}] * 64,
            kernel_trace={"sha256": "d" * 64, "layer_count": 42, "material_linear_shapes": [[64, 15, 4096, 16384]], "observed_kernels": [{"kernel": "gemm"}]},
        )
        process_id = 101 if policy == "WHOLE_LAYER_RECOMPUTE" else 102
        return _with_runtime_custody(receipt, process_id=process_id)

    def test_arm_and_comparison_freeze_exact_counts_r_and_identity(self) -> None:
        arm_a = self._arm("WHOLE_LAYER_RECOMPUTE", 0.20, 60.0)
        arm_b = self._arm("DISABLED_EVERY_LAYER", 0.15, 61.0)
        _bind_arm_b(arm_b, arm_a)
        self.assertEqual(arm_a["counts"], {"complete_updates": 64, "warmup": 16, "measured": 48, "profiler": 8})
        self.assertGreaterEqual(arm_a["attribution_fraction_min"], 0.99)
        self.assertEqual(arm_a["recomputed_layer_forwards"], 64 * 42)
        self.assertEqual(len(arm_a["identity"]["optimizer_initial_state_sha256"]), 64)
        self.assertEqual(len(arm_a["identity"]["cpu_rng_state_sha256"]), 64)
        self.assertEqual(len(arm_a["identity"]["cuda_rng_state_sha256"]), 64)
        self.assertEqual(arm_b["recomputed_layer_forwards"], 0)
        self.assertEqual(arm_a["applied_decoder_target_tokens_per_update"], 960)
        self.assertIn("board_energy_joules_per_update", arm_a)
        self.assertIn("implied_20k_required_tflops", arm_a)
        comparison = build_comparison_receipt(arm_a, arm_b, arm_a_raw_sha256=_raw_sha(arm_a))
        self.assertAlmostEqual(comparison["relative_median_improvement"], 0.25)
        self.assertEqual(comparison["frozen_R"], 0.01)
        self.assertEqual(comparison["result"], "PASS")
        self.assertIn("maximum_removable_milliseconds_by_owner", comparison["successor_input"])
        _self_hash(comparison)

    def test_all_off_oom_is_terminal_only_for_all_off_and_preserves_selective_successor(self) -> None:
        arm_a = self._arm("WHOLE_LAYER_RECOMPUTE", 0.20, 60.0)
        oom = build_oom_arm_receipt(
            identity=arm_a["identity"],
            completed_updates=3,
            peak_demand_bytes=25_000_000_000,
            ceiling_bytes=24_000_000_000,
            first_temperature_c=61.0,
            error_class="torch.OutOfMemoryError",
        )
        _with_runtime_custody(oom, process_id=102)
        _bind_arm_b(oom, arm_a)
        comparison = build_comparison_receipt(arm_a, oom, arm_a_raw_sha256=_raw_sha(arm_a))
        self.assertEqual(comparison["result"], "PASS")
        self.assertEqual(comparison["all_off_result"], "OOM")
        self.assertEqual(comparison["measured_vram_gap_bytes"], 1_000_000_000)
        self.assertEqual(comparison["successor_input"]["selective_recompute_study"], "C1-W1-RECOMPUTE-REMOVAL")
        self.assertFalse(comparison["successor_input"]["selective_recompute_adjudicated"])

    def test_comparison_refuses_same_process_or_unmatched_gpu_custody(self) -> None:
        arm_a = self._arm("WHOLE_LAYER_RECOMPUTE", 0.20, 60.0)
        arm_b = self._arm("DISABLED_EVERY_LAYER", 0.15, 61.0)

        _with_runtime_custody(arm_a, process_id=101, gpu_uuid="GPU-bound")
        _with_runtime_custody(arm_b, process_id=101, gpu_uuid="GPU-bound")
        _bind_arm_b(arm_b, arm_a)
        with self.assertRaisesRegex(ValueError, "fresh process"):
            build_comparison_receipt(arm_a, arm_b, arm_a_raw_sha256=_raw_sha(arm_a))
        _with_runtime_custody(arm_b, process_id=102, gpu_uuid="GPU-other")
        _bind_arm_b(arm_b, arm_a)
        with self.assertRaisesRegex(ValueError, "GPU UUID"):
            build_comparison_receipt(arm_a, arm_b, arm_a_raw_sha256=_raw_sha(arm_a))

    def test_comparison_refuses_substituted_arm_a_or_preflight_chain(self) -> None:
        arm_a = self._arm("WHOLE_LAYER_RECOMPUTE", 0.20, 60.0)
        arm_b = self._arm("DISABLED_EVERY_LAYER", 0.15, 61.0)
        _bind_arm_b(arm_b, arm_a)
        with self.assertRaisesRegex(ValueError, "exact Arm A"):
            build_comparison_receipt(arm_a, arm_b, arm_a_raw_sha256="9" * 64)

        arm_b.pop("self_sha256")
        arm_b["runtime_custody"]["preflight_raw_sha256"] = "6" * 64
        arm_b["self_sha256"] = hashlib.sha256(
            json.dumps(arm_b, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        with self.assertRaisesRegex(ValueError, "same exact preflight"):
            build_comparison_receipt(arm_a, arm_b, arm_a_raw_sha256=_raw_sha(arm_a))


if __name__ == "__main__":
    unittest.main()
