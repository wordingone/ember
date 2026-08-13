# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Build a closed Ember Lab v3 plan for the issue #675 actual event.

The builder performs no dispatch and grants no event or scientific credit.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Mapping, Sequence

from q2_producer_contract import ProducerContractRefusal, validate_producer_contract


_GIB = 1024**3
_HOST_COMMIT_RESERVE = 10 * _GIB
_MIN_VRAM = 21_746_679_808
_MIN_STORAGE = 42_949_672_960
_CPU_RATE_PERCENT = 80
_PRODUCER_KINDS = (
    "training_data_loader",
    "checkpoint_writer",
    "telemetry_buffer",
)
_HOST_COMMIT_RECEIPT_FIELDS = {
    "schema_version",
    "job_id",
    "source_commit",
    "measurement_mode",
    "process",
    "bindings",
    "phases",
    "simulated_peak_commit_bytes",
    "maximum_job_memory_bytes",
    "producer_budgets",
    "trace_sha256",
    "event_credit",
    "scientific_credit",
    "no_new_parallel_authority",
    "receipt_sha256",
}
_CUDA_RECEIPT_FIELDS = {
    "schema", "job_id", "source_commit", "config_sha256",
    "measurement_tool_sha256", "checkpoint_manifest_sha256",
    "intermediate_size", "observed_at_ms", "expires_at_ms",
    "device_index", "device_name", "model_bytes", "required_scratch_bytes",
    "chunk_bytes", "free_before_bytes", "free_after_bytes", "total_bytes",
    "result", "event_credit", "scientific_credit",
    "no_new_parallel_authority", "receipt_sha256",
}
_CUDA_CHUNK_BYTES = 64 * 1024**2
_CACHE_ENV = {
    "TEMP": "temp",
    "TMP": "tmp",
    "TORCH_HOME": "torch",
    "TRITON_CACHE_DIR": "triton",
    "CUDA_CACHE_PATH": "cuda",
    "HF_HOME": "hf",
    "XDG_CACHE_HOME": "xdg",
}


class DispatchPlanRefusal(ValueError):
    """Named refusal emitted before a dispatch manifest is selectable."""


def _refuse(code: str) -> None:
    raise DispatchPlanRefusal(code)


def _file(path: Path, code: str) -> Path:
    try:
        result = Path(path).resolve(strict=True)
    except OSError:
        _refuse(code)
    if not result.is_file():
        _refuse(code)
    return result


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _host_commit_receipt(
    path: Path,
    *,
    job_id: str,
    source_commit: str,
    simulated_peak_commit_bytes: int,
    maximum_job_memory_bytes: int,
    producer_budgets: Mapping[str, int],
) -> Path:
    receipt_path = _file(path, "DISPATCH_HOST_COMMIT_RECEIPT_UNAVAILABLE")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _refuse("DISPATCH_HOST_COMMIT_RECEIPT_MALFORMED")
    if not isinstance(receipt, dict) or set(receipt) != _HOST_COMMIT_RECEIPT_FIELDS:
        _refuse("DISPATCH_HOST_COMMIT_RECEIPT_SCHEMA_INVALID")
    supplied_sha = receipt.get("receipt_sha256")
    unsigned = dict(receipt)
    unsigned.pop("receipt_sha256", None)
    expected_sha = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    if not isinstance(supplied_sha, str) or supplied_sha != expected_sha:
        _refuse("DISPATCH_HOST_COMMIT_RECEIPT_TAMPERED")
    if (
        receipt["schema_version"] != "q2-host-commit-simulation-receipt-v1"
        or receipt["measurement_mode"] != "bounded_dry_run"
        or receipt["job_id"] != job_id
        or receipt["source_commit"] != source_commit
        or receipt["simulated_peak_commit_bytes"] != simulated_peak_commit_bytes
        or receipt["maximum_job_memory_bytes"] != maximum_job_memory_bytes
        or receipt["producer_budgets"] != dict(producer_budgets)
        or receipt["event_credit"] is not False
        or receipt["scientific_credit"] is not False
        or receipt["no_new_parallel_authority"] is not True
    ):
        _refuse("DISPATCH_HOST_COMMIT_RECEIPT_MISMATCH")
    return receipt_path


def _cuda_allocability_receipt(
    path: Path,
    *,
    job_id: str,
    source_commit: str,
    config_sha256: str,
    measurement_tool_sha256: str,
    checkpoint_manifest_sha256: str,
    intermediate_size: int,
    expected_model_bytes: int,
    expected_scratch_bytes: int,
    not_before_ms: int,
    expires_at_ms: int,
) -> Path:
    receipt_path = _file(path, "DISPATCH_CUDA_ALLOCABILITY_RECEIPT_UNAVAILABLE")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _refuse("DISPATCH_CUDA_ALLOCABILITY_RECEIPT_MALFORMED")
    if not isinstance(receipt, dict) or set(receipt) != _CUDA_RECEIPT_FIELDS:
        _refuse("DISPATCH_CUDA_ALLOCABILITY_RECEIPT_SCHEMA_INVALID")
    supplied = receipt.get("receipt_sha256")
    unsigned = dict(receipt)
    unsigned.pop("receipt_sha256", None)
    expected = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if supplied != expected:
        _refuse("DISPATCH_CUDA_ALLOCABILITY_RECEIPT_TAMPERED")
    numeric = tuple(
        receipt.get(key)
        for key in (
            "intermediate_size", "observed_at_ms", "expires_at_ms",
            "model_bytes", "required_scratch_bytes", "chunk_bytes",
            "free_before_bytes", "free_after_bytes", "total_bytes",
        )
    )
    if (
        receipt.get("schema") != "q2-cuda-allocability-receipt-v1"
        or receipt.get("job_id") != job_id
        or receipt.get("source_commit") != source_commit
        or receipt.get("config_sha256") != config_sha256
        or receipt.get("measurement_tool_sha256") != measurement_tool_sha256
        or receipt.get("checkpoint_manifest_sha256") != checkpoint_manifest_sha256
        or receipt.get("intermediate_size") != intermediate_size
        or receipt.get("model_bytes") != expected_model_bytes
        or receipt.get("required_scratch_bytes") != expected_scratch_bytes
        or receipt.get("chunk_bytes") != _CUDA_CHUNK_BYTES
        or receipt.get("observed_at_ms") > not_before_ms
        or receipt.get("expires_at_ms") < expires_at_ms
        or receipt.get("device_index") != 0
        or not isinstance(receipt.get("device_name"), str)
        or not receipt.get("device_name")
        or receipt.get("free_after_bytes") > receipt.get("free_before_bytes")
        or receipt.get("free_before_bytes") > receipt.get("total_bytes")
        or any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in numeric)
        or receipt.get("result") != "ALLOCATABLE"
        or receipt.get("event_credit") is not False
        or receipt.get("scientific_credit") is not False
        or receipt.get("no_new_parallel_authority") is not True
    ):
        _refuse("DISPATCH_CUDA_ALLOCABILITY_RECEIPT_MISMATCH")
    return receipt_path


def _expected_cuda_bounds(config_path: Path, checkpoint_path: Path) -> tuple[int, int, int]:
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        model = config["model"]
        mtp = config["objective"]["mtp_aux_heads"]
        if not isinstance(model, dict) or not isinstance(mtp, dict):
            raise TypeError
        vocab, hidden, layers, heads, seq = (
            int(model[key]) for key in ("vocab", "hidden", "layers", "heads", "seq")
        )
        tied = model["tied_embeddings"]
        n_mtp = int(mtp["n_heads"])
        intermediate = int(checkpoint["intermediate_size"])
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        _refuse("DISPATCH_CUDA_BOUND_INPUT_INVALID")
    if (
        any(value <= 0 for value in (vocab, hidden, layers, heads, seq, intermediate))
        or tied not in (True, False)
        or n_mtp < 0
    ):
        _refuse("DISPATCH_CUDA_BOUND_INPUT_INVALID")
    elements = (
        vocab * hidden
        + layers * (4 * hidden * hidden + 3 * hidden * intermediate + 2 * hidden)
        + hidden
        + (0 if tied else vocab * hidden)
        + n_mtp * vocab * hidden
    )
    model_bytes = 2 * elements
    per_layer = 2 * seq * (16 * hidden + 6 * intermediate + 2 * heads * seq)
    scratch_bytes = per_layer + 4 * hidden * intermediate + 512 * 1024**2
    return intermediate, model_bytes, scratch_bytes


def _has_historical_module_refusal(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError):
        _refuse("PRODUCER_SOURCE_UNREADABLE")
    for node in tree.body:
        if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
            continue
        if not isinstance(node.exc.func, ast.Name) or node.exc.func.id != "SystemExit":
            continue
        text = " ".join(
            value.value
            for value in node.exc.args
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        )
        if "historical_only" in text or "execution-denied" in text:
            return True
    return False


def build_dispatch_manifest(
    *,
    job_id: str,
    source_commit: str,
    not_before_ms: int,
    expires_at_ms: int,
    program_path: Path,
    producer_path: Path,
    source_dependencies: Sequence[Path],
    custody_root: Path,
    config_path: Path,
    checkpoint_manifest_path: Path,
    batch_manifest_path: Path,
    threshold_path: Path,
    verifier_path: Path,
    host_commit_receipt_path: Path,
    cuda_allocability_receipt_path: Path,
    producer_contract_path: Path,
    producer_component_paths: Mapping[str, Path],
    minimum_free_vram_bytes: int,
    storage_root: Path,
    minimum_storage_free_bytes: int,
    simulated_peak_commit_bytes: int,
    maximum_job_memory_bytes: int,
    observed_available_maximum_commit_bytes: int,
    producer_budgets: Mapping[str, int],
) -> dict[str, object]:
    """Return a deterministic dispatch object or a named pre-dispatch refusal."""

    if not isinstance(job_id, str) or re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", job_id) is None:
        _refuse("DISPATCH_JOB_ID_INVALID")
    if not isinstance(source_commit, str) or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        _refuse("DISPATCH_SOURCE_COMMIT_INVALID")
    if (
        not isinstance(not_before_ms, int)
        or isinstance(not_before_ms, bool)
        or not isinstance(expires_at_ms, int)
        or isinstance(expires_at_ms, bool)
        or not_before_ms < 0
        or expires_at_ms <= not_before_ms
        or expires_at_ms - not_before_ms > 300_000
    ):
        _refuse("DISPATCH_WINDOW_INVALID")

    program = _file(program_path, "DISPATCH_PROGRAM_UNAVAILABLE")
    producer = _file(producer_path, "DISPATCH_PRODUCER_UNAVAILABLE")
    dependencies = [_file(path, "PRODUCER_SOURCE_UNREADABLE") for path in source_dependencies]
    if producer not in dependencies or len(set(dependencies)) != len(dependencies):
        _refuse("PRODUCER_DEPENDENCY_SET_INVALID")
    if any(_has_historical_module_refusal(path) for path in dependencies):
        _refuse("HISTORICAL_IMPORT_EXECUTION_DENIED")

    producer_contract = _file(
        producer_contract_path, "DISPATCH_PRODUCER_CONTRACT_UNAVAILABLE"
    )
    producer_components = {
        key: _file(path, "DISPATCH_PRODUCER_COMPONENT_UNAVAILABLE")
        for key, path in producer_component_paths.items()
    }
    try:
        validate_producer_contract(
            contract_path=producer_contract,
            source_commit=source_commit,
            producer_path=producer,
            component_paths=producer_components,
        )
    except ProducerContractRefusal:
        _refuse("DISPATCH_PRODUCER_CONTRACT_REFUSED")

    try:
        custody = Path(custody_root).resolve(strict=True)
        storage = Path(storage_root).resolve(strict=True)
    except OSError:
        _refuse("DISPATCH_CUSTODY_OR_STORAGE_UNAVAILABLE")
    if not custody.is_dir() or not storage.is_dir():
        _refuse("DISPATCH_CUSTODY_OR_STORAGE_UNAVAILABLE")
    env: dict[str, str] = {}
    for key, logical in _CACHE_ENV.items():
        try:
            path = (custody / logical).resolve(strict=True)
        except OSError:
            _refuse("DISPATCH_CACHE_ROOT_UNAVAILABLE")
        if not path.is_dir() or not path.is_relative_to(custody):
            _refuse("DISPATCH_CACHE_ROOT_OUTSIDE_CUSTODY")
        env[key] = str(path)

    if minimum_free_vram_bytes < _MIN_VRAM:
        _refuse("DISPATCH_VRAM_FLOOR_WEAKENED")
    if minimum_storage_free_bytes < _MIN_STORAGE:
        _refuse("DISPATCH_STORAGE_FLOOR_WEAKENED")
    numeric = (
        simulated_peak_commit_bytes,
        maximum_job_memory_bytes,
        observed_available_maximum_commit_bytes,
    )
    if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in numeric):
        _refuse("DISPATCH_HOST_COMMIT_BOUND_INVALID")
    if (
        simulated_peak_commit_bytes > maximum_job_memory_bytes
        or maximum_job_memory_bytes + _HOST_COMMIT_RESERVE
        > observed_available_maximum_commit_bytes
    ):
        _refuse("DISPATCH_HOST_COMMIT_CAP")
    if set(producer_budgets) != set(_PRODUCER_KINDS) or any(
        not isinstance(value, int) or isinstance(value, bool) or value <= 0
        for value in producer_budgets.values()
    ):
        _refuse("DISPATCH_PRODUCER_BUDGET_SCHEMA_INVALID")
    if sum(producer_budgets.values()) != simulated_peak_commit_bytes:
        _refuse("DISPATCH_PRODUCER_BUDGET_PEAK_MISMATCH")
    host_commit_receipt = _host_commit_receipt(
        host_commit_receipt_path,
        job_id=job_id,
        source_commit=source_commit,
        simulated_peak_commit_bytes=simulated_peak_commit_bytes,
        maximum_job_memory_bytes=maximum_job_memory_bytes,
        producer_budgets=producer_budgets,
    )
    if "measured_dry_run" not in producer_components:
        _refuse("DISPATCH_PRODUCER_COMPONENT_UNAVAILABLE")
    config = _file(config_path, "DISPATCH_CONFIG_UNAVAILABLE")
    checkpoint = _file(checkpoint_manifest_path, "DISPATCH_CHECKPOINT_UNAVAILABLE")
    intermediate_size, expected_model_bytes, expected_scratch_bytes = _expected_cuda_bounds(
        config, checkpoint
    )
    cuda_allocability_receipt = _cuda_allocability_receipt(
        cuda_allocability_receipt_path,
        job_id=job_id,
        source_commit=source_commit,
        config_sha256=_sha(config),
        measurement_tool_sha256=_sha(producer_components["measured_dry_run"]),
        checkpoint_manifest_sha256=_sha(checkpoint),
        intermediate_size=intermediate_size,
        expected_model_bytes=expected_model_bytes,
        expected_scratch_bytes=expected_scratch_bytes,
        not_before_ms=not_before_ms,
        expires_at_ms=expires_at_ms,
    )

    binding_rows: list[dict[str, str]] = []
    binding_specs = [
        ("config", config),
        ("manifest", _file(threshold_path, "DISPATCH_THRESHOLD_UNAVAILABLE")),
        ("input", checkpoint),
        ("input", _file(batch_manifest_path, "DISPATCH_BATCH_UNAVAILABLE")),
        ("manifest", producer_contract),
        *[("input", path) for path in producer_components.values()],
        ("verifier", _file(verifier_path, "DISPATCH_VERIFIER_UNAVAILABLE")),
        ("input", host_commit_receipt),
        ("input", cuda_allocability_receipt),
        *[("input", path) for path in dependencies],
    ]
    if len({path for _, path in binding_specs}) != len(binding_specs):
        _refuse("DISPATCH_BINDING_DUPLICATE")
    for kind, path in binding_specs:
        binding_rows.append({"kind": kind, "path": str(path), "sha256": _sha(path)})

    args = [
        str(producer),
        "governed-vertical",
        "--run-id",
        job_id,
        "--config",
        str(Path(config_path).resolve()),
        "--checkpoint-manifest",
        str(Path(checkpoint_manifest_path).resolve()),
        "--batch-manifest",
        str(Path(batch_manifest_path).resolve()),
        "--threshold",
        str(Path(threshold_path).resolve()),
        "--verifier",
        str(Path(verifier_path).resolve()),
        "--custody-root",
        str(custody),
    ]
    return {
        "schema_version": "ember-lab-dispatch-manifest-v3",
        "job_id": job_id,
        "source_commit": source_commit,
        "not_before_ms": not_before_ms,
        "expires_at_ms": expires_at_ms,
        "resource_lease": "gpu-q2-actual-update",
        "program": {"path": str(program), "sha256": _sha(program)},
        "args": args,
        "workload_profile": {
            "profile_id": "governed_vertical",
            "pinned_host_producers": [
                {"kind": kind, "maximum_bytes": producer_budgets[kind]}
                for kind in _PRODUCER_KINDS
            ],
            "requires_ui_responsiveness": False,
            "cpu_rate_percent": _CPU_RATE_PERCENT,
        },
        # governed_vertical is not actually CPU-paced today (no enforcement lane exists yet)
        # and this producer spawns a headless training process -- truth-declared, not
        # aspirational. See runtime/ember-lab/src/lib.rs DispatchCpuPacingClass/
        # DispatchWindowContract.
        "cpu_pacing_class": "unpaced",
        "window_contract": "headless_no_windows",
        "env": env,
        "bindings": binding_rows,
        "custody_root": str(custody),
        "storage_reserves": [
            {"root": str(storage), "minimum_free_bytes": minimum_storage_free_bytes}
        ],
        "minimum_free_vram_bytes": minimum_free_vram_bytes,
        "required_available_maximum_commit_bytes": maximum_job_memory_bytes
        + _HOST_COMMIT_RESERVE,
        "maximum_job_memory_bytes": maximum_job_memory_bytes,
        "simulated_peak_commit_bytes": simulated_peak_commit_bytes,
        "preflight_receipt": str(custody / "dispatch-preflight.json"),
    }
