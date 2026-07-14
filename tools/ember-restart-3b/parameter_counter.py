# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Content-addressable source for routed Ember parameter measurements."""

from __future__ import annotations

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
