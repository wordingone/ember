# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Canonical semantic model-contract binding for owned specialist data."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

SCHEMA_VERSION = "ember-semantic-model-contract-v1"


def semantic_model_contract_payload(config: Mapping[str, Any]) -> dict[str, Any]:
    """Return only load-bearing architecture/input/training semantics.

    Operational scheduling, receipt, and formatting fields deliberately do not
    enter this identity. The returned object is JSON-compatible and detached
    from the caller's mutable mapping.
    """
    if not isinstance(config, Mapping):
        raise ValueError("model config must be an object")
    model = config.get("model")
    training = config.get("training")
    if not isinstance(model, Mapping) or not isinstance(training, Mapping):
        raise ValueError("model config lacks model/training maps")
    if config.get("contract_version") != 3 or config.get("architecture_revision") != "ember-sparse-3b-v2":
        raise ValueError("model config revision is not the authorized sparse 3B contract")
    required_model = (
        "architecture", "hidden_size", "layers", "attention_heads", "vocab_size",
        "tied_embeddings", "normalization", "position_encoding", "expert_routing",
        "image_projection", "audio_projection", "parameter_formula",
        "total_unique_trainable_parameters",
    )
    if any(key not in model for key in required_model):
        raise ValueError("model config lacks load-bearing architecture fields")
    required_training = (
        "gradient_checkpointing", "optimizer", "expert_activation", "memory",
        "expected_input_artifact_id",
    )
    if any(key not in training for key in required_training):
        raise ValueError("model config lacks load-bearing training fields")
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_version": config.get("contract_version"),
        "architecture_revision": config.get("architecture_revision"),
        "model": json.loads(json.dumps(dict(model), sort_keys=True, ensure_ascii=False)),
        "training": {
            key: json.loads(json.dumps(training[key], sort_keys=True, ensure_ascii=False))
            for key in required_training
        },
    }


def semantic_model_contract_sha256(config: Mapping[str, Any]) -> str:
    payload = semantic_model_contract_payload(config)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
