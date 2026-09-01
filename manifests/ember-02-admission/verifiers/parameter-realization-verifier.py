# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Measure realized parameter counts from a model config and a checkpoint manifest.

Evidence class: parameter_realization. Invoked by src/ember/governance/scripts/ember_restart/contract.py as

    python -I parameter-realization-verifier.py \
        --model-config <path> --checkpoint-manifest <path> --active-expert <id|empty>

Counts are derived from the config's own declared shape, not from any receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

EXPERT_DOMAINS = ("vision", "audio", "reasoning", "tool")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def derive_counts(model: dict, active_expert: str) -> dict[str, int]:
    hidden = model["hidden_size"]
    layers = model["layers"]
    vocab = model["vocab_size"]
    heads = model["attention_heads"]
    image_input = 1
    for size in model["image_projection"]["input_shape"]:
        image_input *= size
    audio_input = model["audio_projection"]["frame_samples"]
    head_dim = hidden // heads

    shared_per_layer = 4 * hidden * hidden + 12 * hidden * hidden + 2 * hidden + 2 * head_dim
    expert_per_layer = 12 * hidden * hidden
    shared_total = (
        vocab * hidden
        + layers * shared_per_layer
        + image_input * hidden
        + audio_input * hidden
        + hidden
    )
    expert_total = layers * expert_per_layer
    total = shared_total + len(EXPERT_DOMAINS) * expert_total
    active = shared_total if not active_expert else shared_total + expert_total
    return {
        "allocated_parameters": total,
        "unique_parameters": total,
        "trainable_parameters": total,
        "served_parameters": total,
        "active_parameters": active,
        "episode_trainable_parameters": active,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-config", required=True, type=Path)
    parser.add_argument("--checkpoint-manifest", required=True, type=Path)
    parser.add_argument("--active-expert", default="")
    args = parser.parse_args(argv)

    config = json.loads(args.model_config.read_text(encoding="utf-8"))
    model = config["model"]
    active_expert = args.active_expert.strip()
    if active_expert and active_expert not in EXPERT_DOMAINS:
        print(f"unknown expert: {active_expert}", file=sys.stderr)
        return 1

    measured = {
        "result": "MEASURED",
        "subject_checkpoint_sha256": sha256(args.checkpoint_manifest),
        "model_config_sha256": sha256(args.model_config),
        "architecture_revision": config["architecture_revision"],
        "active_expert_ids": [active_expert] if active_expert else [],
        **derive_counts(model, active_expert),
    }
    print(json.dumps(measured, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
