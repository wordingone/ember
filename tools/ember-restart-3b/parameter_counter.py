# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Content-addressable source for routed Ember parameter measurements."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from typing import Any

from model import UnifiedDecoder


def measure_parameter_counts(model: UnifiedDecoder) -> dict[str, Any]:
    """Measure total allocated capacity and the one active episode path."""

    total = model.count_unique_trainable_parameters(include_frozen=True)
    active = model.count_unique_trainable_parameters()
    return {
        "allocated_parameters": total,
        "unique_parameters": total,
        "trainable_parameters": total,
        "served_parameters": total,
        "active_parameters": active,
        "episode_trainable_parameters": active,
        "active_expert_ids": [model.active_expert],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_parameter_receipt(
    model: UnifiedDecoder,
    config_path: Path,
    checkpoint_manifest_path: Path,
    expert_genesis_sha256: dict[str, str],
) -> dict[str, Any]:
    """Emit the exact measured counter binding used by a checkpoint candidate."""

    counts = measure_parameter_counts(model)
    return {
        "schema_version": "ember-sparse-parameter-receipt-v1",
        "result": "MEASURED",
        "model_config_sha256": _sha256(config_path),
        "counter_sha256": _sha256(Path(__file__)),
        "subject_checkpoint_sha256": _sha256(checkpoint_manifest_path),
        "architecture_revision": "ember-sparse-3b-v1",
        **counts,
        "expert_genesis_sha256": dict(expert_genesis_sha256),
    }