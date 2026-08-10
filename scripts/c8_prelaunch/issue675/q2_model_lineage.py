# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Replay the canonical B2 grow and bind it to the live #675 model state.

The implementation mirrors ``cbase_grow_rung2_event.py``'s epsilon widening
worker: seed bfloat16 -> float32, deterministic Net2Net widening, then bfloat16.
It performs no launch, optimizer step, or file mutation.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Mapping

import torch


_SHA256 = re.compile(r"[0-9a-f]{64}")
_JOB_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}")


class ModelLineageRefusal(ValueError):
    """Named refusal before an unrelated model can enter capture custody."""


def _refuse(code: str) -> None:
    raise ModelLineageRefusal(code)


def _sha(path: Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        _refuse("MODEL_LINEAGE_FILE_UNAVAILABLE")


def _state(value: object, code: str) -> dict[str, torch.Tensor]:
    if (
        not isinstance(value, Mapping)
        or not value
        or any(
            not isinstance(name, str)
            or not name
            or not isinstance(tensor, torch.Tensor)
            or tensor.layout != torch.strided
            or tensor.numel() == 0
            or not bool(torch.isfinite(tensor).all())
            for name, tensor in value.items()
        )
    ):
        _refuse(code)
    return {name: tensor.detach().cpu().contiguous() for name, tensor in value.items()}


def _same_state(left: Mapping[str, torch.Tensor], right: Mapping[str, torch.Tensor]) -> bool:
    return set(left) == set(right) and all(
        left[name].dtype == right[name].dtype
        and left[name].shape == right[name].shape
        and torch.equal(left[name], right[name])
        for name in left
    )


def replay_b2_widen(
    seed_state: Mapping[str, torch.Tensor],
    *,
    n_layers: int,
    eps_sigma: float,
    eps_seed: int,
) -> dict[str, torch.Tensor]:
    """Reproduce the canonical B2 worker's persisted bfloat16 state."""

    seed = _state(seed_state, "SEED_MODEL_STATE_INVALID")
    if not isinstance(n_layers, int) or isinstance(n_layers, bool) or n_layers <= 0:
        _refuse("B2_LAYER_COUNT_INVALID")
    if (
        not isinstance(eps_sigma, (int, float))
        or isinstance(eps_sigma, bool)
        or not math.isfinite(float(eps_sigma))
        or eps_sigma <= 0
        or not isinstance(eps_seed, int)
        or isinstance(eps_seed, bool)
        or eps_seed < 0
    ):
        _refuse("B2_EPSILON_INVALID")

    grown = {name: tensor.float() for name, tensor in seed.items()}
    generator = torch.Generator().manual_seed(eps_seed)
    for index in range(n_layers):
        prefix = f"backbone_model.layers.{index}.mlp."
        gate_name = prefix + "gate_proj.weight"
        up_name = prefix + "up_proj.weight"
        down_name = prefix + "down_proj.weight"
        try:
            gate = seed[gate_name].float()
            up = seed[up_name].float()
            down = seed[down_name].float()
        except KeyError:
            _refuse("B2_SEED_FF_KEYS_MISSING")
        if gate.ndim != 2 or up.ndim != 2 or down.ndim != 2:
            _refuse("B2_SEED_FF_SHAPE_INVALID")
        hidden, intermediate = down.shape
        if gate.shape[0] != intermediate or up.shape[0] != intermediate:
            _refuse("B2_SEED_FF_SHAPE_INVALID")
        column_norms = down.norm(dim=0)
        noise = torch.randn(hidden, intermediate, generator=generator, dtype=down.dtype)
        tau = float(eps_sigma) * column_norms / (hidden**0.5)
        eta = noise * tau.unsqueeze(0)
        grown[gate_name] = torch.cat([gate, gate], dim=0)
        grown[up_name] = torch.cat([up, up], dim=0)
        grown[down_name] = torch.cat([down * 0.5 + eta, down * 0.5 - eta], dim=1)
    return {name: tensor.to(torch.bfloat16) for name, tensor in grown.items()}


def validate_model_lineage(
    *,
    live_state: Mapping[str, torch.Tensor],
    seed_manifest_path: Path,
    seed_model_path: Path,
    grown_model_path: Path,
    b2_receipt_path: Path,
    grow_operator_path: Path,
    expected_run_id: str,
    n_layers: int,
) -> dict[str, object]:
    """Prove seed -> canonical B2 grow -> persisted state -> live state."""

    if not isinstance(expected_run_id, str) or _JOB_ID.fullmatch(expected_run_id) is None:
        _refuse("MODEL_LINEAGE_RUN_ID_INVALID")
    try:
        receipt = json.loads(Path(b2_receipt_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _refuse("B2_RECEIPT_MALFORMED")
    if not isinstance(receipt, dict):
        _refuse("B2_RECEIPT_MALFORMED")
    eps = receipt.get("eps")
    cache = receipt.get("cache")
    proof = receipt.get("realized_proof")
    if (
        receipt.get("ticket") != "CBASE-GROW-RUNG2-EVENT-B2"
        or receipt.get("run_id") != expected_run_id
        or receipt.get("verdict") != "B2_REALIZED_PASS"
        or not isinstance(eps, dict)
        or eps.get("banned_zero_assertion_passed") is not True
        or not isinstance(cache, dict)
        or cache.get("distinct_from_eps0_cache") is not True
        or not isinstance(proof, dict)
        or proof.get("eta_band_pass") is not True
        or proof.get("twin_cosine_pass") is not True
    ):
        _refuse("B2_RECEIPT_NOT_GREEN")
    operator_sha = _sha(grow_operator_path)
    if receipt.get("operator_sha256") != operator_sha:
        _refuse("B2_OPERATOR_HASH_MISMATCH")

    try:
        seed_manifest = json.loads(Path(seed_manifest_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _refuse("SEED_MANIFEST_MALFORMED")
    seed_model_sha = _sha(seed_model_path)
    if (
        not isinstance(seed_manifest, dict)
        or not isinstance(seed_manifest.get("files"), dict)
        or seed_manifest["files"].get("model.pt") != seed_model_sha
    ):
        _refuse("SEED_MODEL_HASH_MISMATCH")

    try:
        seed_state = _state(
            torch.load(seed_model_path, map_location="cpu", weights_only=True),
            "SEED_MODEL_STATE_INVALID",
        )
        grown_state = _state(
            torch.load(grown_model_path, map_location="cpu", weights_only=True),
            "GROWN_MODEL_STATE_INVALID",
        )
    except ModelLineageRefusal:
        raise
    except Exception:
        _refuse("MODEL_LINEAGE_LOAD_FAILED")
    expected_grown = replay_b2_widen(
        seed_state,
        n_layers=n_layers,
        eps_sigma=eps.get("eps_sigma"),
        eps_seed=eps.get("eps_seed"),
    )
    if not _same_state(expected_grown, grown_state):
        _refuse("GROWN_MODEL_REPLAY_MISMATCH")
    live = _state(live_state, "LIVE_MODEL_STATE_INVALID")
    if not _same_state(grown_state, live):
        _refuse("LIVE_MODEL_GROWN_STATE_MISMATCH")

    return {
        "schema_version": "q2-model-lineage-binding-v1",
        "run_id": expected_run_id,
        "seed_manifest_sha256": _sha(seed_manifest_path),
        "seed_model_sha256": seed_model_sha,
        "grown_model_sha256": _sha(grown_model_path),
        "b2_receipt_sha256": _sha(b2_receipt_path),
        "grow_operator_sha256": operator_sha,
        "n_layers": n_layers,
        "eps_sigma": float(eps["eps_sigma"]),
        "eps_seed": eps["eps_seed"],
        "state_entry_count": len(grown_state),
        "live_state_matches_grown": True,
        "event_credit": False,
        "scientific_credit": False,
        "no_new_parallel_authority": True,
    }
