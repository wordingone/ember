#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#2006 three-case CUDA BF16 gradient-equivalence receipt producer.

This producer is deliberately throughput-blind.  It exits after the frozen
gradient gate and cannot make the treatment visible to a training launch.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

GOAL_ID = "EMBER-02"
WORKSTREAM_ID = "EMBER-02B"
NEXT_OUTCOME = "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
TREATMENT_ID = "d3617962c97b1f7efec47a49ad113aedd19cea127c7b623bd15741cb38453de6"
PARAMETER_SEEDS = (1945201, 1945202, 1945203)
CASES = (
    ("w3-gradient-001", 0, (1, 1, 2048), 1945001, 1945101, 1945201),
    ("w3-gradient-002", 7, (1, 64, 2048), 1945002, 1945102, 1945202),
    ("w3-gradient-003", 13, (2, 128, 2048), 1945003, 1945103, 1945203),
)
SUBJECTS = ("input_gradient", "up_gate_weight_gradient", "down_weight_gradient")
THRESHOLDS = {"cosine_min": 0.999999, "relative_l2_max": 0.001, "rtol": 0.001, "atol": 0.00001}
MAX_WALL_SECONDS = 1800.0
MAX_ADDITIONAL_PROCESS_COMMIT_BYTES = 25_769_803_776
MAX_RESERVED_VRAM_BYTES = 23_622_320_128
BOUND_UNCHANGED_BLOBS = {
    "tools/ember-restart-3b/pretrain.py": "43c9a4bf6532ef0fe43f14bd7352f7b1b1cf5e72",
    "tools/ember-restart-3b/training_acceleration.py": "71a337f46405bda2defc029a699402d3c6daee68",
}
DEPENDENCIES = {
    "w3_spec_raw_sha256": "28266f5bfa97cf4f02e57cee5093d337df202f9c136f605876476c97dcb44923",
    "w3_spec_self_sha256": "1633970fc61f66ac942bfad62bb307c91f3da8887eb4344bf7bcd0123fa08e55",
    "w3_measurement_raw_sha256": "4945bbf885a12d8acb989478ad18ab9d37c57e1b7bf091a924db877ad38c48ae",
    "w3_measurement_self_sha256": "826002a0f4a2771892e1dabdb7afa604b591468b0b23cf777add1ba8d6cd5b51",
    "w3_disk_raw_sha256": "6af7a32d3b78240b5d5f4b0c9d670215aca927cb260187c0d7d464f744b0dc53",
    "w3_terminal_raw_sha256": "08913ae684ced4323cf27d96647177fc5ba3981404d39b1103905e5a66f79161",
    "w3_terminal_self_sha256": "caf04fecc18f7f1f299c567f5366f68c229f46d4f3ba7e37e93c23b12301298f",
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def self_hash(value: dict[str, Any]) -> str:
    unsigned = dict(value)
    unsigned.pop("self_sha256", None)
    return sha256(canonical_bytes(unsigned))


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes())


def _read_dependency(path: Path, raw_key: str, self_key: str | None = None) -> tuple[dict[str, Any], dict[str, str]]:
    path = path.resolve(strict=True)
    raw = path.read_bytes()
    actual_raw = sha256(raw)
    if actual_raw != DEPENDENCIES[raw_key]:
        raise ValueError(f"{raw_key} drift: {actual_raw}")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise TypeError(f"{raw_key} is not a JSON object")
    evidence = {"path": str(path), "raw_sha256": actual_raw}
    if self_key is not None:
        stored = value.get("self_sha256")
        actual_self = self_hash(value)
        if stored != DEPENDENCIES[self_key] or actual_self != DEPENDENCIES[self_key]:
            raise ValueError(f"{self_key} drift: stored={stored} recomputed={actual_self}")
        evidence["self_sha256"] = actual_self
    return value, evidence


def verify_dependency_files(paths: dict[str, Path]) -> dict[str, dict[str, str]]:
    if set(paths) != {"spec", "measurement", "disk", "terminal"}:
        raise ValueError("dependency path set drift")
    _, spec_evidence = _read_dependency(paths["spec"], "w3_spec_raw_sha256", "w3_spec_self_sha256")
    measurement, measurement_evidence = _read_dependency(
        paths["measurement"], "w3_measurement_raw_sha256", "w3_measurement_self_sha256"
    )
    _, disk_evidence = _read_dependency(paths["disk"], "w3_disk_raw_sha256")
    terminal, terminal_evidence = _read_dependency(
        paths["terminal"], "w3_terminal_raw_sha256", "w3_terminal_self_sha256"
    )
    expected_spec = (DEPENDENCIES["w3_spec_raw_sha256"], DEPENDENCIES["w3_spec_self_sha256"])
    if (measurement.get("spec_raw_sha256"), measurement.get("spec_self_sha256")) != expected_spec:
        raise ValueError("measurement-to-spec binding drift")
    if (terminal.get("spec_raw_sha256"), terminal.get("spec_self_sha256")) != expected_spec:
        raise ValueError("terminal-to-spec binding drift")
    if terminal.get("disk_receipt_raw_sha256") != DEPENDENCIES["w3_disk_raw_sha256"]:
        raise ValueError("terminal-to-disk binding drift")
    expected_measurement = {
        "raw_sha256": DEPENDENCIES["w3_measurement_raw_sha256"],
        "self_sha256": DEPENDENCIES["w3_measurement_self_sha256"],
    }
    if terminal.get("measurement") != expected_measurement:
        raise ValueError("terminal-to-measurement binding drift")
    if terminal.get("result") != "PASS" or terminal.get("resource_failures") != []:
        raise ValueError("W3 attribution terminal is not resource-clean PASS")
    return {
        "spec": spec_evidence,
        "measurement": measurement_evidence,
        "disk": disk_evidence,
        "terminal": terminal_evidence,
    }


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(["git", *arguments], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or f"git {' '.join(arguments)} failed")
    return result.stdout.strip()


def verify_source(root: Path, expected_commit: str, expected_model_sha256: str) -> dict[str, str]:
    root = root.resolve(strict=True)
    head = _git(root, "rev-parse", "HEAD")
    if head != expected_commit:
        raise ValueError(f"source commit drift: {head}")
    if _git(root, "status", "--porcelain"):
        raise ValueError("source worktree is not clean")
    model = root / "tools" / "ember-restart-3b" / "model.py"
    raw = file_sha256(model)
    if raw != expected_model_sha256:
        raise ValueError(f"model raw drift: {raw}")
    blobs = {path: _git(root, "rev-parse", f"HEAD:{path}") for path in ("tools/ember-restart-3b/model.py", *BOUND_UNCHANGED_BLOBS)}
    for path, expected in BOUND_UNCHANGED_BLOBS.items():
        if blobs[path] != expected:
            raise ValueError(f"source blob drift: {path}: {blobs[path]}")
    return {"commit": head, "tree": _git(root, "rev-parse", "HEAD^{tree}"), "model_sha256": raw, "source_blobs": blobs}


def load_model(root: Path) -> Any:
    path = root / "tools" / "ember-restart-3b" / "model.py"
    spec = importlib.util.spec_from_file_location("issue2006_bound_model", path)
    if spec is None or spec.loader is None:
        raise ValueError("model import spec unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if module.W3_ACTIVE_EXPERT_FUSED_BACKWARD_TREATMENT_ID != TREATMENT_ID:
        raise ValueError("treatment identity drift")
    return module


def process_commit_bytes() -> tuple[int, int]:
    if sys.platform != "win32":
        raise RuntimeError("process commit measurement requires Windows")
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    if not ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise RuntimeError("GetProcessMemoryInfo failed")
    return int(counters.PrivateUsage), int(counters.PeakPagefileUsage)


def _tensor_hash(tensor: Any) -> str:
    import torch

    return sha256(tensor.detach().cpu().contiguous().view(torch.uint8).numpy().tobytes())


def _metrics(torch: Any, control: Any, treatment: Any) -> dict[str, Any]:
    left = control.float().reshape(-1)
    right = treatment.float().reshape(-1)
    left_norm = torch.linalg.vector_norm(left)
    difference = torch.linalg.vector_norm(left - right)
    relative_l2 = float(difference / left_norm) if float(left_norm) else (0.0 if float(difference) == 0.0 else float("inf"))
    return {
        "shape_equal": tuple(control.shape) == tuple(treatment.shape),
        "dtype_equal": control.dtype == treatment.dtype,
        "finite_mask_equal": bool(torch.equal(torch.isfinite(control), torch.isfinite(treatment))),
        "zero_mask_equal": bool(torch.equal(control == 0, treatment == 0)),
        "cosine_similarity": float(torch.nn.functional.cosine_similarity(left, right, dim=0)),
        "relative_l2_error": relative_l2,
        "elementwise_close": bool(torch.allclose(left, right, rtol=THRESHOLDS["rtol"], atol=THRESHOLDS["atol"])),
        "control_sha256": _tensor_hash(control),
        "treatment_sha256": _tensor_hash(treatment),
    }


def metric_pass(value: dict[str, Any]) -> bool:
    return bool(value["shape_equal"] and value["dtype_equal"] and value["finite_mask_equal"] and value["zero_mask_equal"] and value["cosine_similarity"] >= THRESHOLDS["cosine_min"] and value["relative_l2_error"] <= THRESHOLDS["relative_l2_max"] and value["elementwise_close"])


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _exact_hash_map(value: Any, keys: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == keys and all(_is_sha256(value[key]) for key in keys)


def validate_receipt(receipt: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if receipt.get("schema") != "ember-issue2006-w3-gradient-equivalence/v1": errors.append("schema")
    if receipt.get("goal_id") != GOAL_ID or receipt.get("workstream_id") != WORKSTREAM_ID or receipt.get("next_executed_outcome") != NEXT_OUTCOME: errors.append("authority")
    if receipt.get("treatment_id") != TREATMENT_ID: errors.append("treatment_id")
    if receipt.get("dependencies") != DEPENDENCIES: errors.append("dependencies")
    if receipt.get("thresholds") != THRESHOLDS: errors.append("thresholds")
    cases = receipt.get("cases")
    if not isinstance(cases, list) or len(cases) != len(CASES): return errors + ["case_count"]
    for observed, frozen in zip(cases, CASES):
        case_id, layer, shape, input_seed, upstream_seed, parameter_seed = frozen
        expected = {"case_id": case_id, "layer": layer, "shape": list(shape), "input_seed": input_seed, "upstream_seed": upstream_seed, "parameter_seed": parameter_seed, "expert": "reasoning"}
        if any(observed.get(key) != value for key, value in expected.items()): errors.append(f"{case_id}.identity")
        gradients = observed.get("gradients")
        if not isinstance(gradients, dict) or set(gradients) != set(SUBJECTS): errors.append(f"{case_id}.subjects")
        elif not all(metric_pass(gradients[name]) for name in SUBJECTS): errors.append(f"{case_id}.metrics")
        if observed.get("forward_byte_identical") is not True: errors.append(f"{case_id}.forward")
        inputs = observed.get("input_hashes")
        if not _exact_hash_map(inputs, {"cpu_fp32", "upstream_cpu_fp32", "cuda_bf16", "upstream_cuda_bf16"}):
            errors.append(f"{case_id}.inputs")
        forwards = observed.get("forward_hashes")
        if not _exact_hash_map(forwards, {"control", "treatment"}) or forwards["control"] != forwards["treatment"]:
            errors.append(f"{case_id}.forward_hashes")
        parameters = observed.get("parameter_hashes")
        if not isinstance(parameters, dict) or set(parameters) != {"cpu_fp32", "cuda_bf16"}: errors.append(f"{case_id}.parameters")
        elif not all(_exact_hash_map(parameters[dtype], {"up_gate.weight", "down.weight"}) for dtype in parameters):
            errors.append(f"{case_id}.parameter_hashes")
    resource = receipt.get("resource") or {}
    if resource.get("wall_seconds", float("inf")) > MAX_WALL_SECONDS: errors.append("wall")
    if resource.get("additional_process_commit_bytes", MAX_ADDITIONAL_PROCESS_COMMIT_BYTES + 1) > MAX_ADDITIONAL_PROCESS_COMMIT_BYTES: errors.append("commit")
    if resource.get("peak_reserved_vram_bytes", MAX_RESERVED_VRAM_BYTES + 1) > MAX_RESERVED_VRAM_BYTES: errors.append("vram")
    expected_result = "PASS" if not errors else "REJECTED_GRADIENT_EQUIVALENCE"
    if receipt.get("result") != expected_result: errors.append("result")
    return errors


def run_case(torch: Any, model: Any, frozen: tuple[Any, ...]) -> dict[str, Any]:
    case_id, layer, shape, input_seed, upstream_seed, parameter_seed = frozen
    hidden = torch.randn(shape, generator=torch.Generator(device="cpu").manual_seed(input_seed), dtype=torch.float32).mul_(0.125)
    hidden.reshape(-1)[::17] = 0
    upstream = torch.randn(shape, generator=torch.Generator(device="cpu").manual_seed(upstream_seed), dtype=torch.float32).mul_(0.0625)
    upstream.reshape(-1)[::19] = 0
    torch.manual_seed(parameter_seed)
    expert = model.SwiGLUExpert(2048, device="cpu")
    fp32_parameters = {name: _tensor_hash(parameter) for name, parameter in expert.named_parameters()}
    input_hashes = {"cpu_fp32": _tensor_hash(hidden), "upstream_cpu_fp32": _tensor_hash(upstream)}
    expert = expert.to(device="cuda", dtype=torch.bfloat16)
    hidden = hidden.to(device="cuda", dtype=torch.bfloat16).requires_grad_(True)
    upstream = upstream.to(device="cuda", dtype=torch.bfloat16)
    input_hashes.update({"cuda_bf16": _tensor_hash(hidden), "upstream_cuda_bf16": _tensor_hash(upstream)})
    bf16_parameters = {name: _tensor_hash(parameter) for name, parameter in expert.named_parameters()}

    control_output = expert(hidden)
    control_output.backward(upstream)
    control = {"input_gradient": hidden.grad.detach().clone(), "up_gate_weight_gradient": expert.up_gate.weight.grad.detach().clone(), "down_weight_gradient": expert.down.weight.grad.detach().clone()}
    hidden.grad = None
    expert.zero_grad(set_to_none=True)
    treatment_output = expert.forward_with_fused_backward(hidden)
    treatment_output.backward(upstream)
    treatment = {"input_gradient": hidden.grad.detach().clone(), "up_gate_weight_gradient": expert.up_gate.weight.grad.detach().clone(), "down_weight_gradient": expert.down.weight.grad.detach().clone()}
    torch.cuda.synchronize()
    gradients = {name: _metrics(torch, control[name], treatment[name]) for name in SUBJECTS}
    return {
        "case_id": case_id, "layer": layer, "shape": list(shape), "input_seed": input_seed,
        "upstream_seed": upstream_seed, "parameter_seed": parameter_seed, "expert": "reasoning",
        "input_hashes": input_hashes,
        "parameter_hashes": {"cpu_fp32": fp32_parameters, "cuda_bf16": bf16_parameters},
        "forward_hashes": {"control": _tensor_hash(control_output), "treatment": _tensor_hash(treatment_output)},
        "forward_byte_identical": bool(torch.equal(control_output, treatment_output)),
        "gradients": gradients,
    }


def produce(
    root: Path,
    output: Path,
    expected_commit: str,
    expected_model_sha256: str,
    dependency_paths: dict[str, Path],
    *,
    live: bool,
) -> dict[str, Any]:
    if output.exists(): raise FileExistsError(f"no-overwrite output exists: {output}")
    if not live or os.environ.get("EMBER_GATE_AUTHORIZED") != "1": raise ValueError("live gradient gate requires --live and EMBER_GATE_AUTHORIZED=1")
    if os.environ.get("EMBER_W3_ACTIVE_EXPERT_FUSED_BACKWARD") is not None: raise ValueError("selector must be unset during isolated gradient gate")
    source = verify_source(root, expected_commit, expected_model_sha256)
    dependency_files = verify_dependency_files(dependency_paths)
    import torch
    if not torch.cuda.is_available(): raise RuntimeError("CUDA unavailable")
    if torch.cuda.device_count() != 1: raise RuntimeError("gradient gate requires exactly one visible CUDA device")
    device = torch.cuda.get_device_properties(0)
    if "4090" not in device.name: raise RuntimeError(f"unexpected CUDA device: {device.name}")
    module = load_model(root)
    started = time.monotonic()
    commit_before, _ = process_commit_bytes()
    torch.cuda.reset_peak_memory_stats(0)
    cases = [run_case(torch, module, frozen) for frozen in CASES]
    torch.cuda.synchronize()
    commit_after, commit_peak = process_commit_bytes()
    resource = {
        "wall_seconds": time.monotonic() - started,
        "process_commit_before_bytes": commit_before,
        "process_commit_peak_bytes": commit_peak,
        "process_commit_after_bytes": commit_after,
        "additional_process_commit_bytes": max(0, commit_peak - commit_before),
        "peak_reserved_vram_bytes": int(torch.cuda.max_memory_reserved(0)),
        "device_name": device.name,
        "device_total_memory_bytes": int(device.total_memory),
    }
    receipt: dict[str, Any] = {
        "schema": "ember-issue2006-w3-gradient-equivalence/v1", "goal_id": GOAL_ID,
        "workstream_id": WORKSTREAM_ID, "next_executed_outcome": NEXT_OUTCOME,
        "treatment_id": TREATMENT_ID, "treatment_class": "EAGER_FORWARD_CUSTOM_BACKWARD_FUSED_SWIGLU_GRADIENT",
        "source": source, "dependencies": DEPENDENCIES, "dependency_files": dependency_files,
        "thresholds": THRESHOLDS, "cases": cases, "resource": resource,
        "throughput_visible": False,
        "claim_boundary": "GRADIENT_EQUIVALENCE_ONLY; NO_THROUGHPUT_NO_LEARNING_NO_EVALUATION_NO_RETENTION_NO_20K_NO_CAMPAIGN_CREDIT",
    }
    receipt["result"] = "PASS" if not validate_receipt({**receipt, "result": "PASS"}) else "REJECTED_GRADIENT_EQUIVALENCE"
    errors = validate_receipt(receipt)
    receipt["validation_errors"] = errors
    receipt["self_sha256"] = self_hash(receipt)
    raw = json.dumps(receipt, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(raw)
    print(json.dumps({"result": receipt["result"], "raw_sha256": sha256(raw), "self_sha256": receipt["self_sha256"]}, sort_keys=True))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--expected-model-sha256", required=True)
    parser.add_argument("--w3-spec", type=Path, required=True)
    parser.add_argument("--w3-measurement", type=Path, required=True)
    parser.add_argument("--w3-disk-receipt", type=Path, required=True)
    parser.add_argument("--w3-terminal", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    dependency_paths = {
        "spec": args.w3_spec,
        "measurement": args.w3_measurement,
        "disk": args.w3_disk_receipt,
        "terminal": args.w3_terminal,
    }
    receipt = produce(
        args.root,
        args.output,
        args.expected_source_commit,
        args.expected_model_sha256,
        dependency_paths,
        live=args.live,
    )
    return 0 if receipt["result"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
