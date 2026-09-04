# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Current-native, non-admissible full-step throughput screen."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import tempfile
import time
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F

_REPO_IMPORT_HOME = Path(__file__).resolve().parents[5]
if str(_REPO_IMPORT_HOME) not in sys.path:
    sys.path.insert(0, str(_REPO_IMPORT_HOME))
from batch import decode_owned_batch
from src.ember.model.model import RestartDecoderConfig, UnifiedDecoder
# issue2015 exact-local-import:src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py
import importlib.util as _ember_1601eccb5605602b_importlib
import sys as _ember_1601eccb5605602b_sys
from pathlib import Path as _ember_1601eccb5605602b_Path
_ember_1601eccb5605602b_path = _ember_1601eccb5605602b_Path(__file__).resolve().parent.joinpath('parameter_counter.py')
if not _ember_1601eccb5605602b_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py')
_ember_1601eccb5605602b_aliases = ('_ember_issue2015_1601eccb5605602b', 'parameter_counter', 'src.ember.infrastructure.tools.ember-restart-3b.parameter_counter')
_ember_1601eccb5605602b_existing = []
for _ember_1601eccb5605602b_alias in _ember_1601eccb5605602b_aliases:
    _ember_1601eccb5605602b_candidate = _ember_1601eccb5605602b_sys.modules.get(_ember_1601eccb5605602b_alias)
    if _ember_1601eccb5605602b_candidate is not None and all(_ember_1601eccb5605602b_candidate is not item for item in _ember_1601eccb5605602b_existing):
        _ember_1601eccb5605602b_existing.append(_ember_1601eccb5605602b_candidate)
if len(_ember_1601eccb5605602b_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py')
if _ember_1601eccb5605602b_existing:
    _ember_1601eccb5605602b_module = _ember_1601eccb5605602b_existing[0]
    _ember_1601eccb5605602b_observed = getattr(_ember_1601eccb5605602b_module, '__file__', None)
    if _ember_1601eccb5605602b_observed is None or _ember_1601eccb5605602b_Path(_ember_1601eccb5605602b_observed).resolve() != _ember_1601eccb5605602b_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py')
else:
    _ember_1601eccb5605602b_spec = _ember_1601eccb5605602b_importlib.spec_from_file_location('_ember_issue2015_1601eccb5605602b', _ember_1601eccb5605602b_path)
    if _ember_1601eccb5605602b_spec is None or _ember_1601eccb5605602b_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py')
    _ember_1601eccb5605602b_module = _ember_1601eccb5605602b_importlib.module_from_spec(_ember_1601eccb5605602b_spec)
    for _ember_1601eccb5605602b_alias in _ember_1601eccb5605602b_aliases:
        _ember_1601eccb5605602b_prior = _ember_1601eccb5605602b_sys.modules.get(_ember_1601eccb5605602b_alias)
        if _ember_1601eccb5605602b_prior is not None and _ember_1601eccb5605602b_prior is not _ember_1601eccb5605602b_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py')
        _ember_1601eccb5605602b_sys.modules[_ember_1601eccb5605602b_alias] = _ember_1601eccb5605602b_module
    try:
        _ember_1601eccb5605602b_spec.loader.exec_module(_ember_1601eccb5605602b_module)
    except BaseException:
        for _ember_1601eccb5605602b_alias in _ember_1601eccb5605602b_aliases:
            if _ember_1601eccb5605602b_sys.modules.get(_ember_1601eccb5605602b_alias) is _ember_1601eccb5605602b_module:
                _ember_1601eccb5605602b_sys.modules.pop(_ember_1601eccb5605602b_alias, None)
        raise
for _ember_1601eccb5605602b_alias in _ember_1601eccb5605602b_aliases:
    _ember_1601eccb5605602b_prior = _ember_1601eccb5605602b_sys.modules.get(_ember_1601eccb5605602b_alias)
    if _ember_1601eccb5605602b_prior is not None and _ember_1601eccb5605602b_prior is not _ember_1601eccb5605602b_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py')
    _ember_1601eccb5605602b_sys.modules[_ember_1601eccb5605602b_alias] = _ember_1601eccb5605602b_module
measure_parameter_counts = getattr(_ember_1601eccb5605602b_module, 'measure_parameter_counts')
# issue2015 exact-local-import-end:src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py
# issue2015 exact-local-import:src/ember/infrastructure/tools/ember-restart-3b/run_vertical_slice.py
import importlib.util as _ember_58a9db1b1610c537_importlib
import sys as _ember_58a9db1b1610c537_sys
from pathlib import Path as _ember_58a9db1b1610c537_Path
_ember_58a9db1b1610c537_path = _ember_58a9db1b1610c537_Path(__file__).resolve().parent.joinpath('run_vertical_slice.py')
if not _ember_58a9db1b1610c537_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/infrastructure/tools/ember-restart-3b/run_vertical_slice.py')
_ember_58a9db1b1610c537_aliases = ('_ember_issue2015_58a9db1b1610c537', 'run_vertical_slice', 'src.ember.infrastructure.tools.ember-restart-3b.run_vertical_slice')
_ember_58a9db1b1610c537_existing = []
for _ember_58a9db1b1610c537_alias in _ember_58a9db1b1610c537_aliases:
    _ember_58a9db1b1610c537_candidate = _ember_58a9db1b1610c537_sys.modules.get(_ember_58a9db1b1610c537_alias)
    if _ember_58a9db1b1610c537_candidate is not None and all(_ember_58a9db1b1610c537_candidate is not item for item in _ember_58a9db1b1610c537_existing):
        _ember_58a9db1b1610c537_existing.append(_ember_58a9db1b1610c537_candidate)
if len(_ember_58a9db1b1610c537_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/run_vertical_slice.py')
if _ember_58a9db1b1610c537_existing:
    _ember_58a9db1b1610c537_module = _ember_58a9db1b1610c537_existing[0]
    _ember_58a9db1b1610c537_observed = getattr(_ember_58a9db1b1610c537_module, '__file__', None)
    if _ember_58a9db1b1610c537_observed is None or _ember_58a9db1b1610c537_Path(_ember_58a9db1b1610c537_observed).resolve() != _ember_58a9db1b1610c537_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/infrastructure/tools/ember-restart-3b/run_vertical_slice.py')
else:
    _ember_58a9db1b1610c537_spec = _ember_58a9db1b1610c537_importlib.spec_from_file_location('_ember_issue2015_58a9db1b1610c537', _ember_58a9db1b1610c537_path)
    if _ember_58a9db1b1610c537_spec is None or _ember_58a9db1b1610c537_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/infrastructure/tools/ember-restart-3b/run_vertical_slice.py')
    _ember_58a9db1b1610c537_module = _ember_58a9db1b1610c537_importlib.module_from_spec(_ember_58a9db1b1610c537_spec)
    for _ember_58a9db1b1610c537_alias in _ember_58a9db1b1610c537_aliases:
        _ember_58a9db1b1610c537_prior = _ember_58a9db1b1610c537_sys.modules.get(_ember_58a9db1b1610c537_alias)
        if _ember_58a9db1b1610c537_prior is not None and _ember_58a9db1b1610c537_prior is not _ember_58a9db1b1610c537_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/run_vertical_slice.py')
        _ember_58a9db1b1610c537_sys.modules[_ember_58a9db1b1610c537_alias] = _ember_58a9db1b1610c537_module
    try:
        _ember_58a9db1b1610c537_spec.loader.exec_module(_ember_58a9db1b1610c537_module)
    except BaseException:
        for _ember_58a9db1b1610c537_alias in _ember_58a9db1b1610c537_aliases:
            if _ember_58a9db1b1610c537_sys.modules.get(_ember_58a9db1b1610c537_alias) is _ember_58a9db1b1610c537_module:
                _ember_58a9db1b1610c537_sys.modules.pop(_ember_58a9db1b1610c537_alias, None)
        raise
for _ember_58a9db1b1610c537_alias in _ember_58a9db1b1610c537_aliases:
    _ember_58a9db1b1610c537_prior = _ember_58a9db1b1610c537_sys.modules.get(_ember_58a9db1b1610c537_alias)
    if _ember_58a9db1b1610c537_prior is not None and _ember_58a9db1b1610c537_prior is not _ember_58a9db1b1610c537_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/run_vertical_slice.py')
    _ember_58a9db1b1610c537_sys.modules[_ember_58a9db1b1610c537_alias] = _ember_58a9db1b1610c537_module
build_production_optimizer = getattr(_ember_58a9db1b1610c537_module, 'build_production_optimizer')
validate_optimizer_contract = getattr(_ember_58a9db1b1610c537_module, 'validate_optimizer_contract')
# issue2015 exact-local-import-end:src/ember/infrastructure/tools/ember-restart-3b/run_vertical_slice.py
# issue2015 exact-local-import:src/ember/infrastructure/tools/ember-restart-3b/semantic_stream.py
import importlib.util as _ember_61c7220b679f890b_importlib
import sys as _ember_61c7220b679f890b_sys
from pathlib import Path as _ember_61c7220b679f890b_Path
_ember_61c7220b679f890b_path = _ember_61c7220b679f890b_Path(__file__).resolve().parent.joinpath('semantic_stream.py')
if not _ember_61c7220b679f890b_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/infrastructure/tools/ember-restart-3b/semantic_stream.py')
_ember_61c7220b679f890b_aliases = ('_ember_issue2015_61c7220b679f890b', 'semantic_stream', 'src.ember.infrastructure.tools.ember-restart-3b.semantic_stream')
_ember_61c7220b679f890b_existing = []
for _ember_61c7220b679f890b_alias in _ember_61c7220b679f890b_aliases:
    _ember_61c7220b679f890b_candidate = _ember_61c7220b679f890b_sys.modules.get(_ember_61c7220b679f890b_alias)
    if _ember_61c7220b679f890b_candidate is not None and all(_ember_61c7220b679f890b_candidate is not item for item in _ember_61c7220b679f890b_existing):
        _ember_61c7220b679f890b_existing.append(_ember_61c7220b679f890b_candidate)
if len(_ember_61c7220b679f890b_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/semantic_stream.py')
if _ember_61c7220b679f890b_existing:
    _ember_61c7220b679f890b_module = _ember_61c7220b679f890b_existing[0]
    _ember_61c7220b679f890b_observed = getattr(_ember_61c7220b679f890b_module, '__file__', None)
    if _ember_61c7220b679f890b_observed is None or _ember_61c7220b679f890b_Path(_ember_61c7220b679f890b_observed).resolve() != _ember_61c7220b679f890b_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/infrastructure/tools/ember-restart-3b/semantic_stream.py')
else:
    _ember_61c7220b679f890b_spec = _ember_61c7220b679f890b_importlib.spec_from_file_location('_ember_issue2015_61c7220b679f890b', _ember_61c7220b679f890b_path)
    if _ember_61c7220b679f890b_spec is None or _ember_61c7220b679f890b_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/infrastructure/tools/ember-restart-3b/semantic_stream.py')
    _ember_61c7220b679f890b_module = _ember_61c7220b679f890b_importlib.module_from_spec(_ember_61c7220b679f890b_spec)
    for _ember_61c7220b679f890b_alias in _ember_61c7220b679f890b_aliases:
        _ember_61c7220b679f890b_prior = _ember_61c7220b679f890b_sys.modules.get(_ember_61c7220b679f890b_alias)
        if _ember_61c7220b679f890b_prior is not None and _ember_61c7220b679f890b_prior is not _ember_61c7220b679f890b_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/semantic_stream.py')
        _ember_61c7220b679f890b_sys.modules[_ember_61c7220b679f890b_alias] = _ember_61c7220b679f890b_module
    try:
        _ember_61c7220b679f890b_spec.loader.exec_module(_ember_61c7220b679f890b_module)
    except BaseException:
        for _ember_61c7220b679f890b_alias in _ember_61c7220b679f890b_aliases:
            if _ember_61c7220b679f890b_sys.modules.get(_ember_61c7220b679f890b_alias) is _ember_61c7220b679f890b_module:
                _ember_61c7220b679f890b_sys.modules.pop(_ember_61c7220b679f890b_alias, None)
        raise
for _ember_61c7220b679f890b_alias in _ember_61c7220b679f890b_aliases:
    _ember_61c7220b679f890b_prior = _ember_61c7220b679f890b_sys.modules.get(_ember_61c7220b679f890b_alias)
    if _ember_61c7220b679f890b_prior is not None and _ember_61c7220b679f890b_prior is not _ember_61c7220b679f890b_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/semantic_stream.py')
    _ember_61c7220b679f890b_sys.modules[_ember_61c7220b679f890b_alias] = _ember_61c7220b679f890b_module
ManifestBoundTokenStream = getattr(_ember_61c7220b679f890b_module, 'ManifestBoundTokenStream')
# issue2015 exact-local-import-end:src/ember/infrastructure/tools/ember-restart-3b/semantic_stream.py

_SEQUENCE_LENGTH = 1024
_REQUIRED_BATCHES = (1, 2)
_MEMORY_GATE_BATCHES = (4, 8)
_COMPUTE_DTYPE = "torch.bfloat16"
_RTX_4090_BF16_DENSE_PEAK_FLOPS = 165e12
_RTX_4090_BF16_DENSE_PEAK_FLOPS_PROVENANCE = (
    "NVIDIA_GEFORCE_RTX_4090_BF16_TENSOR_CORE_DENSE_165_TFLOPS"
)
_MAX_POWER_SAMPLE_GAP_MULTIPLIER = 1.5


def screen_plan(*, total_vram_bytes: int) -> dict[str, object]:
    if not isinstance(total_vram_bytes, int) or total_vram_bytes <= 0:
        raise ValueError("total VRAM bytes must be positive")
    return {
        "sequence_length": _SEQUENCE_LENGTH,
        "required_batches": list(_REQUIRED_BATCHES),
        "memory_gate_only_batches": list(_MEMORY_GATE_BATCHES),
        "max_peak_allocated_bytes": int(total_vram_bytes * 0.8),
        "minimum_free_margin_bytes": int(1.5 * 1024**3),
    }


def screen_receipt(
    *,
    model_config_sha256: str,
    optimizer_contract_sha256: str,
    tokenizer_sha256: str,
    checkpoint_manifest_sha256: str,
    source_sha256: str,
    total_vram_bytes: int,
    available_vram_bytes: int | None = None,
    custody: dict[str, Any] | None = None,
    batch_measurements: list[dict[str, Any]],
) -> dict[str, object]:
    plan = screen_plan(total_vram_bytes=total_vram_bytes)
    identity_hashes = (
        model_config_sha256,
        optimizer_contract_sha256,
        tokenizer_sha256,
        checkpoint_manifest_sha256,
        source_sha256,
    )
    if any(not _is_sha256(value) for value in identity_hashes):
        raise ValueError("screen receipt identity hashes must be lowercase SHA-256 digests")
    required = list(plan["required_batches"])
    max_peak = int(plan["max_peak_allocated_bytes"])
    available = total_vram_bytes if available_vram_bytes is None else available_vram_bytes
    if not isinstance(available, int) or available <= 0 or available > total_vram_bytes:
        raise ValueError("available VRAM bytes must be a positive value no greater than total VRAM")
    minimum_margin = int(plan["minimum_free_margin_bytes"])
    for item in batch_measurements:
        if not isinstance(item.get("elapsed_seconds"), (int, float)) or item["elapsed_seconds"] <= 0:
            raise ValueError("screen step timing must be positive")
        if not isinstance(item.get("peak_allocated_bytes"), int) or item["peak_allocated_bytes"] > max_peak:
            raise MemoryError("0.8 VRAM governor rejects the measured allocation")
        if not isinstance(item.get("peak_reserved_bytes"), int) or item["peak_reserved_bytes"] < item["peak_allocated_bytes"]:
            raise ValueError("screen reserved peak must cover allocated peak")
        if available - item["peak_reserved_bytes"] < minimum_margin:
            raise MemoryError("1.5 GiB free-memory governor rejects the measured reservation")
    observed = [item.get("batch_size") for item in batch_measurements]
    if observed != required:
        raise ValueError("screen receipt requires exactly batch-1 then batch-2 full steps")
    required_custody = {"hardware_runtime", "source_closure_sha256", "ember_lab_schedule_receipt_sha256", "disk_budget_receipt_sha256"}
    if not isinstance(custody, dict) or set(custody) != required_custody:
        raise ValueError("screen receipt custody must bind runtime, source closure, ember-lab, and disk evidence")
    runtime = custody["hardware_runtime"]
    runtime_fields = {"gpu_name", "compute_capability", "torch_version", "cuda_version", "cudnn_version", "optimizer_implementation", "optimizer_version"}
    if not isinstance(runtime, dict) or not runtime_fields.issubset(runtime) or any(not isinstance(runtime[field], str) or not runtime[field].strip() for field in runtime_fields):
        raise ValueError("screen receipt custody runtime identity is incomplete")
    closure = custody["source_closure_sha256"]
    needed_sources = {"model.py", "batch.py", "semantic_stream.py", "run_vertical_slice.py", "parameter_counter.py", "native_compute_screen.py"}
    if not isinstance(closure, dict) or set(closure) != needed_sources or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in closure.values()):
        raise ValueError("screen receipt custody source closure is incomplete")
    if any(not isinstance(custody[key], str) or not re.fullmatch(r"[0-9a-f]{64}", custody[key]) for key in ("ember_lab_schedule_receipt_sha256", "disk_budget_receipt_sha256")):
        raise ValueError("screen receipt custody receipt hashes are invalid")
    return {
        "schema_version": "ember-native-compute-screen-v1",
        "result": "MEASURED",
        "admission": "NON_ADMISSIBLE_COMPUTE_PRIMITIVE",
        "operation": "CLEAN_GENESIS_FULL_FORWARD_BACKWARD_OPTIMIZER_STEP",
        "sequence_length": _SEQUENCE_LENGTH,
        "required_batches": required,
        "memory_gate_only_batches": list(plan["memory_gate_only_batches"]),
        "vram_governor": {"maximum_fraction": 0.8, "minimum_free_margin_bytes": plan["minimum_free_margin_bytes"]},
        "model_config_sha256": model_config_sha256,
        "optimizer_contract_sha256": optimizer_contract_sha256,
        "tokenizer_sha256": tokenizer_sha256,
        "checkpoint_manifest_sha256": checkpoint_manifest_sha256,
        "source_sha256": source_sha256,
        "total_vram_bytes": total_vram_bytes,
        "available_vram_bytes_at_dispatch": available,
        "custody": custody,
        "steps": batch_measurements,
    }

_SCREEN_JOB_ID = "ember-02b-native-clean-genesis-screen-b1-b2-seed83"
_SOURCE_NAMES = (
    "model.py",
    "batch.py",
    "semantic_stream.py",
    "run_vertical_slice.py",
    "parameter_counter.py",
    "native_compute_screen.py",
)
_OPERATING_FLOORS_GIB = {"B": 250.0, "C": 150.0}
_MAX_WRITE_GIB = {"B": 0.1, "C": 0.1}
_MAX_SCHEDULE_FUTURE_SKEW_MS = 60_000


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _validate_source_closure(closure: object) -> dict[str, str]:
    if not isinstance(closure, dict) or set(closure) != set(_SOURCE_NAMES):
        raise ValueError("source closure must bind every native screen source")
    if any(not _is_sha256(value) for value in closure.values()):
        raise ValueError("source closure must use lowercase SHA-256 digests")
    return dict(closure)


def _source_closure(root: Path) -> dict[str, str]:
    return {name: _sha256(root / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b" / name) for name in _SOURCE_NAMES}


def _assert_source_closure_stable(before: dict[str, str], after: dict[str, str]) -> None:
    if before != after:
        raise RuntimeError("native screen source closure changed before receipt publication")


def _read_json_receipt(path: Path, label: str) -> tuple[dict[str, object], str]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} must be readable JSON") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload, hashlib.sha256(raw).hexdigest()


def _load_screen_authority(*, config_path: Path, reference_checkpoint_manifest: Path) -> dict[str, object]:
    """Parse every authority object from the same bytes used for its receipt hash."""

    config_payload, config_sha256 = _read_json_receipt(config_path, "model config")
    checkpoint_payload, checkpoint_sha256 = _read_json_receipt(
        reference_checkpoint_manifest,
        "reference checkpoint manifest",
    )
    if checkpoint_payload.get("schema_version") not in {
        "ember-sparse-checkpoint-v3",
        "ember-sparse-checkpoint-v4",
    }:
        raise ValueError("reference checkpoint manifest has an invalid schema")
    try:
        optimizer_payload = config_payload["training"]["optimizer"]
    except (KeyError, TypeError) as error:
        raise ValueError("model config must declare the production optimizer") from error
    return {
        "config": RestartDecoderConfig.from_contract_payload(config_payload),
        "optimizer_contract": validate_optimizer_contract(optimizer_payload),
        "model_config_sha256": config_sha256,
        "checkpoint_manifest_sha256": checkpoint_sha256,
    }


def _dispatch_binding(*, output: Path, seed: int) -> dict[str, object]:
    if not isinstance(seed, int) or seed < 0:
        raise ValueError("screen dispatch seed must be a nonnegative integer")
    payload = {
        "job_id": _SCREEN_JOB_ID,
        "sequence_length": _SEQUENCE_LENGTH,
        "required_batches": list(_REQUIRED_BATCHES),
        "seed": seed,
        "output_path_sha256": hashlib.sha256(str(output.resolve()).encode("utf-8")).hexdigest(),
    }
    return {
        "payload": payload,
        "sha256": hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
    }


def _dispatch_sha256(*, output: Path, seed: int) -> str:
    return str(_dispatch_binding(output=output, seed=seed)["sha256"])

def _validated_daemon_identity(value: object, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"binary_sha256", "source_sha256"} or any(not _is_sha256(digest) for digest in value.values()):
        raise ValueError(f"{label} must bind lowercase binary/source SHA-256 values")
    return dict(value)


def _validate_schedule_receipt(path: Path, *, now_ms: int | None = None) -> dict[str, object]:
    payload, digest = _read_json_receipt(path, "ember-lab schedule receipt")
    runs = payload.get("runs")
    if payload.get("schema_version") != "ember-lab-schedule-alarm-state-v1" or not isinstance(runs, list):
        raise ValueError("ember-lab schedule receipt has an invalid schema")
    if not isinstance(payload.get("generated_at_ms"), int) or payload["generated_at_ms"] <= 0:
        raise ValueError("ember-lab schedule receipt lacks an integer generation timestamp")
    top_identity = _validated_daemon_identity(payload.get("ember_lab_identity"), "ember-lab identity")
    matches = [run for run in runs if isinstance(run, dict) and run.get("job_id") == _SCREEN_JOB_ID]
    if len(matches) != 1:
        raise ValueError("ember-lab schedule receipt does not bind the native B1/B2 prediction")
    run = matches[0]
    if run.get("artifact_class") != "compute-primitive" or run.get("predicted_tokens") != 3072 or run.get("predicted_duration_ms") != 720000:
        raise ValueError("ember-lab schedule receipt does not bind the native B1/B2 prediction")
    timestamps = ("predicted_at_ms", "predicted_program_completion_ms", "absolute_deadline_ms")
    if any(not isinstance(run.get(field), int) or run[field] <= 0 for field in timestamps):
        raise ValueError("ember-lab schedule receipt lacks integer prediction timestamps and deadline")
    if not run["predicted_at_ms"] <= run["predicted_program_completion_ms"] <= run["absolute_deadline_ms"]:
        raise ValueError("ember-lab schedule prediction timestamps are not ordered")
    observed_now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    if not isinstance(observed_now_ms, int) or isinstance(observed_now_ms, bool) or observed_now_ms <= 0:
        raise ValueError("schedule validation requires a positive current timestamp")
    maximum_issued_timestamp_ms = observed_now_ms + _MAX_SCHEDULE_FUTURE_SKEW_MS
    if payload["generated_at_ms"] > maximum_issued_timestamp_ms or run["predicted_at_ms"] > maximum_issued_timestamp_ms:
        raise ValueError("ember-lab schedule exceeds bounded future clock skew")
    if observed_now_ms >= run["absolute_deadline_ms"]:
        raise ValueError("ember-lab schedule deadline has elapsed")
    prediction_identity = _validated_daemon_identity(run.get("prediction_daemon_identity"), "ember-lab prediction identity")
    if prediction_identity != top_identity:
        raise ValueError("ember-lab prediction identity does not match the schedule identity")
    return {
        "sha256": digest,
        "generated_at_ms": payload["generated_at_ms"],
        "predicted_at_ms": run["predicted_at_ms"],
        "predicted_program_completion_ms": run["predicted_program_completion_ms"],
        "absolute_deadline_ms": run["absolute_deadline_ms"],
        "predicted_duration_ms": run["predicted_duration_ms"],
        "predicted_tokens": run["predicted_tokens"],
        "prediction_daemon_identity": prediction_identity,
    }


def _validate_dispatch_payload(dispatch: object) -> dict[str, object]:
    required = {"job_id", "sequence_length", "required_batches", "seed", "output_path_sha256"}
    if not isinstance(dispatch, dict) or set(dispatch) != required:
        raise ValueError("disk preflight must bind the canonical screen dispatch")
    if dispatch.get("job_id") != _SCREEN_JOB_ID or dispatch.get("sequence_length") != _SEQUENCE_LENGTH or dispatch.get("required_batches") != list(_REQUIRED_BATCHES):
        raise ValueError("disk preflight must bind the canonical screen dispatch")
    if not isinstance(dispatch.get("seed"), int) or dispatch["seed"] < 0 or not _is_sha256(dispatch.get("output_path_sha256")):
        raise ValueError("disk preflight must bind the canonical screen dispatch")
    return dict(dispatch)


def _canonical_dispatch_sha256(dispatch: dict[str, object]) -> str:
    return hashlib.sha256(json.dumps(dispatch, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def disk_preflight_receipt(
    *,
    free_bytes_by_drive: dict[str, int],
    source_closure_sha256: dict[str, str],
    ember_lab_schedule_receipt_sha256: str,
    dispatch_sha256: str,
    dispatch: dict[str, object],
) -> dict[str, object]:
    closure = _validate_source_closure(source_closure_sha256)
    canonical_dispatch = _validate_dispatch_payload(dispatch)
    if not _is_sha256(ember_lab_schedule_receipt_sha256) or not _is_sha256(dispatch_sha256):
        raise ValueError("disk preflight must bind lowercase schedule and dispatch SHA-256 values")
    if dispatch_sha256 != _canonical_dispatch_sha256(canonical_dispatch):
        raise ValueError("disk preflight dispatch digest does not match its canonical dispatch")
    if set(free_bytes_by_drive) != set(_OPERATING_FLOORS_GIB) or any(not isinstance(value, int) or value < 0 for value in free_bytes_by_drive.values()):
        raise ValueError("disk preflight requires observed B and C free bytes")
    observed = {drive: round(free_bytes_by_drive[drive] / 1024**3, 6) for drive in _OPERATING_FLOORS_GIB}
    projected = {drive: round(observed[drive] - _MAX_WRITE_GIB[drive], 6) for drive in _OPERATING_FLOORS_GIB}
    if any(projected[drive] < _OPERATING_FLOORS_GIB[drive] for drive in _OPERATING_FLOORS_GIB):
        raise ValueError("disk preflight projected end crosses an operating floor")
    return {
        "schema_version": "ember-native-screen-disk-preflight-v1",
        "job_id": _SCREEN_JOB_ID,
        "result": "PASSED",
        "max_b_write_gib": _MAX_WRITE_GIB["B"],
        "max_c_write_gib": _MAX_WRITE_GIB["C"],
        "operating_floors_gib": dict(_OPERATING_FLOORS_GIB),
        "observed_free_gib": observed,
        "projected_end_free_gib": projected,
        "source_closure_sha256": closure,
        "ember_lab_schedule_receipt_sha256": ember_lab_schedule_receipt_sha256,
        "dispatch_sha256": dispatch_sha256,
        "dispatch": canonical_dispatch,
    }


def write_disk_preflight(
    *,
    path: Path,
    source_closure_sha256: dict[str, str],
    ember_lab_schedule_receipt_sha256: str,
    dispatch_sha256: str,
    dispatch: dict[str, object],
    free_bytes_by_drive: dict[str, int] | None = None,
) -> dict[str, object]:
    observed = free_bytes_by_drive
    if observed is None:
        observed = {drive: shutil.disk_usage(f"{drive}:\\").free for drive in _OPERATING_FLOORS_GIB}
    receipt = disk_preflight_receipt(
        free_bytes_by_drive=observed,
        source_closure_sha256=source_closure_sha256,
        ember_lab_schedule_receipt_sha256=ember_lab_schedule_receipt_sha256,
        dispatch_sha256=dispatch_sha256,
        dispatch=dispatch,
    )
    _atomic_json(path, receipt)
    return receipt


def _validate_disk_preflight(
    path: Path,
    *,
    expected_schedule_sha256: str | None = None,
    expected_source_closure_sha256: dict[str, str] | None = None,
    expected_dispatch_sha256: str | None = None,
) -> dict[str, object]:
    payload, digest = _read_json_receipt(path, "disk preflight receipt")
    if payload.get("schema_version") != "ember-native-screen-disk-preflight-v1" or payload.get("job_id") != _SCREEN_JOB_ID or payload.get("result") != "PASSED":
        raise ValueError("disk preflight receipt does not bind the native screen job")
    if payload.get("max_b_write_gib") != _MAX_WRITE_GIB["B"] or payload.get("max_c_write_gib") != _MAX_WRITE_GIB["C"] or payload.get("operating_floors_gib") != _OPERATING_FLOORS_GIB:
        raise ValueError("disk preflight receipt does not bind the approved B/C budget and floors")
    closure = _validate_source_closure(payload.get("source_closure_sha256"))
    if expected_source_closure_sha256 is not None and closure != _validate_source_closure(expected_source_closure_sha256):
        raise ValueError("disk preflight source closure does not match the executable screen")
    schedule_digest = payload.get("ember_lab_schedule_receipt_sha256")
    dispatch_digest = payload.get("dispatch_sha256")
    if not _is_sha256(schedule_digest) or not _is_sha256(dispatch_digest):
        raise ValueError("disk preflight receipt lacks canonical schedule and dispatch digests")
    canonical_dispatch = _validate_dispatch_payload(payload.get("dispatch"))
    if dispatch_digest != _canonical_dispatch_sha256(canonical_dispatch):
        raise ValueError("disk preflight dispatch digest does not match its canonical dispatch")
    if expected_schedule_sha256 is not None and schedule_digest != expected_schedule_sha256:
        raise ValueError("disk preflight does not match the validated ember-lab schedule")
    if expected_dispatch_sha256 is not None and dispatch_digest != expected_dispatch_sha256:
        raise ValueError("disk preflight does not match the exact screen dispatch")
    observed = payload.get("observed_free_gib")
    projected = payload.get("projected_end_free_gib")
    if not isinstance(observed, dict) or not isinstance(projected, dict) or set(observed) != set(_OPERATING_FLOORS_GIB) or set(projected) != set(_OPERATING_FLOORS_GIB):
        raise ValueError("disk preflight receipt lacks observed and projected B/C free space")
    for drive, floor in _OPERATING_FLOORS_GIB.items():
        if not isinstance(observed[drive], (int, float)) or not isinstance(projected[drive], (int, float)) or projected[drive] < floor:
            raise ValueError("disk preflight receipt crosses an operating floor")
        if round(float(observed[drive]) - _MAX_WRITE_GIB[drive], 6) != round(float(projected[drive]), 6):
            raise ValueError("disk preflight projected end does not match its write budget")
    return {
        "sha256": digest,
        "dispatch_sha256": dispatch_digest,
        "dispatch": canonical_dispatch,
        "max_write_gib": {"B": payload["max_b_write_gib"], "C": payload["max_c_write_gib"]},
        "operating_floors_gib": payload["operating_floors_gib"],
        "observed_free_gib": observed,
        "projected_end_free_gib": projected,
    }

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _power_sample() -> dict[str, object]:
    """Read one GPU-board power sample from the driver, never from self-reported model state."""

    completed = subprocess.run(
        ["nvidia-smi", "--query-gpu=uuid,index,memory.used,power.draw,power.limit,driver_version,name", "--format=csv,noheader,nounits"],
        text=True, capture_output=True, check=False, timeout=5,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "nvidia-smi power query failed")
    fields = [field.strip() for field in completed.stdout.strip().split(",")]
    if len(fields) != 7:
        raise RuntimeError("nvidia-smi power query emitted an invalid row")
    return {
        "monotonic_s": time.monotonic(),
        "gpu_uuid": fields[0],
        "gpu_index": int(fields[1]),
        "memory_used_mib": float(fields[2]),
        "watts": float(fields[3]),
        "power_limit_w": float(fields[4]),
        "driver_version": fields[5],
        "gpu_name": fields[6],
    }


class _PowerSampler:
    """Low-overhead same-run GPU-board sampler; failures remove efficiency credit, not training custody."""

    def __init__(self, cadence_s: float = 1.0) -> None:
        self.cadence_s = cadence_s
        self.samples: list[dict[str, object]] = []
        self.missing_sample_count = 0
        self.errors: list[str] = []
        self.started_monotonic_s: float | None = None
        self.stopped_monotonic_s: float | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.started_monotonic_s = time.monotonic()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=self.cadence_s + 6.0)
        if self._thread.is_alive():
            self.missing_sample_count += 1
            self.errors.append("power sampler did not stop")
        self.stopped_monotonic_s = time.monotonic()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.samples.append(_power_sample())
            except Exception as error:
                self.missing_sample_count += 1
                self.errors.append(f"{type(error).__name__}: {error}")
            self._stop.wait(self.cadence_s)


def _power_efficiency(
    *,
    trace: dict[str, object],
    wall_s: float,
    tokens_processed: int,
    active_parameters: int,
    total_parameters: int,
    allocator_peak_vram_bytes: int,
    target_vector_sha256: str,
    checkpoint_manifest_sha256: str,
) -> dict[str, object]:
    """Derive board-energy quantities from raw same-run driver samples, or mark credit unavailable."""

    if not isinstance(wall_s, (int, float)) or wall_s <= 0:
        raise ValueError("power efficiency requires positive wall time")
    raw = json.dumps(trace, sort_keys=True, separators=(",", ":")).encode("utf-8")
    trace_sha256 = hashlib.sha256(raw).hexdigest()
    samples = trace.get("samples")
    missing = trace.get("missing_sample_count")
    cadence = trace.get("sampling_cadence_s")
    started = trace.get("started_monotonic_s")
    stopped = trace.get("stopped_monotonic_s")
    if not isinstance(samples, list) or not isinstance(missing, int) or missing < 0 or not isinstance(cadence, (int, float)) or cadence <= 0:
        raise ValueError("power trace has an invalid closed shape")
    if not isinstance(total_parameters, int) or total_parameters <= 0 or not isinstance(active_parameters, int) or active_parameters <= 0 or active_parameters > total_parameters:
        raise ValueError("power efficiency requires exact positive active and total parameter counts")
    if not isinstance(allocator_peak_vram_bytes, int) or allocator_peak_vram_bytes <= 0:
        raise ValueError("power efficiency requires a positive allocator peak VRAM measurement")
    anchors_valid = (
        isinstance(started, (int, float))
        and isinstance(stopped, (int, float))
        and math.isfinite(float(started))
        and math.isfinite(float(stopped))
        and float(stopped) > float(started)
    )
    trace_window_s = float(stopped) - float(started) if anchors_valid else None
    expected_samples = max(1, math.ceil(trace_window_s / float(cadence))) if trace_window_s is not None else max(1, math.ceil(float(wall_s) / float(cadence)))
    valid: list[dict[str, object]] = []
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        watts = sample.get("watts")
        limit = sample.get("power_limit_w")
        timestamp = sample.get("monotonic_s")
        memory_used_mib = sample.get("memory_used_mib")
        gpu_index = sample.get("gpu_index")
        if (
            not isinstance(watts, (int, float)) or not math.isfinite(float(watts)) or watts <= 0
            or not isinstance(limit, (int, float)) or not math.isfinite(float(limit)) or limit <= 0
            or not isinstance(timestamp, (int, float)) or not math.isfinite(float(timestamp))
            or not isinstance(memory_used_mib, (int, float)) or not math.isfinite(float(memory_used_mib)) or memory_used_mib <= 0
            or not isinstance(gpu_index, int) or isinstance(gpu_index, bool) or gpu_index < 0
            or not isinstance(sample.get("driver_version"), str) or not sample["driver_version"].strip()
            or not isinstance(sample.get("gpu_name"), str) or not sample["gpu_name"].strip()
            or not isinstance(sample.get("gpu_uuid"), str) or not sample["gpu_uuid"].strip()
        ):
            continue
        valid.append(sample)
    coverage_ratio = min(1.0, len(valid) / max(expected_samples, len(valid) + missing))
    base: dict[str, object] = {
        "energy_scope": "GPU_BOARD_ONLY",
        "raw_power_trace_sha256": trace_sha256,
        "sampling_cadence_s": float(cadence),
        "missing_sample_count": missing,
        "coverage_ratio": coverage_ratio,
        "started_monotonic_s": float(started) if isinstance(started, (int, float)) else None,
        "stopped_monotonic_s": float(stopped) if isinstance(stopped, (int, float)) else None,
        "trace_window_s": trace_window_s,
        "maximum_sample_gap_s": None,
        "wall_s": float(wall_s),
        "tokens_processed": int(tokens_processed),
        "tokens": int(tokens_processed),
        "active_flops": int(active_parameters) * 6 * int(tokens_processed),
        "active_param_pct": int(active_parameters) / int(total_parameters),
        "compute_dtype": _COMPUTE_DTYPE,
        "peak_flops": _RTX_4090_BF16_DENSE_PEAK_FLOPS,
        "peak_flops_provenance": _RTX_4090_BF16_DENSE_PEAK_FLOPS_PROVENANCE,
        "allocator_peak_vram_bytes": allocator_peak_vram_bytes,
        "peak_vram_bytes": allocator_peak_vram_bytes,
        "driver_peak_vram_bytes": None,
        "peak_vram_confirmed": False,
        "target_vector_sha256": target_vector_sha256,
        "checkpoint_manifest_sha256": checkpoint_manifest_sha256,
        "evaluation_receipt_sha256": None,
        "gpu_joules": None,
        "energy_j": None,
        "mean_watts": None,
        "avg_power_w": None,
        "peak_watts": None,
        "peak_power_w": None,
        "tok_s": int(tokens_processed) / float(wall_s),
        "tok_per_gpu_joule": None,
        "tok_j": None,
        "mfu": None,
    }
    if len(valid) != len(samples) or missing != 0 or coverage_ratio < 0.90 or not anchors_valid or trace_window_s is None or trace_window_s < float(wall_s):
        return {"result": "UNAVAILABLE", **base}
    identities = {
        (
            sample["driver_version"],
            sample["gpu_name"],
            sample["gpu_uuid"],
            int(sample["gpu_index"]),
            float(sample["power_limit_w"]),
        )
        for sample in valid
    }
    timestamps = [float(sample["monotonic_s"]) for sample in valid]
    temporal_gaps = [
        timestamps[0] - float(started),
        *(later - earlier for earlier, later in zip(timestamps, timestamps[1:])),
        float(stopped) - timestamps[-1],
    ] if timestamps else []
    maximum_sample_gap_s = max(temporal_gaps) if temporal_gaps else math.inf
    base["maximum_sample_gap_s"] = maximum_sample_gap_s
    if (
        len(identities) != 1
        or timestamps != sorted(set(timestamps))
        or any(gap < 0 for gap in temporal_gaps)
        or maximum_sample_gap_s > float(cadence) * _MAX_POWER_SAMPLE_GAP_MULTIPLIER
    ):
        return {"result": "UNAVAILABLE", **base}
    watts = [float(sample["watts"]) for sample in valid]
    mean = sum(watts) / len(watts)
    joules = mean * float(wall_s)
    active_flops = int(base["active_flops"])
    mfu = active_flops / (_RTX_4090_BF16_DENSE_PEAK_FLOPS * float(wall_s))
    driver_peak_vram_bytes = int(max(float(sample["memory_used_mib"]) for sample in valid) * 1024**2)
    if driver_peak_vram_bytes < allocator_peak_vram_bytes:
        base["driver_peak_vram_bytes"] = driver_peak_vram_bytes
        return {"result": "UNAVAILABLE", **base}
    base.update({
        "result": "MEASURED",
        "gpu_joules": joules,
        "energy_j": joules,
        "mean_watts": mean,
        "avg_power_w": mean,
        "peak_watts": max(watts),
        "peak_power_w": max(watts),
        "tok_per_gpu_joule": int(tokens_processed) / joules,
        "tok_j": int(tokens_processed) / joules,
        "mfu": mfu,
        "driver_peak_vram_bytes": driver_peak_vram_bytes,
        "peak_vram_confirmed": True,
        "gpu_power_limit_w": float(valid[-1]["power_limit_w"]),
        "gpu_driver_version": valid[-1]["driver_version"],
        "gpu_name": valid[-1]["gpu_name"],
        "gpu_uuid": valid[-1]["gpu_uuid"],
        "gpu_index": int(valid[-1]["gpu_index"]),
        "first_target_crossing_step": None,
    })
    return base
def _full_step(*, model: UnifiedDecoder, optimizer: torch.optim.Optimizer, record: dict[str, object], config: RestartDecoderConfig, batch_size: int, device: torch.device) -> dict[str, object]:
    batch = decode_owned_batch(record, config, device=device)
    input_ids = batch["input_ids"].repeat(batch_size, 1)
    target_ids = batch["target_ids"].repeat(batch_size, 1)
    torch.cuda.reset_peak_memory_stats(device)
    torch.cuda.synchronize(device)
    started = time.perf_counter()
    optimizer.zero_grad(set_to_none=True)
    logits = model(input_ids, active_expert="shared")
    loss = F.cross_entropy(logits.float().reshape(-1, config.vocab_size), target_ids.reshape(-1))
    if not torch.isfinite(loss):
        raise RuntimeError("native full-step screen produced a non-finite loss")
    loss.backward()
    optimizer.step()
    torch.cuda.synchronize(device)
    return {
        "batch_size": batch_size,
        "elapsed_seconds": time.perf_counter() - started,
        "loss": float(loss.detach().cpu()),
        "peak_allocated_bytes": int(torch.cuda.max_memory_allocated(device)),
        "peak_reserved_bytes": int(torch.cuda.max_memory_reserved(device)),
    }


def run_screen(*, receipt_path: Path, shards_root: Path, tokenizer_path: Path, reference_checkpoint_manifest: Path, ember_lab_schedule_receipt: Path, disk_budget_receipt: Path, output: Path, seed: int) -> dict[str, object]:
    """Run both required clean-genesis batch arms; call only through disk_budget_runner."""
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the native full-step screen")
    if not isinstance(seed, int) or seed < 0:
        raise ValueError("screen seed must be a nonnegative integer")
    if output.exists():
        raise FileExistsError("native screen output must be a fresh path")
    if not reference_checkpoint_manifest.is_file() or not ember_lab_schedule_receipt.is_file() or not disk_budget_receipt.is_file():
        raise ValueError("reference checkpoint, ember-lab schedule, and disk-budget receipts must exist")
    root = Path(__file__).resolve().parents[5]
    schedule_binding = _validate_schedule_receipt(ember_lab_schedule_receipt)
    source_closure_before = _source_closure(root)
    dispatch_binding = _dispatch_binding(output=output, seed=seed)
    dispatch_sha256 = str(dispatch_binding["sha256"])
    disk_preflight_binding = _validate_disk_preflight(
        disk_budget_receipt,
        expected_schedule_sha256=str(schedule_binding["sha256"]),
        expected_source_closure_sha256=source_closure_before,
        expected_dispatch_sha256=dispatch_sha256,
    )
    # This is deliberately before model allocation: all 26 shard bytes and tokenizer bytes are rechecked first.
    stream = ManifestBoundTokenStream.from_receipt(receipt_path=receipt_path, shards_root=shards_root, tokenizer_path=tokenizer_path)
    config_path = root / "configs" / "ember-restart-3b.json"
    authority = _load_screen_authority(
        config_path=config_path,
        reference_checkpoint_manifest=reference_checkpoint_manifest,
    )
    config = authority["config"]
    optimizer_contract = authority["optimizer_contract"]
    device = torch.device("cuda")
    available, total = torch.cuda.mem_get_info(device)
    plan = screen_plan(total_vram_bytes=int(total))
    if available < int(plan["minimum_free_margin_bytes"]):
        raise MemoryError("native screen dispatch lacks the 1.5 GiB GPU free-memory floor")
    record, _ = stream.next_episode(shard_index=0, token_offset=0, sequence_length=_SEQUENCE_LENGTH)
    steps: list[dict[str, object]] = []
    counts: dict[str, object] | None = None
    sampler = _PowerSampler(cadence_s=1.0)
    screen_started = time.perf_counter()
    sampler.start()
    for batch_size in _REQUIRED_BATCHES:
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        previous_dtype = torch.get_default_dtype()
        torch.set_default_dtype(torch.bfloat16)
        try:
            model = UnifiedDecoder(config, device=device, allow_production_allocation=True, genesis_seed=seed)
        finally:
            torch.set_default_dtype(previous_dtype)
        model.train()
        model._activate_expert("shared")
        counts = measure_parameter_counts(model)
        if int(counts["unique_parameters"]) < 3_000_000_000 or counts["active_expert_ids"] != ["shared"]:
            raise RuntimeError("native screen did not instantiate the required owned shared-active 3B path")
        optimizer = build_production_optimizer(model, optimizer_contract=optimizer_contract)
        steps.append(_full_step(model=model, optimizer=optimizer, record=record, config=config, batch_size=batch_size, device=device))
        del optimizer, model
        torch.cuda.empty_cache()
    sampler.stop()
    wall_s = time.perf_counter() - screen_started
    power_trace = {
        "schema_version": "ember-gpu-board-power-trace-v1",
        "sampling_cadence_s": sampler.cadence_s,
        "started_monotonic_s": sampler.started_monotonic_s,
        "stopped_monotonic_s": sampler.stopped_monotonic_s,
        "missing_sample_count": sampler.missing_sample_count,
        "errors": sampler.errors,
        "samples": sampler.samples,
    }
    power_trace_path = output.with_name(output.stem + ".power-trace.json")
    _atomic_json(power_trace_path, power_trace)
    target_vector_sha256 = hashlib.sha256(json.dumps({"sequence_length": _SEQUENCE_LENGTH, "required_batches": list(_REQUIRED_BATCHES)}, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    efficiency = _power_efficiency(
        trace=power_trace,
        wall_s=wall_s,
        tokens_processed=sum(_SEQUENCE_LENGTH * batch for batch in _REQUIRED_BATCHES),
        active_parameters=int(counts["active_parameters"]) if counts else 0,
        total_parameters=int(counts["unique_parameters"]) if counts else 0,
        allocator_peak_vram_bytes=max(int(step["peak_reserved_bytes"]) for step in steps),
        target_vector_sha256=target_vector_sha256,
        checkpoint_manifest_sha256=str(authority["checkpoint_manifest_sha256"]),
    )
    if _source_closure(root) != source_closure_before:
        raise RuntimeError("native screen source closure changed before receipt publication")
    result = screen_receipt(
        model_config_sha256=str(authority["model_config_sha256"]),
        optimizer_contract_sha256=hashlib.sha256(json.dumps(optimizer_contract, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
        tokenizer_sha256=stream.tokenizer_sha256,
        checkpoint_manifest_sha256=str(authority["checkpoint_manifest_sha256"]),
        source_sha256=_sha256(Path(__file__)),
        total_vram_bytes=int(total),
        available_vram_bytes=int(available),
        custody={"hardware_runtime": {"gpu_name": torch.cuda.get_device_name(device), "compute_capability": ".".join(map(str, torch.cuda.get_device_capability(device))), "torch_version": torch.__version__, "cuda_version": torch.version.cuda or "unavailable", "cudnn_version": str(torch.backends.cudnn.version()), "optimizer_implementation": str(optimizer_contract["implementation"]), "optimizer_version": __import__("bitsandbytes").__version__}, "source_closure_sha256": source_closure_before, "ember_lab_schedule_receipt_sha256": str(schedule_binding["sha256"]), "disk_budget_receipt_sha256": str(disk_preflight_binding["sha256"])},
        batch_measurements=steps,
    )
    result.update({
        "genesis_seed": seed,
        "reference_checkpoint_role": "CUSTODY_REFERENCE_ONLY_NOT_LOADED",
        "stream_receipt_sha256": stream.receipt_sha256,
        "total_parameters": counts["unique_parameters"] if counts else None,
        "active_parameters": counts["active_parameters"] if counts else None,
        "power_trace_path": power_trace_path.name,
        "energy_efficiency": efficiency,
        "validated_external": {
            "ember_lab_schedule": schedule_binding,
            "disk_preflight": disk_preflight_binding,
        },
    })
    _atomic_json(output, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--shards-root", type=Path)
    parser.add_argument("--tokenizer", type=Path)
    parser.add_argument("--reference-checkpoint-manifest", type=Path)
    parser.add_argument("--ember-lab-schedule-receipt", type=Path)
    parser.add_argument("--disk-budget-receipt", type=Path)
    parser.add_argument("--emit-disk-preflight", type=Path)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.emit_disk_preflight is not None:
        if args.ember_lab_schedule_receipt is None or args.output is None or args.seed is None:
            parser.error("--emit-disk-preflight requires --ember-lab-schedule-receipt --output --seed")
        root = Path(__file__).resolve().parents[5]
        schedule_binding = _validate_schedule_receipt(args.ember_lab_schedule_receipt)
        result = write_disk_preflight(
            path=args.emit_disk_preflight,
            source_closure_sha256=_source_closure(root),
            ember_lab_schedule_receipt_sha256=str(schedule_binding["sha256"]),
            dispatch_sha256=_dispatch_sha256(output=args.output, seed=args.seed),
            dispatch=dict(_dispatch_binding(output=args.output, seed=args.seed)["payload"]),
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    required = {
        "--receipt": args.receipt,
        "--shards-root": args.shards_root,
        "--tokenizer": args.tokenizer,
        "--reference-checkpoint-manifest": args.reference_checkpoint_manifest,
        "--ember-lab-schedule-receipt": args.ember_lab_schedule_receipt,
        "--disk-budget-receipt": args.disk_budget_receipt,
        "--seed": args.seed,
        "--output": args.output,
    }
    missing = [flag for flag, value in required.items() if value is None]
    if missing:
        parser.error(f"screen execution requires {' '.join(missing)}")
    try:
        print(json.dumps(run_screen(
            receipt_path=args.receipt,
            shards_root=args.shards_root,
            tokenizer_path=args.tokenizer,
            reference_checkpoint_manifest=args.reference_checkpoint_manifest,
            ember_lab_schedule_receipt=args.ember_lab_schedule_receipt,
            disk_budget_receipt=args.disk_budget_receipt,
            output=args.output,
            seed=args.seed,
        ), sort_keys=True))
    except Exception as error:
        parser.error(str(error))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
