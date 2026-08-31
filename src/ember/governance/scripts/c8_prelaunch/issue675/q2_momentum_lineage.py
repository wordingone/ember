# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Verify the canonical B1m momentum buffer and B3 gate pushforward.

This is an import-safe copy of the #580 Muon-local ID resolution rule and the
declared B3 gate row-duplication pushforward.  It performs no optimizer step.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Mapping

import torch


_SHA256 = re.compile(r"[0-9a-f]{64}")
_JOB_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}")


class MomentumLineageRefusal(ValueError):
    """Named refusal for missing, foreign, or substituted momentum."""


def _refuse(code: str) -> None:
    raise MomentumLineageRefusal(code)


def _sha(path: Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        _refuse("MOMENTUM_LINEAGE_FILE_UNAVAILABLE")


def _tensor(value: object, code: str) -> torch.Tensor:
    if (
        not isinstance(value, torch.Tensor)
        or value.dtype != torch.float32
        or value.ndim != 2
        or value.numel() == 0
        or not bool(torch.isfinite(value).all())
    ):
        _refuse(code)
    return value.detach().cpu().contiguous()


def _seed_tensor(value: object, code: str) -> torch.Tensor:
    if (
        not isinstance(value, torch.Tensor)
        or value.dtype not in {torch.bfloat16, torch.float32}
        or value.ndim != 2
        or value.numel() == 0
        or not bool(torch.isfinite(value).all())
    ):
        _refuse(code)
    return value.detach().cpu().contiguous()


def _muon_name_to_id(model_state: Mapping[str, torch.Tensor]) -> dict[str, int]:
    names: list[str] = []
    seen_storage: set[int] = set()
    for name, tensor in model_state.items():
        if not isinstance(name, str) or not isinstance(tensor, torch.Tensor):
            _refuse("SEED_MODEL_STATE_INVALID")
        pointer = tensor.data_ptr()
        if pointer in seen_storage:
            continue
        seen_storage.add(pointer)
        lowered = name.lower()
        if tensor.dim() == 2 and "embed" not in lowered and "head" not in lowered:
            names.append(name)
    return {name: index for index, name in enumerate(names)}


def resolve_seed_momentum(
    *, seed_model_path: Path, seed_optimizer_path: Path, target_name: str
) -> torch.Tensor:
    """Reopen the surviving B1 checkpoint and resolve its target Muon buffer."""

    try:
        model_state = torch.load(seed_model_path, map_location="cpu", weights_only=True)
        optimizer_state = torch.load(
            seed_optimizer_path, map_location="cpu", weights_only=True
        )
    except Exception:
        _refuse("MOMENTUM_LINEAGE_LOAD_FAILED")
    if not isinstance(model_state, Mapping) or target_name not in model_state:
        _refuse("SEED_MODEL_STATE_INVALID")
    ids = _muon_name_to_id(model_state)
    muon_id = ids.get(target_name)
    if muon_id is None or not isinstance(optimizer_state, Mapping):
        _refuse("SEED_GATE_MOMENTUM_UNRESOLVED")
    state = optimizer_state.get("muon", {}).get("state")
    if not state:
        state = optimizer_state.get("state", {})
    try:
        resolved = _seed_tensor(
            state[muon_id]["momentum_buffer"], "SEED_GATE_MOMENTUM_INVALID"
        )
    except (KeyError, TypeError):
        _refuse("SEED_GATE_MOMENTUM_UNRESOLVED")
    if float(resolved.to(torch.float32).square().mean().sqrt()) < 1e-10:
        _refuse("SEED_GATE_MOMENTUM_NEAR_ZERO")
    return resolved


def validate_momentum_lineage(
    *,
    seed_manifest_path: Path,
    seed_model_path: Path,
    seed_optimizer_path: Path,
    b1m_receipt_path: Path,
    persisted_pre_momentum_path: Path,
    target_name: str,
    reset_momentum: torch.Tensor,
    transplant_momentum: torch.Tensor,
    expected_run_id: str,
) -> dict[str, object]:
    """Bind the supplied arm buffers to the exact seed optimizer and B1m bytes."""

    if not isinstance(expected_run_id, str) or _JOB_ID.fullmatch(expected_run_id) is None:
        _refuse("MOMENTUM_RUN_ID_INVALID")
    try:
        manifest = json.loads(Path(seed_manifest_path).read_text(encoding="utf-8"))
        receipt = json.loads(Path(b1m_receipt_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _refuse("MOMENTUM_LINEAGE_RECEIPT_MALFORMED")
    model_sha = _sha(seed_model_path)
    optimizer_sha = _sha(seed_optimizer_path)
    if (
        not isinstance(manifest, dict)
        or not isinstance(manifest.get("files"), dict)
        or manifest["files"].get("model.pt") != model_sha
        or manifest["files"].get("optimizer.pt") != optimizer_sha
    ):
        _refuse("SEED_OPTIMIZER_HASH_MISMATCH")
    u_pre = receipt.get("u_pre") if isinstance(receipt, dict) else None
    cache_paths = receipt.get("cache_paths") if isinstance(receipt, dict) else None
    if (
        receipt.get("ticket") != "CBASE-GROW-RUNG2-EVENT-B1M"
        or receipt.get("run_id") != expected_run_id
        or receipt.get("verdict") != "B1M_CAPTURED"
        or not isinstance(u_pre, dict)
        or u_pre.get("gate_key") != target_name
        or u_pre.get("momentum_buffer_source")
        != "B1 snapshot pre-grow momentum_buffer (parent-carried)"
        or not isinstance(cache_paths, dict)
        or not isinstance(cache_paths.get("pre_momentum"), str)
        or not Path(cache_paths["pre_momentum"]).name
    ):
        _refuse("B1M_RECEIPT_INVALID")

    try:
        persisted = _seed_tensor(
            torch.load(persisted_pre_momentum_path, map_location="cpu", weights_only=True),
            "B1M_PERSISTED_MOMENTUM_INVALID",
        )
    except MomentumLineageRefusal:
        raise
    except Exception:
        _refuse("MOMENTUM_LINEAGE_LOAD_FAILED")
    resolved = resolve_seed_momentum(
        seed_model_path=seed_model_path,
        seed_optimizer_path=seed_optimizer_path,
        target_name=target_name,
    )
    muon_id = _muon_name_to_id(
        torch.load(seed_model_path, map_location="cpu", weights_only=True)
    )[target_name]
    if not torch.equal(resolved, persisted):
        _refuse("B1M_PERSISTED_MOMENTUM_MISMATCH")
    resolved_float32 = resolved.to(torch.float32)
    expected_transplant = torch.cat([resolved_float32, resolved_float32], dim=0)
    reset = _tensor(reset_momentum, "RESET_MOMENTUM_INVALID")
    transplant = _tensor(transplant_momentum, "TRANSPLANT_MOMENTUM_INVALID")
    if reset.shape != expected_transplant.shape or bool(torch.count_nonzero(reset)):
        _refuse("RESET_MOMENTUM_NOT_ZERO")
    if not torch.equal(transplant, expected_transplant):
        _refuse("TRANSPLANT_MOMENTUM_PUSHFORWARD_MISMATCH")

    return {
        "schema_version": "q2-momentum-lineage-binding-v1",
        "run_id": expected_run_id,
        "target_name": target_name,
        "seed_model_sha256": model_sha,
        "seed_optimizer_sha256": optimizer_sha,
        "b1m_receipt_sha256": _sha(b1m_receipt_path),
        "persisted_pre_momentum_sha256": _sha(persisted_pre_momentum_path),
        "historical_pre_momentum_name": Path(cache_paths["pre_momentum"]).name,
        "muon_local_id": muon_id,
        "pushforward": "gate-row-duplication",
        "reset_exact_zero": True,
        "transplant_matches_pushforward": True,
        "event_credit": False,
        "scientific_credit": False,
        "no_new_parallel_authority": True,
    }
