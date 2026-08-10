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

    binding_rows: list[dict[str, str]] = []
    binding_specs = [
        ("config", _file(config_path, "DISPATCH_CONFIG_UNAVAILABLE")),
        ("manifest", _file(threshold_path, "DISPATCH_THRESHOLD_UNAVAILABLE")),
        ("input", _file(checkpoint_manifest_path, "DISPATCH_CHECKPOINT_UNAVAILABLE")),
        ("input", _file(batch_manifest_path, "DISPATCH_BATCH_UNAVAILABLE")),
        ("manifest", producer_contract),
        *[("input", path) for path in producer_components.values()],
        ("verifier", _file(verifier_path, "DISPATCH_VERIFIER_UNAVAILABLE")),
        ("input", host_commit_receipt),
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
