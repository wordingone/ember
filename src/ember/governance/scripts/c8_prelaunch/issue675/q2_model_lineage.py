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
CANONICAL_B2_RECEIPT_SHA256 = "fbf0440b98f439a01c03f399e8c7fb48ba3500b8b48386ca1c55562cf772de66"
CANONICAL_B2_LINEAGE_RUN_ID = "grow-rung2-20260709-remeasure"
CANONICAL_B2_OPERATOR_SHA256 = "5d9c16f49b2c4ad056cc174a692a92f18ab034d881699a8564f3da763f51a40f"
CANONICAL_B2_EPS_SIGMA = 0.05
CANONICAL_B2_EPS_SEED = 0


class ModelLineageRefusal(ValueError):
    """Named refusal before an unrelated model can enter capture custody."""


def _refuse(code: str) -> None:
    raise ModelLineageRefusal(code)


def _sha(path: Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        _refuse("MODEL_LINEAGE_FILE_UNAVAILABLE")


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


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
    runtime_config_path: Path,
    expected_run_id: str,
    expected_source_commit: str,
    n_layers: int,
) -> dict[str, object]:
    """Prove seed -> canonical B2 grow -> persisted state -> live state."""

    if not isinstance(expected_run_id, str) or _JOB_ID.fullmatch(expected_run_id) is None:
        _refuse("MODEL_LINEAGE_RUN_ID_INVALID")
    if not isinstance(expected_source_commit, str) or re.fullmatch(r"[0-9a-f]{40}", expected_source_commit) is None:
        _refuse("MODEL_LINEAGE_SOURCE_COMMIT_INVALID")
    try:
        receipt = json.loads(Path(b2_receipt_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _refuse("B2_RECEIPT_MALFORMED")
    if not isinstance(receipt, dict):
        _refuse("B2_RECEIPT_MALFORMED")
    historical = receipt.get("historical")
    law = receipt.get("law")
    inputs = receipt.get("inputs")
    output = receipt.get("output")
    receipt_without_sha = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if (
        set(receipt) != {"schema", "source_commit", "lineage_run_id", "verdict", "historical", "law", "inputs", "operator_sha256", "output", "receipt_sha256"}
        or receipt.get("schema") != "q2-b2-replay-remint-receipt-v1"
        or receipt.get("source_commit") != expected_source_commit
        or receipt.get("lineage_run_id") != expected_run_id
        or receipt.get("verdict") != "B2_REPLAY_REMINTED"
        or not isinstance(historical, dict)
        or set(historical) != {"receipt_sha256", "operator_sha256", "ticket", "verdict"}
        or historical.get("ticket") != "CBASE-GROW-RUNG2-EVENT-B2"
        or historical.get("verdict") != "B2_REALIZED_PASS"
        or not isinstance(law, dict)
        or set(law) != {"n_layers", "eps_sigma", "eps_seed", "banned_zero_assertion_passed", "distinct_from_eps0_cache", "eta_band_pass", "twin_cosine_pass"}
        or law.get("n_layers") != n_layers
        or law.get("banned_zero_assertion_passed") is not True
        or law.get("distinct_from_eps0_cache") is not True
        or law.get("eta_band_pass") is not True
        or law.get("twin_cosine_pass") is not True
        or not isinstance(inputs, dict)
        or set(inputs) != {"seed_manifest_sha256", "seed_model_sha256", "runtime_config_sha256"}
        or not isinstance(output, dict)
        or set(output) != {"grown_model_sha256"}
        or receipt.get("receipt_sha256") != hashlib.sha256(_canonical(receipt_without_sha)).hexdigest()
    ):
        _refuse("B2_REPLAY_RECEIPT_INVALID")
    historical_operator_sha = historical.get("operator_sha256")
    if (
        expected_run_id != CANONICAL_B2_LINEAGE_RUN_ID
        or historical.get("receipt_sha256") != CANONICAL_B2_RECEIPT_SHA256
        or historical_operator_sha != CANONICAL_B2_OPERATOR_SHA256
    ):
        _refuse("B2_HISTORICAL_BINDING_INVALID")
    if (
        law.get("eps_sigma") != CANONICAL_B2_EPS_SIGMA
        or law.get("eps_seed") != CANONICAL_B2_EPS_SEED
    ):
        _refuse("B2_FROZEN_LAW_MISMATCH")
    replay_operator_sha = _sha(grow_operator_path)
    if receipt.get("operator_sha256") != replay_operator_sha or replay_operator_sha != _sha(Path(__file__).resolve()):
        _refuse("B2_REPLAY_OPERATOR_HASH_MISMATCH")

    try:
        seed_manifest = json.loads(Path(seed_manifest_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _refuse("SEED_MANIFEST_MALFORMED")
    seed_model_sha = _sha(seed_model_path)
    if (
        not isinstance(seed_manifest, dict)
        or not isinstance(seed_manifest.get("files"), dict)
        or seed_manifest["files"].get("model.pt") != seed_model_sha
        or inputs.get("seed_manifest_sha256") != _sha(seed_manifest_path)
        or inputs.get("seed_model_sha256") != seed_model_sha
    ):
        _refuse("SEED_MODEL_HASH_MISMATCH")
    if output.get("grown_model_sha256") != _sha(grown_model_path):
        _refuse("GROWN_MODEL_HASH_MISMATCH")
    if inputs.get("runtime_config_sha256") != _sha(runtime_config_path):
        _refuse("B2_RUNTIME_CONFIG_HASH_MISMATCH")

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
        eps_sigma=law.get("eps_sigma"),
        eps_seed=law.get("eps_seed"),
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
        "historical_grow_operator_sha256": historical_operator_sha,
        "replay_operator_sha256": replay_operator_sha,
        "grow_operator_sha256": replay_operator_sha,
        "n_layers": n_layers,
        "eps_sigma": float(law["eps_sigma"]),
        "eps_seed": law["eps_seed"],
        "state_entry_count": len(grown_state),
        "live_state_matches_grown": True,
        "event_credit": False,
        "scientific_credit": False,
        "no_new_parallel_authority": True,
    }
