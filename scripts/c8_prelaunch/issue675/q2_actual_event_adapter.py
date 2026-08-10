# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Derive issue #675 target-only capture operands from one live model snapshot.

This is a bounded producer adapter, not a launcher.  Ember Lab remains the
dispatch authority and ``q2_capture_writer`` remains the manifest authority.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Callable, Mapping

import torch

from q2_capture_writer import CaptureWriteRefusal, validate_dispatch_preflight, write_capture
from q2_event_inputs import EventInputRefusal, validate_runtime_config
from q2_gradient_lineage import validate_gradient_lineage
from q2_model_lineage import validate_model_lineage
from q2_momentum_lineage import validate_momentum_lineage
import q2_muon_primitives as _muon_primitives
from q2_muon_primitives import muon_step_in_copy


_ADAPTER_SOURCE_PATH = Path(__file__).resolve()
_MUON_SOURCE_PATH = Path(_muon_primitives.__file__).resolve()
_BINDING_KEYS = {
    "batch_sha256",
    "b3_receipt_sha256",
    "checkpoint_sha256",
    "config_sha256",
    "momentum_sha256",
    "optimizer_sha256",
    "replay_sha256",
    "source_sha256",
    "threshold_sha256",
    "verifier_sha256",
}


class CaptureAdapterRefusal(ValueError):
    """Named refusal raised before a selectable capture manifest exists."""


def _refuse(code: str) -> None:
    raise CaptureAdapterRefusal(code)


def _snapshot(model: torch.nn.Module) -> dict[str, torch.Tensor]:
    state = model.state_dict()
    if not state or any(not isinstance(value, torch.Tensor) for value in state.values()):
        _refuse("EVENT_MODEL_STATE_INVALID")
    return {
        name: value.detach().to(device="cpu").contiguous().clone()
        for name, value in state.items()
    }


def _same_state(
    left: Mapping[str, torch.Tensor], right: Mapping[str, torch.Tensor]
) -> bool:
    return set(left) == set(right) and all(
        left[name].dtype == right[name].dtype
        and tuple(left[name].shape) == tuple(right[name].shape)
        and torch.equal(left[name], right[name])
        for name in left
    )


def _has_reparse_component(path: Path, stop: Path | None = None) -> bool:
    """Detect symlinks and Windows junction/reparse components without following them."""

    current = Path(os.path.abspath(os.fspath(path)))
    boundary = Path(os.path.abspath(os.fspath(stop))) if stop is not None else None
    while True:
        try:
            status = current.lstat()
        except OSError:
            return True
        attributes = getattr(status, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if stat.S_ISLNK(status.st_mode) or bool(attributes & reparse_flag):
            return True
        if current == boundary:
            return False
        parent = current.parent
        if parent == current:
            return boundary is not None
        current = parent


def _admit_custody_root(path: Path) -> Path:
    supplied = Path(path)
    if _has_reparse_component(supplied):
        _refuse("EVENT_CUSTODY_ROOT_REFUSED")
    try:
        canonical = supplied.resolve(strict=True)
    except OSError:
        _refuse("EVENT_CUSTODY_ROOT_REFUSED")
    if not canonical.is_dir():
        _refuse("EVENT_CUSTODY_ROOT_REFUSED")
    return canonical


def _admit_file(root: Path, path: Path, code: str) -> Path:
    """Resolve one immutable input inside custody before model/GPU access."""

    supplied = Path(path)
    lexical = Path(os.path.abspath(os.fspath(supplied)))
    if not lexical.is_relative_to(root) or _has_reparse_component(lexical, root):
        _refuse(code)
    try:
        canonical = lexical.resolve(strict=True)
    except OSError:
        _refuse(code)
    if not canonical.is_file() or not canonical.is_relative_to(root):
        _refuse(code)
    return canonical


def _admit_directory(root: Path, path: Path, code: str) -> Path:
    supplied = Path(path)
    lexical = Path(os.path.abspath(os.fspath(supplied)))
    if not lexical.is_relative_to(root) or _has_reparse_component(lexical, root):
        _refuse(code)
    try:
        canonical = lexical.resolve(strict=True)
    except OSError:
        _refuse(code)
    if not canonical.is_dir() or not canonical.is_relative_to(root):
        _refuse(code)
    return canonical


def _admit_event_inputs(
    root: Path,
    binding_files: Mapping[str, Path],
    file_inputs: Mapping[str, Path],
    gradient_data_root: Path,
) -> tuple[dict[str, Path], dict[str, Path], Path]:
    """Close every caller path before state snapshot, CUDA, or tensor loading."""

    if set(binding_files) != _BINDING_KEYS:
        _refuse("EVENT_BINDING_SET_INVALID")
    admitted_bindings = {
        key: _admit_file(root, path, "EVENT_BINDING_CUSTODY_REFUSED")
        for key, path in binding_files.items()
    }
    admitted_files = {
        key: _admit_file(root, path, f"EVENT_{key.upper()}_CUSTODY_REFUSED")
        for key, path in file_inputs.items()
    }
    admitted_data_root = _admit_directory(
        root, gradient_data_root, "EVENT_GRADIENT_ROOT_CUSTODY_REFUSED"
    )
    return admitted_bindings, admitted_files, admitted_data_root


def _verify_executed_source_bindings(binding_files: Mapping[str, Path]) -> None:
    for key, source, code in (
        ("source_sha256", _ADAPTER_SOURCE_PATH, "EVENT_SOURCE_BINDING_MISMATCH"),
        ("optimizer_sha256", _MUON_SOURCE_PATH, "EVENT_OPTIMIZER_BINDING_MISMATCH"),
    ):
        try:
            bound = Path(binding_files[key]).read_bytes()
            expected = source.read_bytes()
        except (KeyError, OSError):
            _refuse(code)
        if bound != expected:
            _refuse(code)


def _verify_lineage_receipt_binding(
    binding_files: Mapping[str, Path],
    b2_receipt_path: Path,
    runtime_config_path: Path,
    b1m_receipt_path: Path,
    b3_receipt_path: Path,
    batch_manifest_path: Path,
) -> None:
    for key, receipt_path, code in (
        ("config_sha256", runtime_config_path, "EVENT_RUNTIME_CONFIG_BINDING_MISMATCH"),
        ("checkpoint_sha256", b2_receipt_path, "EVENT_LINEAGE_BINDING_MISMATCH"),
        ("momentum_sha256", b1m_receipt_path, "EVENT_MOMENTUM_BINDING_MISMATCH"),
        ("b3_receipt_sha256", b3_receipt_path, "EVENT_GRADIENT_RECEIPT_BINDING_MISMATCH"),
        ("batch_sha256", batch_manifest_path, "EVENT_BATCH_BINDING_MISMATCH"),
    ):
        try:
            bound = Path(binding_files[key]).read_bytes()
            receipt = Path(receipt_path).read_bytes()
        except (KeyError, OSError):
            _refuse("EVENT_LINEAGE_BINDING_UNAVAILABLE")
        if bound != receipt:
            _refuse(code)


def _run_arm(
    *,
    model: torch.nn.Module,
    baseline: Mapping[str, torch.Tensor],
    target_name: str,
    gradient: torch.Tensor,
    momentum: torch.Tensor,
    learning_rate: float,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    parameters = dict(model.named_parameters())
    target = parameters.get(target_name)
    if target is None:
        _refuse("EVENT_TARGET_NOT_PARAMETER")
    if target.device.type != "cuda":
        _refuse("EVENT_GPU_APPLICATION_REQUIRED")
    try:
        result = muon_step_in_copy(
            target.detach().to(dtype=torch.float32).clone(),
            gradient.to(device=target.device, dtype=torch.float32),
            momentum.to(device=target.device, dtype=torch.float32),
            learning_rate=learning_rate,
        )
        with torch.no_grad():
            target.copy_(result)
        torch.cuda.synchronize(target.device)
    except Exception:
        _refuse("EVENT_STEP_FAILED")
    after = _snapshot(model)
    for name in sorted(baseline):
        if name != target_name and not torch.equal(baseline[name], after[name]):
            _refuse("EVENT_STEP_MUTATED_NON_TARGET")
    try:
        model.load_state_dict(dict(baseline), strict=True)
        torch.cuda.synchronize(target.device)
    except Exception:
        _refuse("EVENT_STEP_RESTORE_FAILED")
    if not _same_state(baseline, _snapshot(model)):
        _refuse("EVENT_STEP_RESTORE_MISMATCH")
    return after[target_name], after


def capture_actual_event(
    *,
    custody_root: Path,
    run_id: str,
    lineage_run_id: str,
    expected_source_commit: str,
    dispatch_receipt_path: Path,
    binding_files: Mapping[str, Path],
    model: torch.nn.Module,
    target_name: str,
    reset_momentum: torch.Tensor,
    transplant_momentum: torch.Tensor,
    loss_replay: Callable[[torch.Tensor, dict[str, torch.Tensor]], float],
    learning_rate: float,
    optimizer_scale: float,
    seed_manifest_path: Path,
    seed_model_path: Path,
    seed_optimizer_path: Path,
    grown_model_path: Path,
    b2_receipt_path: Path,
    runtime_config_path: Path,
    b1m_receipt_path: Path,
    b3_receipt_path: Path,
    batch_manifest_path: Path,
    persisted_pre_momentum_path: Path,
    persisted_gradient_path: Path,
    gradient_data_root: Path,
    expected_batch_sha256: str,
    grow_operator_path: Path,
    n_layers: int,
) -> Path:
    """Derive both target arms and prove the live model stayed byte-identical."""

    try:
        custody = _admit_custody_root(custody_root)
        dispatch_receipt_path = _admit_file(
            custody, dispatch_receipt_path, "EVENT_DISPATCH_PREFLIGHT_REFUSED"
        )
        dispatch, _dispatch_raw = validate_dispatch_preflight(
            dispatch_receipt_path, custody
        )
    except (OSError, CaptureWriteRefusal, CaptureAdapterRefusal):
        _refuse("EVENT_DISPATCH_PREFLIGHT_REFUSED")
    if dispatch["job_id"] != run_id:
        _refuse("EVENT_DISPATCH_JOB_MISMATCH")
    if dispatch["source_commit"] != expected_source_commit:
        _refuse("EVENT_DISPATCH_SOURCE_MISMATCH")
    binding_files, admitted, gradient_data_root = _admit_event_inputs(
        custody,
        binding_files,
        {
            "seed_manifest": seed_manifest_path,
            "seed_model": seed_model_path,
            "seed_optimizer": seed_optimizer_path,
            "grown_model": grown_model_path,
            "b2_receipt": b2_receipt_path,
            "runtime_config": runtime_config_path,
            "b1m_receipt": b1m_receipt_path,
            "b3_receipt": b3_receipt_path,
            "batch_manifest": batch_manifest_path,
            "persisted_pre_momentum": persisted_pre_momentum_path,
            "persisted_gradient": persisted_gradient_path,
            "grow_operator": grow_operator_path,
        },
        gradient_data_root,
    )
    seed_manifest_path = admitted["seed_manifest"]
    seed_model_path = admitted["seed_model"]
    seed_optimizer_path = admitted["seed_optimizer"]
    grown_model_path = admitted["grown_model"]
    b2_receipt_path = admitted["b2_receipt"]
    runtime_config_path = admitted["runtime_config"]
    b1m_receipt_path = admitted["b1m_receipt"]
    b3_receipt_path = admitted["b3_receipt"]
    batch_manifest_path = admitted["batch_manifest"]
    persisted_pre_momentum_path = admitted["persisted_pre_momentum"]
    persisted_gradient_path = admitted["persisted_gradient"]
    grow_operator_path = admitted["grow_operator"]
    _verify_executed_source_bindings(binding_files)
    _verify_lineage_receipt_binding(
        binding_files,
        b2_receipt_path,
        runtime_config_path,
        b1m_receipt_path,
        b3_receipt_path,
        batch_manifest_path,
    )
    try:
        validate_runtime_config(runtime_config_path, expected_source_commit)
    except EventInputRefusal:
        _refuse("EVENT_RUNTIME_CONFIG_REFUSED")
    baseline = _snapshot(model)
    try:
        validate_model_lineage(
            live_state=baseline,
            seed_manifest_path=seed_manifest_path,
            seed_model_path=seed_model_path,
            grown_model_path=grown_model_path,
            b2_receipt_path=b2_receipt_path,
            grow_operator_path=grow_operator_path,
            runtime_config_path=runtime_config_path,
            expected_run_id=lineage_run_id,
            expected_source_commit=expected_source_commit,
            n_layers=n_layers,
        )
    except Exception:
        _refuse("EVENT_MODEL_LINEAGE_REFUSED")
    try:
        validate_momentum_lineage(
            seed_manifest_path=seed_manifest_path,
            seed_model_path=seed_model_path,
            seed_optimizer_path=seed_optimizer_path,
            b1m_receipt_path=b1m_receipt_path,
            persisted_pre_momentum_path=persisted_pre_momentum_path,
            target_name=target_name,
            reset_momentum=reset_momentum,
            transplant_momentum=transplant_momentum,
            expected_run_id=lineage_run_id,
        )
    except Exception:
        _refuse("EVENT_MOMENTUM_LINEAGE_REFUSED")
    try:
        gradient = validate_gradient_lineage(
            b3_receipt_path=b3_receipt_path,
            persisted_gradient_path=persisted_gradient_path,
            data_root=gradient_data_root,
            target_name=target_name,
            expected_run_id=run_id,
            expected_batch_sha256=expected_batch_sha256,
        )
    except Exception:
        _refuse("EVENT_GRADIENT_LINEAGE_REFUSED")
    if target_name not in baseline:
        _refuse("EVENT_TARGET_NOT_FOUND")
    target_parameter = dict(model.named_parameters()).get(target_name)
    if target_parameter is None:
        _refuse("EVENT_TARGET_NOT_PARAMETER")
    if target_parameter.device.type != "cuda":
        _refuse("EVENT_GPU_APPLICATION_REQUIRED")
    pre = baseline[target_name]
    if gradient.shape != pre.shape:
        _refuse("EVENT_GRADIENT_TARGET_SHAPE_MISMATCH")
    non_target_pre = {
        name: value for name, value in baseline.items() if name != target_name
    }
    if not non_target_pre:
        _refuse("EVENT_NON_TARGET_STATE_EMPTY")

    reset_post, reset_state = _run_arm(
        model=model,
        baseline=baseline,
        target_name=target_name,
        gradient=gradient,
        momentum=reset_momentum,
        learning_rate=learning_rate,
    )
    transplant_post, transplant_state = _run_arm(
        model=model,
        baseline=baseline,
        target_name=target_name,
        gradient=gradient,
        momentum=transplant_momentum,
        learning_rate=learning_rate,
    )

    return write_capture(
        custody_root=custody_root,
        run_id=run_id,
        dispatch_receipt_path=dispatch_receipt_path,
        binding_files=binding_files,
        target_name=target_name,
        pre=pre,
        reset_post=reset_post,
        transplant_post=transplant_post,
        gradient=gradient,
        reset_momentum=reset_momentum,
        transplant_momentum=transplant_momentum,
        non_target_pre=non_target_pre,
        non_target_reset={
            name: value for name, value in reset_state.items() if name != target_name
        },
        non_target_transplant={
            name: value for name, value in transplant_state.items() if name != target_name
        },
        loss_replay=loss_replay,
        learning_rate=learning_rate,
        optimizer_scale=optimizer_scale,
    )
