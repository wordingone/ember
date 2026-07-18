# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Deterministic, no-allocation shortcut controls for owned spatial vision records."""

from __future__ import annotations

import base64
import math
from collections import Counter, defaultdict
from statistics import NormalDist
from typing import Mapping, Sequence

from build_owned_vision_scenes import coordinate_blind_content_sha256, declared_split_plan, patch_permutation_class
from specialist_semantics import spatial_relation_caption

_LABELS = ("red is left of green", "red is right of green", "red is above green", "red is below green")
_SPLITS = ("train", "validation", "test")


def _patches(record: Mapping[str, object]) -> list[bytes]:
    values = record.get("image_patches_u8_base64")
    if not isinstance(values, list):
        raise ValueError("vision control requires raw image patches")
    return [base64.b64decode(value, validate=True) for value in values]


def _coordinates(record: Mapping[str, object]) -> list[object]:
    coordinates = record.get("image_coordinates")
    if not isinstance(coordinates, list):
        raise ValueError("vision control requires explicit image coordinates")
    return coordinates


def _sample_index(record: Mapping[str, object]) -> int:
    sample_id = record.get("sample_id")
    if not isinstance(sample_id, str) or not sample_id.startswith("owned-vision-spatial-"):
        raise ValueError("vision control requires owned spatial sample IDs")
    return int(sample_id.rsplit("-", 1)[1])


def _wilson_interval(successes: int, total: int) -> list[float]:
    if total <= 0:
        raise ValueError("confidence interval requires positive sample count")
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    margin = z * math.sqrt(proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total)) / denominator
    return [center - margin, center + margin]


def _power_for_10pp_effect(total: int) -> float:
    """Preregistered normal-approximation power for p0=0.25 versus p1=0.35, alpha=0.05."""
    p0, p1, z_alpha = 0.25, 0.35, 1.959963984540054
    threshold = p0 + z_alpha * math.sqrt(p0 * (1.0 - p0) / total)
    z_under_alternative = (threshold - p1) / math.sqrt(p1 * (1.0 - p1) / total)
    return NormalDist().cdf(-z_under_alternative)


def evaluate_shortcut_controls(records: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Measure coordinate-blind shortcuts per declared split without allocating a model or corpus artifact."""
    if not records:
        raise ValueError("shortcut control requires at least one record")
    plan = declared_split_plan(record_count=len(records))
    support: dict[str, set[int]] = {split: set() for split in _SPLITS}
    by_split_content: dict[str, dict[str, Counter[str]]] = {split: defaultdict(Counter) for split in _SPLITS}
    content_splits: dict[str, set[str]] = defaultdict(set)
    raw_mask_rejected = 0
    paired_preserved = 0
    unpaired_changed = 0
    for record in records:
        split = record.get("scene_split")
        label = record.get("target_text")
        if split not in support or label not in _LABELS:
            raise ValueError("shortcut control requires declared split and owned relation label")
        patches = _patches(record)
        coordinates = _coordinates(record)
        support[split].add(patch_permutation_class(_sample_index(record)))
        content_key = coordinate_blind_content_sha256(patches)
        by_split_content[split][content_key][str(label)] += 1
        content_splits[content_key].add(split)
        try:
            spatial_relation_caption([bytes(len(patch)) for patch in patches], coordinates)
        except ValueError:
            raw_mask_rejected += 1
        else:
            raise ValueError("all-zero raw patch mask unexpectedly retained a spatial label")
        reverse = tuple(reversed(range(len(patches))))
        paired_caption = spatial_relation_caption([patches[index] for index in reverse], [coordinates[index] for index in reverse])
        paired_preserved += int(paired_caption == label)
        unpaired_caption = spatial_relation_caption([patches[index] for index in reverse], coordinates)
        unpaired_changed += int(unpaired_caption != label)
    if any(len(splits) != 1 for splits in content_splits.values()):
        raise ValueError("coordinate-blind counterfactual group is split across declared partitions")
    expected_support = set(range(24))
    if any(values != expected_support for values in support.values()):
        raise ValueError("preregistered split lacks full 24-class permutation support")
    per_split_accuracy: dict[str, float] = {}
    per_split_interval: dict[str, list[float]] = {}
    per_split_power: dict[str, float] = {}
    per_split_counts = {split: sum(sum(labels.values()) for labels in by_split_content[split].values()) for split in _SPLITS}
    if per_split_counts != plan["record_counts"]:
        raise ValueError("record counts do not match the preregistered split ratio")
    for split in _SPLITS:
        groups = by_split_content[split]
        if not groups or any(labels != Counter(_LABELS) for labels in groups.values()):
            raise ValueError("coordinate-blind counterfactual group must have one record for each label")
        successes = sum(max(labels.values()) for labels in groups.values())
        total = per_split_counts[split]
        per_split_accuracy[split] = successes / total
        per_split_interval[split] = _wilson_interval(successes, total)
        per_split_power[split] = _power_for_10pp_effect(total)
        if per_split_accuracy[split] != 0.25:
            raise ValueError("content-only oracle exceeds preregistered chance within a split")
    return {
        "schema_version": "ember-owned-vision-shortcut-control-v2",
        "result": "MEASURED_NONMATERIALIZING_NONDISPATCHABLE",
        "record_count": len(records),
        "declared_support_records": declared_split_plan()["record_count"],
        "content_only_chance": 0.25,
        "declared_split_ratio": plan["ratio"],
        "per_split_record_counts": per_split_counts,
        "per_split_content_only_oracle_accuracy": per_split_accuracy,
        "per_split_confidence_interval_95": per_split_interval,
        "per_split_power_for_10pp_effect": per_split_power,
        "permutation_support": {split: sorted(values) for split, values in support.items()},
        "raw_patch_mask_rejected": raw_mask_rejected,
        "paired_coordinate_shuffle_preserved": paired_preserved,
        "unpaired_coordinate_shuffle_changed": unpaired_changed,
        "model_allocation": False,
        "corpus_materialized": False,
        "gpu_dispatched": False,
    }