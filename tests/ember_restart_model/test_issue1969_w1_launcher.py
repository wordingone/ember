# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b" / "issue1969_w1_launcher.py"
SPEC_PATH = ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b" / "issue1969-w1-spec-v1.json"


def load_module():
    spec = importlib.util.spec_from_file_location("issue1969_w1_launcher", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _arm(route: str, *, median: float, pid: int, fused_calls: int) -> dict[str, object]:
    return {
        "schema_version": "c1-wave-rendered-owner-arm-v1",
        "result": "PASS",
        "route": route,
        "treatment_id": "5fb3065b7cfa44355db3a897f63b78f0f85d8b55d7455b9ed19b56ae99887dd0",
        "measurement_policy": "issue1946-arm-a",
        "identity": {
            "parameter_sha256": "a" * 64,
            "optimizer_initial_state_sha256": "b" * 64,
            "cpu_rng_state_sha256": "c" * 64,
            "cuda_rng_state_sha256": "d" * 64,
            "config_sha256": "e" * 64,
            "seed": 1945,
            "initial_cursor": 0,
            "selection_receipt_sha256": "f" * 64,
            "stream_manifest_sha256": "1" * 64,
            "stream_build_receipt_sha256": "2" * 64,
            "tokenizer_sha256": "3" * 64,
            "execution_record_order_sha256": "4" * 64,
            "execution_tokens_sha256": "5" * 64,
        },
        "dispatch_evidence": {
            "forward_fused_is_forward": route == "control",
            "fused_path_invocations": fused_calls,
            "shared_ffn_invocations": 64,
        },
        "warmup_update_seconds": [1.0, 1.0, 1.0, 1.0],
        "governed_nonprofiled_update_seconds": [median] * 40,
        "losses": [2.0, 1.9, 1.8, 1.7],
        "fallbacks": [],
        "memory": {"peak_reserved_bytes": 20 * 1024**3},
        "board_energy_joules_per_update": [100.0] * 4,
        "first_temperature_c": 50.0,
        "runtime_custody": {
            "process_id": pid,
            "gpu_uuid": "GPU-ISSUE1969",
            "fresh_process_and_cuda_context_required": True,
        },
        "additional_process_commit_peak_bytes": 20 * 1024**3,
        "base_receipt_raw_sha256": "6" * 64,
        "base_receipt_self_sha256": "7" * 64,
        "self_sha256": "8" * 64,
    }


def _resource(*, started: float = 100.0, finished: float = 200.0) -> dict[str, object]:
    return {
        "schema_version": 7,
        "outcome": "COMPLETED",
        "started_at_unix": started,
        "finished_at_unix": finished,
        "child_exit_code": 0,
        "runner_exit_code": 0,
        "file_max_concurrent_growth_bytes_by_drive": {"C": 0, "B": 1024},
        "operating_reserve_breaches": [],
        "root_scan_uncertainty": [],
        "child_cache_assertion_error": None,
        "unredirected_cache_roots": [],
    }


def _preflight() -> dict[str, object]:
    return {
        "schema_version": "c1-wave-rendered-owner-preflight-v1",
        "result": "PASS",
        "gates": {
            "protected_eval": {"result": "PASS", "raw_sha256": "9" * 64},
            "recovery": {"result": "PASS", "raw_sha256": "a" * 64},
            "rollback": {"result": "PASS", "raw_sha256": "b" * 64},
            "eager_fused_output_gradient_equivalence": {"result": "PASS"},
            "resource_go": {"result": "PASS", "raw_sha256": "c" * 64},
        },
        "self_sha256": "d" * 64,
    }


def test_spec_freezes_same_mode_threshold_and_resource_envelope() -> None:
    module = load_module()
    spec = module.load_spec(SPEC_PATH)
    assert spec["runner"]["control_mode"] == "issue1946-arm-a"
    assert spec["runner"]["treatment_mode"] == "issue1946-arm-a"
    assert spec["retention_rule"] == {
        "minimum_relative_improvement": 0.01,
        "mad_multiplier": 3.0,
        "mad_consistency_constant": 1.4826,
        "matched_loss_relative_tolerance_exclusive": 0.01,
    }
    assert spec["resource_envelope"]["wall_seconds_max"] == 1800
    assert spec["resource_envelope"]["peak_reserved_vram_bytes_max"] == 22 * 1024**3
    assert spec["resource_envelope"]["c_drive_writes_bytes_max"] == 0


def test_rejected_treatment_spec_refuses_post_rollback_source() -> None:
    module = load_module()
    with pytest.raises(ValueError, match=r"^SOURCE_BLOB_DRIFT:model$"):
        module.validate_source(ROOT, module.load_spec(SPEC_PATH))


def test_terminal_retains_only_above_frozen_control_noise_and_all_gates() -> None:
    module = load_module()
    receipt = module.build_terminal_receipt(
        control=_arm("control", median=1.0, pid=101, fused_calls=0),
        treatment=_arm("treatment", median=0.8, pid=202, fused_calls=64),
        preflight=_preflight(),
        control_resource=_resource(),
        treatment_resource=_resource(started=201.0, finished=301.0),
        spec=module.load_spec(SPEC_PATH),
        control_raw_sha256="e" * 64,
        treatment_raw_sha256="f" * 64,
        preflight_raw_sha256="0" * 64,
        control_resource_raw_sha256="1" * 64,
        treatment_resource_raw_sha256="2" * 64,
    )
    assert receipt["schema_version"] == "c1-wave-rendered-owner-v1"
    assert receipt["result"] == "RETAINED"
    assert receipt["frozen_R"] == pytest.approx(0.01)
    assert receipt["relative_median_improvement"] == pytest.approx(0.2)
    assert receipt["matched_loss_max_relative_delta"] == pytest.approx(0.0)
    assert receipt["all_required_gates_pass"] is True
    assert len(receipt["self_sha256"]) == 64


def test_below_threshold_is_terminal_rejected_without_retry() -> None:
    module = load_module()
    receipt = module.build_terminal_receipt(
        control=_arm("control", median=1.0, pid=101, fused_calls=0),
        treatment=_arm("treatment", median=0.995, pid=202, fused_calls=64),
        preflight=_preflight(),
        control_resource=_resource(),
        treatment_resource=_resource(started=201.0, finished=301.0),
        spec=module.load_spec(SPEC_PATH),
        control_raw_sha256="e" * 64,
        treatment_raw_sha256="f" * 64,
        preflight_raw_sha256="0" * 64,
        control_resource_raw_sha256="1" * 64,
        treatment_resource_raw_sha256="2" * 64,
    )
    assert receipt["result"] == "REJECTED"
    assert receipt["retry_or_tuning_authorized"] is False


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (lambda c, t: t.update(measurement_policy="issue1946-arm-b"), "MEASUREMENT_POLICY_DRIFT"),
        (lambda c, t: t["runtime_custody"].update(process_id=101), "FRESH_PROCESS_REQUIRED"),
        (lambda c, t: c["dispatch_evidence"].update(forward_fused_is_forward=False), "CONTROL_PATCH_NOT_PROVEN"),
        (lambda c, t: c["dispatch_evidence"].update(fused_path_invocations=1), "CONTROL_FUSED_DISPATCH_OBSERVED"),
        (lambda c, t: t["dispatch_evidence"].update(fused_path_invocations=0), "TREATMENT_FUSED_DISPATCH_MISSING"),
        (lambda c, t: t["memory"].update(peak_reserved_bytes=22 * 1024**3 + 1), "VRAM_CAP_EXCEEDED"),
        (lambda c, t: t.update(additional_process_commit_peak_bytes=25769803777), "PROCESS_COMMIT_CAP_EXCEEDED"),
    ],
)
def test_planted_reds_refuse_drift_and_silent_control_patch_failure(mutation, error: str) -> None:
    module = load_module()
    control = _arm("control", median=1.0, pid=101, fused_calls=0)
    treatment = _arm("treatment", median=0.8, pid=202, fused_calls=64)
    mutation(control, treatment)
    with pytest.raises(ValueError, match=error):
        module.build_terminal_receipt(
            control=control,
            treatment=treatment,
            preflight=_preflight(),
            control_resource=_resource(),
            treatment_resource=_resource(started=201.0, finished=301.0),
            spec=module.load_spec(SPEC_PATH),
            control_raw_sha256="e" * 64,
            treatment_raw_sha256="f" * 64,
            preflight_raw_sha256="0" * 64,
            control_resource_raw_sha256="1" * 64,
            treatment_resource_raw_sha256="2" * 64,
        )


def test_terminal_refuses_actual_disk_budget_breach() -> None:
    module = load_module()
    resource = _resource()
    resource["file_max_concurrent_growth_bytes_by_drive"]["C"] = 1
    with pytest.raises(ValueError, match="C_WRITE_CAP_EXCEEDED"):
        module.build_terminal_receipt(
            control=_arm("control", median=1.0, pid=101, fused_calls=0),
            treatment=_arm("treatment", median=0.8, pid=202, fused_calls=64),
            preflight=_preflight(),
            control_resource=resource,
            treatment_resource=_resource(started=201.0, finished=301.0),
            spec=module.load_spec(SPEC_PATH),
            control_raw_sha256="e" * 64,
            treatment_raw_sha256="f" * 64,
            preflight_raw_sha256="0" * 64,
            control_resource_raw_sha256="1" * 64,
            treatment_resource_raw_sha256="2" * 64,
        )


def test_terminal_refuses_reordered_or_thermally_unmatched_arms() -> None:
    module = load_module()
    common = {
        "control": _arm("control", median=1.0, pid=101, fused_calls=0),
        "treatment": _arm("treatment", median=0.8, pid=202, fused_calls=64),
        "preflight": _preflight(),
        "control_resource": _resource(started=200.0, finished=300.0),
        "treatment_resource": _resource(started=100.0, finished=199.0),
        "spec": module.load_spec(SPEC_PATH),
        "control_raw_sha256": "e" * 64,
        "treatment_raw_sha256": "f" * 64,
        "preflight_raw_sha256": "0" * 64,
        "control_resource_raw_sha256": "1" * 64,
        "treatment_resource_raw_sha256": "2" * 64,
    }
    with pytest.raises(ValueError, match="ARM_ORDER_INVALID"):
        module.build_terminal_receipt(**common)
    common["control_resource"] = _resource()
    common["treatment_resource"] = _resource(started=201.0, finished=301.0)
    common["treatment"]["first_temperature_c"] = 52.1
    with pytest.raises(ValueError, match="THERMAL_REBASE_FAILED"):
        module.build_terminal_receipt(**common)


def test_no_overwrite_terminal_writer(tmp_path: Path) -> None:
    module = load_module()
    output = tmp_path / "terminal.json"
    module.write_json_no_replace(output, {"result": "REJECTED"})
    with pytest.raises(FileExistsError, match="OUTPUT_EXISTS_REFUSED"):
        module.write_json_no_replace(output, {"result": "RETAINED"})
    assert json.loads(output.read_text(encoding="utf-8"))["result"] == "REJECTED"
