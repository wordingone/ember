# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Dense-A1-only full-state checkpoint writer and inventory verifier."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import torch

from a1_dense import DenseA1Decoder
from a1_optimizer import FullStateAdamWCPUOffload
from durable_io import atomic_create_durable


SCHEMA = "ember-a1-dense-checkpoint-v1"
OPTIMIZER_INVENTORY_FIELDS = {
    "schema_version", "state_format", "registered_parameters", "registered_numel",
    "initialized_parameters", "cpu_fp32_master_numel",
    "cpu_fp32_first_moment_numel", "cpu_fp32_second_moment_numel", "complete",
}


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dense_inventory(model: DenseA1Decoder) -> dict[str, Any]:
    named = list(model.named_parameters())
    if len({id(parameter) for _, parameter in named}) != len(named):
        raise ValueError("dense A1 named parameter inventory contains aliases")
    total = sum(parameter.numel() for _, parameter in named)
    if total != model.config.structural_parameter_count():
        raise ValueError("dense A1 live parameter inventory differs from structure")
    return {
        "parameter_tensors": len(named),
        "unique_trainable_parameters": total,
        "architecture_revision": "ember-dense-a1-3b-v1",
        "contains_router_or_experts": False,
    }


def write_dense_checkpoint(
    root: Path,
    *,
    model: DenseA1Decoder,
    optimizer: FullStateAdamWCPUOffload,
    global_step: int,
    tokens_seen: int,
    identity: dict[str, Any],
) -> tuple[Path, str]:
    if type(global_step) is not int or global_step <= 0:
        raise ValueError("dense A1 checkpoint global_step must be positive")
    if type(tokens_seen) is not int or tokens_seen <= 0:
        raise ValueError("dense A1 checkpoint tokens_seen must be positive")
    inventory = dense_inventory(model)
    optimizer_inventory = optimizer.state_inventory()
    expected = inventory["unique_trainable_parameters"]
    if set(optimizer_inventory) != OPTIMIZER_INVENTORY_FIELDS or optimizer_inventory != {
        **optimizer_inventory,
        "registered_numel": expected,
        "cpu_fp32_master_numel": expected,
        "cpu_fp32_first_moment_numel": expected,
        "cpu_fp32_second_moment_numel": expected,
        "complete": True,
    }:
        raise ValueError("dense A1 optimizer inventory is not complete full state")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    payload_path = root / "a1-full-state.pt"
    with tempfile.NamedTemporaryFile(dir=root, prefix=".a1-full-state.", suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        torch.save(
            {
                "model": model.state_dict(),
                "optimizer": optimizer.state_dict(),
                "global_step": global_step,
                "tokens_seen": tokens_seen,
            },
            temporary,
        )
        os.replace(temporary, payload_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    manifest = {
        "schema_version": SCHEMA,
        "global_step": global_step,
        "tokens_seen": tokens_seen,
        "identity": identity,
        "dense_inventory": inventory,
        "optimizer_inventory": optimizer_inventory,
        "payload": {"path": payload_path.name, "sha256": _sha(payload_path)},
    }
    manifest_path = root / "checkpoint-manifest.json"
    atomic_create_durable(manifest_path, _canonical(manifest) + b"\n")
    return manifest_path, _sha(manifest_path)
