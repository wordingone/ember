# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Hash and write sparse shared/expert checkpoint artifacts after a measured step."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import torch

from model import EXPERT_NAMES, UnifiedDecoder


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _record(path: Path, root: Path) -> dict[str, Any]:
    return {"path": path.relative_to(root).as_posix(), "sha256": _sha256(path), "bytes": path.stat().st_size}


def write_checkpoint_artifacts(
    model: UnifiedDecoder,
    optimizer: torch.optim.Optimizer,
    root: Path,
    *,
    launch_seed: int,
) -> dict[str, Any]:
    """Persist post-step shared state plus one independently hashed file per expert."""

    root.mkdir(parents=True, exist_ok=True)
    shared = root / "shared.pt"
    shared_state = {
        name: value.detach().cpu()
        for name, value in model.state_dict().items()
        if ".experts." not in name
    }
    torch.save({"model": shared_state, "optimizer": optimizer.state_dict()}, shared)
    shards = [_record(shared, root)]
    expert_hashes: dict[str, str] = {}
    for name in EXPERT_NAMES:
        path = root / f"expert-{name}.pt"
        state = {
            key: value.detach().cpu()
            for key, value in model.state_dict().items()
            if f".experts.{name}." in key
        }
        torch.save({"expert": name, "model": state}, path)
        record = _record(path, root)
        shards.append(record)
        expert_hashes[name] = record["sha256"]
    manifest = {
        "schema_version": "ember-sparse-checkpoint-v1",
        "launch_seed": launch_seed,
        "active_expert_ids": [model.active_expert],
        "expert_checkpoint_sha256": expert_hashes,
        "shards": shards,
    }
    (root / "checkpoint-manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return manifest
