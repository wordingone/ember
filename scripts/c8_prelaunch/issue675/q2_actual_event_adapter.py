# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Derive issue #675 target-only capture operands from one live model snapshot.

This is a bounded producer adapter, not a launcher.  Ember Lab remains the
dispatch authority and ``q2_capture_writer`` remains the manifest authority.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping

import torch

from q2_capture_writer import write_capture
from q2_gradient_lineage import validate_gradient_lineage
from q2_model_lineage import validate_model_lineage
from q2_momentum_lineage import validate_momentum_lineage
import q2_muon_primitives as _muon_primitives
from q2_muon_primitives import muon_step_in_copy


_ADAPTER_SOURCE_PATH = Path(__file__).resolve()
_MUON_SOURCE_PATH = Path(_muon_primitives.__file__).resolve()


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
    b1m_receipt_path: Path,
    batch_manifest_path: Path,
) -> None:
    for key, receipt_path, code in (
        ("checkpoint_sha256", b2_receipt_path, "EVENT_LINEAGE_BINDING_MISMATCH"),
        ("momentum_sha256", b1m_receipt_path, "EVENT_MOMENTUM_BINDING_MISMATCH"),
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
    target: torch.Tensor,
    gradient: torch.Tensor,
    momentum: torch.Tensor,
    learning_rate: float,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    try:
        result = muon_step_in_copy(
            target.clone(),
            gradient.clone(),
            momentum.clone(),
            learning_rate=learning_rate,
        )
    except Exception:
        _refuse("EVENT_STEP_FAILED")
    after = _snapshot(model)
    if not _same_state(baseline, after):
        _refuse("EVENT_STEP_MUTATED_LIVE_MODEL")
    if not isinstance(result, torch.Tensor):
        _refuse("EVENT_STEP_RESULT_INVALID")
    return result.detach().to(device="cpu").contiguous(), after


def capture_actual_event(
    *,
    custody_root: Path,
    run_id: str,
    lineage_run_id: str,
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

    _verify_executed_source_bindings(binding_files)
    _verify_lineage_receipt_binding(
        binding_files, b2_receipt_path, b1m_receipt_path, batch_manifest_path
    )
    baseline = _snapshot(model)
    try:
        validate_model_lineage(
            live_state=baseline,
            seed_manifest_path=seed_manifest_path,
            seed_model_path=seed_model_path,
            grown_model_path=grown_model_path,
            b2_receipt_path=b2_receipt_path,
            grow_operator_path=grow_operator_path,
            expected_run_id=lineage_run_id,
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
    pre = baseline[target_name].to(torch.float32)
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
        target=pre,
        gradient=gradient,
        momentum=reset_momentum,
        learning_rate=learning_rate,
    )
    transplant_post, transplant_state = _run_arm(
        model=model,
        baseline=baseline,
        target=pre,
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
