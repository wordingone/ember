# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed launcher and adjudicator for issue #1969's one rendered W1.

The two measured arms deliberately reuse the same reviewed ``issue1946-arm-a``
policy.  The control process locally aliases ``forward_fused`` to ``forward``;
the treatment process executes the merged fused route.  No training-path file
is edited and every output is no-overwrite.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import statistics
import sys
import time
from collections.abc import Mapping
from pathlib import Path

TREATMENT_ID = "5fb3065b7cfa44355db3a897f63b78f0f85d8b55d7455b9ed19b56ae99887dd0"
ARM_SCHEMA = "c1-wave-rendered-owner-arm-v1"
PREFLIGHT_SCHEMA = "c1-wave-rendered-owner-preflight-v1"
TERMINAL_SCHEMA = "c1-wave-rendered-owner-v1"
MEASUREMENT_POLICY = "issue1946-arm-a"
_SHA_CHARS = frozenset("0123456789abcdef")


def canonical_json(value: Mapping[str, object]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def canonical_self_json(value: Mapping[str, object]) -> bytes:
    """Match the predecessor runner's receipt self-hash convention."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in _SHA_CHARS for char in value):
        raise ValueError(f"{label}:SHA256_INVALID")
    return value


def _self_hashed(value: Mapping[str, object]) -> dict[str, object]:
    unsigned = dict(value)
    unsigned.pop("self_sha256", None)
    return {**unsigned, "self_sha256": sha256_bytes(canonical_self_json(unsigned))}


def _verify_self(value: Mapping[str, object], label: str) -> dict[str, object]:
    unsigned = dict(value)
    observed = unsigned.pop("self_sha256", None)
    if observed != sha256_bytes(canonical_self_json(unsigned)):
        raise ValueError(f"{label}:SELF_SHA256_INVALID")
    return dict(value)


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise TypeError(f"{path}:JSON_OBJECT_REQUIRED")
    return value


def load_spec(path: Path) -> dict[str, object]:
    value = _load_json(path)
    if value.get("schema_version") != "ember-issue1969-w1-launch-spec-v1":
        raise ValueError("SPEC_SCHEMA_INVALID")
    treatment = value.get("treatment")
    runner = value.get("runner")
    retention = value.get("retention_rule")
    resource = value.get("resource_envelope")
    if not isinstance(treatment, dict) or treatment.get("treatment_id") != TREATMENT_ID:
        raise ValueError("SPEC_TREATMENT_INVALID")
    if not isinstance(runner, dict) or runner.get("control_mode") != MEASUREMENT_POLICY or runner.get("treatment_mode") != MEASUREMENT_POLICY:
        raise ValueError("SPEC_SAME_MODE_REQUIRED")
    if runner.get("recompute_policy") != "WHOLE_LAYER_RECOMPUTE" or runner.get("order") != ["control", "treatment"]:
        raise ValueError("SPEC_RUNNER_DRIFT")
    expected_retention = {
        "minimum_relative_improvement": 0.01,
        "mad_multiplier": 3.0,
        "mad_consistency_constant": 1.4826,
        "matched_loss_relative_tolerance_exclusive": 0.01,
    }
    if retention != expected_retention:
        raise ValueError("SPEC_RETENTION_RULE_DRIFT")
    if not isinstance(resource, dict) or resource.get("wall_seconds_max") != 1800 or resource.get("c_drive_writes_bytes_max") != 0 or resource.get("peak_reserved_vram_bytes_max") != 22 * 1024**3:
        raise ValueError("SPEC_RESOURCE_ENVELOPE_DRIFT")
    if value.get("terminal_receipt_schema") != TERMINAL_SCHEMA or value.get("retry_or_tuning_authorized") is not False:
        raise ValueError("SPEC_TERMINAL_RULE_DRIFT")
    return value


def write_json_no_replace(path: Path, value: Mapping[str, object]) -> tuple[str, str | None]:
    raw = canonical_json(value)
    try:
        with path.open("xb") as handle:
            handle.write(raw)
    except FileExistsError as error:
        raise FileExistsError("OUTPUT_EXISTS_REFUSED") from error
    self_sha = value.get("self_sha256")
    return sha256_bytes(raw), str(self_sha) if isinstance(self_sha, str) else None


def _git_blob_sha1(path: Path) -> str:
    raw = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def validate_source(root: Path, spec: Mapping[str, object]) -> dict[str, str]:
    source = spec.get("source")
    if not isinstance(source, Mapping):
        raise TypeError("SPEC_SOURCE_INVALID")
    rows = {
        "model": (root / "tools/ember-restart-3b/model.py", source.get("treatment_model_blob")),
        "pretrain": (root / "tools/ember-restart-3b/pretrain.py", source.get("pretrain_blob")),
        "training_acceleration": (root / "tools/ember-restart-3b/training_acceleration.py", source.get("training_acceleration_blob")),
    }
    observed: dict[str, str] = {}
    for name, (path, expected) in rows.items():
        actual = _git_blob_sha1(path)
        if actual != expected:
            raise ValueError(f"SOURCE_BLOB_DRIFT:{name}")
        observed[name] = actual
    return observed


def _require_gate(preflight: Mapping[str, object], name: str) -> None:
    gates = preflight.get("gates")
    row = gates.get(name) if isinstance(gates, Mapping) else None
    if not isinstance(row, Mapping) or row.get("result") != "PASS":
        raise ValueError(f"PREFLIGHT_GATE_MISSING:{name}")


def _validate_arm(arm: Mapping[str, object], expected_route: str, spec: Mapping[str, object]) -> dict[str, object]:
    if arm.get("schema_version") != ARM_SCHEMA or arm.get("result") != "PASS" or arm.get("route") != expected_route:
        raise ValueError(f"ARM_INVALID:{expected_route}")
    if arm.get("treatment_id") != TREATMENT_ID:
        raise ValueError("TREATMENT_ID_DRIFT")
    if arm.get("measurement_policy") != MEASUREMENT_POLICY:
        raise ValueError("MEASUREMENT_POLICY_DRIFT")
    dispatch = arm.get("dispatch_evidence")
    if not isinstance(dispatch, Mapping):
        raise TypeError("DISPATCH_EVIDENCE_MISSING")
    fused_calls = dispatch.get("fused_path_invocations")
    if type(fused_calls) is not int or fused_calls < 0:
        raise ValueError("DISPATCH_COUNTER_INVALID")
    if expected_route == "control":
        if dispatch.get("forward_fused_is_forward") is not True:
            raise ValueError("CONTROL_PATCH_NOT_PROVEN")
        if fused_calls != 0:
            raise ValueError("CONTROL_FUSED_DISPATCH_OBSERVED")
    else:
        if dispatch.get("forward_fused_is_forward") is not False:
            raise ValueError("TREATMENT_ROUTE_NOT_PROVEN")
        if fused_calls < 1:
            raise ValueError("TREATMENT_FUSED_DISPATCH_MISSING")
    memory = arm.get("memory")
    resource = spec["resource_envelope"]
    if not isinstance(memory, Mapping) or type(memory.get("peak_reserved_bytes")) is not int:
        raise ValueError("MEMORY_EVIDENCE_INVALID")
    if int(memory["peak_reserved_bytes"]) > int(resource["peak_reserved_vram_bytes_max"]):
        raise ValueError("VRAM_CAP_EXCEEDED")
    commit_peak = arm.get("additional_process_commit_peak_bytes")
    if type(commit_peak) is not int or commit_peak < 0:
        raise ValueError("PROCESS_COMMIT_EVIDENCE_INVALID")
    if commit_peak > int(resource["additional_process_commit_bytes_max"]):
        raise ValueError("PROCESS_COMMIT_CAP_EXCEEDED")
    fallbacks = arm.get("fallbacks")
    if fallbacks != []:
        raise ValueError("FALLBACK_OBSERVED")
    energy = arm.get("board_energy_joules_per_update")
    if not isinstance(energy, list) or not energy or any(not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) < 0 for value in energy):
        raise ValueError("ENERGY_EVIDENCE_INVALID")
    first_temperature = arm.get("first_temperature_c")
    if not isinstance(first_temperature, (int, float)) or not math.isfinite(float(first_temperature)):
        raise ValueError("THERMAL_EVIDENCE_INVALID")
    for key in ("warmup_update_seconds", "governed_nonprofiled_update_seconds", "losses"):
        values = arm.get(key)
        if not isinstance(values, list) or not values or any(not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in values):
            raise ValueError(f"ARM_VECTOR_INVALID:{key}")
    custody = arm.get("runtime_custody")
    if not isinstance(custody, Mapping) or custody.get("fresh_process_and_cuda_context_required") is not True:
        raise ValueError("FRESH_PROCESS_REQUIRED")
    if type(custody.get("process_id")) is not int or int(custody["process_id"]) <= 0 or not custody.get("gpu_uuid"):
        raise ValueError("RUNTIME_CUSTODY_INVALID")
    return dict(arm)


def _validate_resource_receipt(value: Mapping[str, object], spec: Mapping[str, object], label: str) -> dict[str, object]:
    if value.get("schema_version") != 7 or value.get("outcome") != "COMPLETED":
        raise ValueError(f"{label}:RESOURCE_RECEIPT_INVALID")
    if value.get("child_exit_code") != 0 or value.get("runner_exit_code") != 0:
        raise ValueError(f"{label}:RESOURCE_CHILD_FAILED")
    started = value.get("started_at_unix")
    finished = value.get("finished_at_unix")
    if not isinstance(started, (int, float)) or not isinstance(finished, (int, float)) or finished < started:
        raise ValueError(f"{label}:RESOURCE_WALL_INVALID")
    if float(finished) - float(started) > float(spec["resource_envelope"]["wall_seconds_max"]):
        raise ValueError("WALL_CAP_EXCEEDED")
    growth = value.get("file_max_concurrent_growth_bytes_by_drive")
    if not isinstance(growth, Mapping) or type(growth.get("C")) is not int or type(growth.get("B")) is not int:
        raise ValueError(f"{label}:RESOURCE_WRITE_EVIDENCE_INVALID")
    if int(growth["C"]) > int(spec["resource_envelope"]["c_drive_writes_bytes_max"]):
        raise ValueError("C_WRITE_CAP_EXCEEDED")
    if int(growth["B"]) > int(spec["resource_envelope"]["b_drive_writes_bytes_max"]):
        raise ValueError("B_WRITE_CAP_EXCEEDED")
    if value.get("operating_reserve_breaches") != [] or value.get("root_scan_uncertainty") != []:
        raise ValueError(f"{label}:RESOURCE_SCAN_OR_RESERVE_FAILURE")
    if value.get("child_cache_assertion_error") is not None or value.get("unredirected_cache_roots") != []:
        raise ValueError(f"{label}:RESOURCE_CACHE_CUSTODY_FAILURE")
    return dict(value)


def build_terminal_receipt(
    *,
    control: Mapping[str, object],
    treatment: Mapping[str, object],
    preflight: Mapping[str, object],
    control_resource: Mapping[str, object],
    treatment_resource: Mapping[str, object],
    spec: Mapping[str, object],
    control_raw_sha256: str,
    treatment_raw_sha256: str,
    preflight_raw_sha256: str,
    control_resource_raw_sha256: str,
    treatment_resource_raw_sha256: str,
) -> dict[str, object]:
    left = _validate_arm(control, "control", spec)
    right = _validate_arm(treatment, "treatment", spec)
    left_resource = _validate_resource_receipt(control_resource, spec, "control")
    right_resource = _validate_resource_receipt(treatment_resource, spec, "treatment")
    if float(left_resource["finished_at_unix"]) > float(right_resource["started_at_unix"]):
        raise ValueError("ARM_ORDER_INVALID")
    if float(right["first_temperature_c"]) > float(left["first_temperature_c"]) + 2.0:
        raise ValueError("THERMAL_REBASE_FAILED")
    if preflight.get("schema_version") != PREFLIGHT_SCHEMA or preflight.get("result") != "PASS":
        raise ValueError("PREFLIGHT_INVALID")
    for name in spec["required_preflight_gates"]:
        _require_gate(preflight, str(name))
    left_custody = left["runtime_custody"]
    right_custody = right["runtime_custody"]
    if left_custody["process_id"] == right_custody["process_id"] or left_custody["gpu_uuid"] != right_custody["gpu_uuid"]:
        raise ValueError("FRESH_PROCESS_REQUIRED")
    if left.get("identity") != right.get("identity"):
        raise ValueError("ARM_IDENTITY_DRIFT")
    if left.get("measurement_policy") != right.get("measurement_policy"):
        raise ValueError("MEASUREMENT_POLICY_DRIFT")
    warmup = [float(value) for value in left["warmup_update_seconds"]]
    warmup_median = statistics.median(warmup)
    if warmup_median <= 0:
        raise ValueError("CONTROL_WARMUP_INVALID")
    mad = statistics.median(abs(value - warmup_median) for value in warmup)
    rule = spec["retention_rule"]
    frozen_r = max(
        float(rule["minimum_relative_improvement"]),
        float(rule["mad_multiplier"]) * float(rule["mad_consistency_constant"]) * mad / warmup_median,
    )
    control_median = statistics.median(float(value) for value in left["governed_nonprofiled_update_seconds"])
    treatment_median = statistics.median(float(value) for value in right["governed_nonprofiled_update_seconds"])
    if control_median <= 0 or treatment_median <= 0:
        raise ValueError("MEASURED_MEDIAN_INVALID")
    improvement = (control_median - treatment_median) / control_median
    control_losses = [float(value) for value in left["losses"]]
    treatment_losses = [float(value) for value in right["losses"]]
    if len(control_losses) != len(treatment_losses):
        raise ValueError("MATCHED_LOSS_VECTOR_DRIFT")
    loss_delta = max(abs(a - b) / max(abs(a), 1e-12) for a, b in zip(control_losses, treatment_losses, strict=True))
    matched_loss = loss_delta < float(rule["matched_loss_relative_tolerance_exclusive"])
    all_gates = matched_loss and improvement > frozen_r
    disposition = "RETAINED" if all_gates else "REJECTED"
    for value, label in (
        (control_raw_sha256, "control raw"),
        (treatment_raw_sha256, "treatment raw"),
        (preflight_raw_sha256, "preflight raw"),
        (control_resource_raw_sha256, "control resource raw"),
        (treatment_resource_raw_sha256, "treatment resource raw"),
    ):
        _require_sha(value, label)
    return _self_hashed({
        "schema_version": TERMINAL_SCHEMA,
        "result": disposition,
        "claim_boundary": spec["claim_boundary"],
        "treatment_id": TREATMENT_ID,
        "measurement_policy": MEASUREMENT_POLICY,
        "control_raw_sha256": control_raw_sha256,
        "treatment_raw_sha256": treatment_raw_sha256,
        "preflight_raw_sha256": preflight_raw_sha256,
        "control_resource_raw_sha256": control_resource_raw_sha256,
        "treatment_resource_raw_sha256": treatment_resource_raw_sha256,
        "control_self_sha256": left.get("self_sha256"),
        "treatment_self_sha256": right.get("self_sha256"),
        "preflight_self_sha256": preflight.get("self_sha256"),
        "frozen_R": frozen_r,
        "control_governed_median_seconds": control_median,
        "treatment_governed_median_seconds": treatment_median,
        "relative_median_improvement": improvement,
        "matched_loss_max_relative_delta": loss_delta,
        "all_required_gates_pass": all_gates,
        "dispatch_evidence": {
            "control": left["dispatch_evidence"],
            "treatment": right["dispatch_evidence"],
        },
        "resource_evidence": {
            "control_memory": left["memory"],
            "treatment_memory": right["memory"],
            "control_energy": left["board_energy_joules_per_update"],
            "treatment_energy": right["board_energy_joules_per_update"],
            "control_additional_process_commit_peak_bytes": left["additional_process_commit_peak_bytes"],
            "treatment_additional_process_commit_peak_bytes": right["additional_process_commit_peak_bytes"],
            "control_outer_budget": left_resource,
            "treatment_outer_budget": right_resource,
        },
        "preflight_gates": preflight["gates"],
        "retry_or_tuning_authorized": False,
    })


def _load_bound_receipt(path: Path, expected_raw: str, label: str) -> dict[str, object]:
    raw = path.read_bytes()
    if sha256_bytes(raw) != _require_sha(expected_raw, f"{label} raw"):
        raise ValueError(f"{label}:RAW_SHA256_MISMATCH")
    return _verify_self(json.loads(raw), label)


def _load_raw_bound_json(path: Path, expected_raw: str, label: str) -> dict[str, object]:
    raw = path.read_bytes()
    if sha256_bytes(raw) != _require_sha(expected_raw, f"{label} raw"):
        raise ValueError(f"{label}:RAW_SHA256_MISMATCH")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise TypeError(f"{label}:JSON_OBJECT_REQUIRED")
    return value


def _run_preflight(args: argparse.Namespace) -> dict[str, object]:
    if not args.live:
        raise ValueError("LIVE_AUTHORIZATION_REQUIRED")
    root = args.repo_root.resolve(strict=True)
    spec = load_spec(args.spec.resolve(strict=True))
    source_blobs = validate_source(root, spec)
    protected = _load_bound_receipt(args.protected_eval, args.protected_eval_raw_sha256, "protected_eval")
    recovery = _load_bound_receipt(args.recovery, args.recovery_raw_sha256, "recovery")
    resource_go = _load_bound_receipt(args.resource_go, args.resource_go_raw_sha256, "resource_go")
    for value, label in ((protected, "protected_eval"), (recovery, "recovery"), (resource_go, "resource_go")):
        if value.get("result", value.get("status")) != "PASS":
            raise ValueError(f"{label}:PASS_REQUIRED")
    module_root = root / "tools" / "ember-restart-3b"
    sys.path.insert(0, str(module_root))
    model_module = importlib.import_module("model")
    torch = importlib.import_module("torch")
    if not torch.cuda.is_available():
        raise ValueError("CUDA_REQUIRED")
    left_up = torch.randn(4, 16, device="cuda", dtype=torch.float32, requires_grad=True)
    left_gate = torch.randn(4, 16, device="cuda", dtype=torch.float32, requires_grad=True)
    right_up = left_up.detach().clone().requires_grad_(True)
    right_gate = left_gate.detach().clone().requires_grad_(True)
    eager = model_module._swiglu_product(left_up, left_gate)
    fused = model_module._FUSED_SWIGLU_PRODUCT(right_up, right_gate)
    eager.sum().backward()
    fused.sum().backward()
    output_ok = torch.allclose(eager, fused, rtol=1e-5, atol=1e-6)
    gradient_ok = torch.allclose(left_up.grad, right_up.grad, rtol=1e-5, atol=1e-6) and torch.allclose(left_gate.grad, right_gate.grad, rtol=1e-5, atol=1e-6)
    original = model_module.SwiGLUExpert.forward_fused
    model_module.SwiGLUExpert.forward_fused = model_module.SwiGLUExpert.forward
    rollback_ok = model_module.SwiGLUExpert.forward_fused is model_module.SwiGLUExpert.forward
    model_module.SwiGLUExpert.forward_fused = original
    if not output_ok or not gradient_ok or not rollback_ok:
        raise ValueError("EQUIVALENCE_OR_ROLLBACK_FAILED")
    return _self_hashed({
        "schema_version": PREFLIGHT_SCHEMA,
        "result": "PASS",
        "treatment_id": TREATMENT_ID,
        "source_blobs": source_blobs,
        "gates": {
            "protected_eval": {"result": "PASS", "raw_sha256": args.protected_eval_raw_sha256, "self_sha256": protected["self_sha256"]},
            "recovery": {"result": "PASS", "raw_sha256": args.recovery_raw_sha256, "self_sha256": recovery["self_sha256"]},
            "rollback": {"result": "PASS", "process_local_alias_proven": rollback_ok},
            "eager_fused_output_gradient_equivalence": {"result": "PASS", "rtol": 1e-5, "atol": 1e-6},
            "resource_go": {"result": "PASS", "raw_sha256": args.resource_go_raw_sha256, "self_sha256": resource_go["self_sha256"]},
        },
    })


def _run_arm(args: argparse.Namespace) -> dict[str, object]:
    if not args.live:
        raise ValueError("LIVE_AUTHORIZATION_REQUIRED")
    root = args.repo_root.resolve(strict=True)
    spec = load_spec(args.spec.resolve(strict=True))
    validate_source(root, spec)
    w1_preflight_raw = args.w1_preflight.read_bytes()
    if sha256_bytes(w1_preflight_raw) != args.w1_preflight_raw_sha256:
        raise ValueError("W1_PREFLIGHT_RAW_SHA256_MISMATCH")
    w1_preflight = _verify_self(json.loads(w1_preflight_raw), "w1 preflight")
    if w1_preflight.get("schema_version") != PREFLIGHT_SCHEMA or w1_preflight.get("result") != "PASS":
        raise ValueError("W1_PREFLIGHT_INVALID")
    module_root = root / "tools" / "ember-restart-3b"
    sys.path.insert(0, str(module_root))
    packed = importlib.import_module("packed_specialist_run")
    model_module = importlib.import_module("model")
    psutil = importlib.import_module("psutil")
    captured: dict[str, object] = {}
    original_segment = packed.run_packed_selection_pretraining_segment
    original_forward_fused = model_module.SwiGLUExpert.forward_fused
    fused_counter = {"count": 0}
    process = psutil.Process(os.getpid())
    baseline_memory = process.memory_info()
    baseline_private = int(getattr(baseline_memory, "private", baseline_memory.rss))
    peak_private = {"bytes": baseline_private}

    if args.route == "control":
        model_module.SwiGLUExpert.forward_fused = model_module.SwiGLUExpert.forward
        patch_proven = model_module.SwiGLUExpert.forward_fused is model_module.SwiGLUExpert.forward
    else:
        def counted_fused(instance, hidden_states):
            fused_counter["count"] += 1
            return original_forward_fused(instance, hidden_states)
        model_module.SwiGLUExpert.forward_fused = counted_fused
        patch_proven = False

    def capture_segment(**kwargs):
        original_progress = kwargs.get("progress_callback")

        def capture_progress(row):
            if original_progress is not None:
                original_progress(row)
            memory_info = process.memory_info()
            peak_private["bytes"] = max(
                peak_private["bytes"],
                int(getattr(memory_info, "private", memory_info.rss)),
            )

        kwargs["progress_callback"] = capture_progress
        result = original_segment(**kwargs)
        captured["losses"] = [float(value) for value in result["losses"]]
        captured["final_parameter_sha256"] = packed.all_parameter_sha256(kwargs["model"])
        return result

    packed.run_packed_selection_pretraining_segment = capture_segment
    profile_args = argparse.Namespace(
        repo_root=root,
        artifact_root=args.artifact_root,
        stream_manifest=args.stream_manifest,
        stream_manifest_sha256=args.stream_manifest_sha256,
        stream_build_receipt=args.stream_build_receipt,
        stream_build_receipt_sha256=args.stream_build_receipt_sha256,
        census=args.census,
        census_raw_sha256=args.census_raw_sha256,
        census_self_sha256=args.census_self_sha256,
        density=args.density,
        density_raw_sha256=args.density_raw_sha256,
        density_self_sha256=args.density_self_sha256,
        source_commit=args.source_commit,
        seed=args.seed,
        live=True,
        execution_source_commit=args.execution_source_commit,
        preflight_receipt=args.issue1946_preflight_receipt,
        arm_a_receipt=None,
    )
    started_monotonic = time.monotonic()
    try:
        result = packed.run_issue1946_profile(profile_args, mode=MEASUREMENT_POLICY)
    finally:
        packed.run_packed_selection_pretraining_segment = original_segment
        model_module.SwiGLUExpert.forward_fused = original_forward_fused
    elapsed_seconds = time.monotonic() - started_monotonic
    base_path = Path(str(result["receipt_path"]))
    base_raw = base_path.read_bytes()
    base = _verify_self(json.loads(base_raw), "base profile")
    dispatch = {
        "forward_fused_is_forward": patch_proven,
        "fused_path_invocations": fused_counter["count"],
        "shared_ffn_invocations": len(captured["losses"]),
    }
    arm = _self_hashed({
        "schema_version": ARM_SCHEMA,
        "result": "PASS",
        "route": args.route,
        "treatment_id": TREATMENT_ID,
        "measurement_policy": MEASUREMENT_POLICY,
        "identity": base["identity"],
        "dispatch_evidence": dispatch,
        "warmup_update_seconds": base["warmup_update_seconds"],
        "governed_nonprofiled_update_seconds": base["governed_nonprofiled_update_seconds"],
        "losses": captured["losses"],
        "final_parameter_sha256": captured["final_parameter_sha256"],
        "fallbacks": base["fallbacks"],
        "memory": base["memory"],
        "board_energy_joules_per_update": base["board_energy_joules_per_update"],
        "first_temperature_c": base["power_rows"][0]["temperature_c"],
        "runtime_custody": base["runtime_custody"],
        "additional_process_commit_peak_bytes": max(0, peak_private["bytes"] - baseline_private),
        "launcher_elapsed_seconds": elapsed_seconds,
        "base_receipt_path": str(base_path),
        "base_receipt_raw_sha256": sha256_bytes(base_raw),
        "base_receipt_self_sha256": base["self_sha256"],
        "w1_preflight_raw_sha256": args.w1_preflight_raw_sha256,
        "w1_preflight_self_sha256": w1_preflight["self_sha256"],
    })
    _validate_arm(arm, args.route, spec)
    return arm


def _add_bound_receipt(parser: argparse.ArgumentParser, name: str) -> None:
    parser.add_argument(f"--{name.replace('_', '-')}", type=Path, required=True)
    parser.add_argument(f"--{name.replace('_', '-')}-raw-sha256", required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--repo-root", type=Path, required=True)
    preflight.add_argument("--spec", type=Path, required=True)
    _add_bound_receipt(preflight, "protected_eval")
    _add_bound_receipt(preflight, "recovery")
    _add_bound_receipt(preflight, "resource_go")
    preflight.add_argument("--output", type=Path, required=True)
    preflight.add_argument("--live", action="store_true")
    arm = sub.add_parser("arm")
    arm.add_argument("--route", choices=("control", "treatment"), required=True)
    arm.add_argument("--repo-root", type=Path, required=True)
    arm.add_argument("--spec", type=Path, required=True)
    arm.add_argument("--artifact-root", type=Path, required=True)
    arm.add_argument("--w1-preflight", type=Path, required=True)
    arm.add_argument("--w1-preflight-raw-sha256", required=True)
    arm.add_argument("--issue1946-preflight-receipt", type=Path, required=True)
    arm.add_argument("--stream-manifest", type=Path, required=True)
    arm.add_argument("--stream-manifest-sha256", required=True)
    arm.add_argument("--stream-build-receipt", type=Path, required=True)
    arm.add_argument("--stream-build-receipt-sha256", required=True)
    arm.add_argument("--census", type=Path, required=True)
    arm.add_argument("--census-raw-sha256", required=True)
    arm.add_argument("--census-self-sha256", required=True)
    arm.add_argument("--density", type=Path, required=True)
    arm.add_argument("--density-raw-sha256", required=True)
    arm.add_argument("--density-self-sha256", required=True)
    arm.add_argument("--source-commit", required=True)
    arm.add_argument("--execution-source-commit", required=True)
    arm.add_argument("--seed", type=int, required=True)
    arm.add_argument("--output", type=Path, required=True)
    arm.add_argument("--live", action="store_true")
    finalize = sub.add_parser("finalize")
    finalize.add_argument("--spec", type=Path, required=True)
    _add_bound_receipt(finalize, "control")
    _add_bound_receipt(finalize, "treatment")
    _add_bound_receipt(finalize, "preflight")
    _add_bound_receipt(finalize, "control_resource")
    _add_bound_receipt(finalize, "treatment_resource")
    finalize.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.output.exists():
        raise FileExistsError("OUTPUT_EXISTS_REFUSED")
    if args.command == "preflight":
        receipt = _run_preflight(args)
    elif args.command == "arm":
        receipt = _run_arm(args)
    else:
        spec = load_spec(args.spec.resolve(strict=True))
        control = _load_bound_receipt(args.control, args.control_raw_sha256, "control")
        treatment = _load_bound_receipt(args.treatment, args.treatment_raw_sha256, "treatment")
        preflight = _load_bound_receipt(args.preflight, args.preflight_raw_sha256, "preflight")
        control_resource = _load_raw_bound_json(args.control_resource, args.control_resource_raw_sha256, "control resource")
        treatment_resource = _load_raw_bound_json(args.treatment_resource, args.treatment_resource_raw_sha256, "treatment resource")
        receipt = build_terminal_receipt(
            control=control,
            treatment=treatment,
            preflight=preflight,
            control_resource=control_resource,
            treatment_resource=treatment_resource,
            spec=spec,
            control_raw_sha256=args.control_raw_sha256,
            treatment_raw_sha256=args.treatment_raw_sha256,
            preflight_raw_sha256=args.preflight_raw_sha256,
            control_resource_raw_sha256=args.control_resource_raw_sha256,
            treatment_resource_raw_sha256=args.treatment_resource_raw_sha256,
        )
    raw_sha, self_sha = write_json_no_replace(args.output, receipt)
    print(json.dumps({"result": receipt["result"], "receipt_path": str(args.output), "raw_sha256": raw_sha, "self_sha256": self_sha}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
