# goal_id: EMBER-02
# workstream_id: EMBER-02A
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
_ORDER_LEAK_SCHEMA = "ember-owned-vision-order-v1"
_ORDER_LEAK_ALPHA = 0.01
_ORDER_LEAK_HYPOTHESES = len(_LABELS) ** len(_LABELS)


def _best_order_oracle_accuracy(labels: Sequence[str], features: Sequence[object]) -> float:
    if len(labels) != len(features) or not labels:
        raise ValueError("order oracle requires aligned nonempty labels and features")
    groups: dict[object, Counter[str]] = defaultdict(Counter)
    for label, feature in zip(labels, features):
        groups[feature][label] += 1
    return sum(max(values.values()) for values in groups.values()) / len(labels)


def _order_leak_acceptance_bound(total: int) -> float:
    """Bonferroni 99% upper control limit for 4^4 fitted label maps at chance p=0.25."""
    if total < 2:
        raise ValueError("order-leak acceptance bound requires at least two serialized records")
    p0 = 0.25
    z = NormalDist().inv_cdf(1.0 - _ORDER_LEAK_ALPHA / _ORDER_LEAK_HYPOTHESES)
    return min(1.0, p0 + z * math.sqrt(p0 * (1.0 - p0) / total))


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
    by_split_ordered_patch_mean: dict[str, dict[tuple[tuple[int, int, int], ...], Counter[str]]] = {split: defaultdict(Counter) for split in _SPLITS}
    content_splits: dict[str, set[str]] = defaultdict(set)
    serialized_labels: dict[str, list[str]] = {split: [] for split in _SPLITS}
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
        serialized_labels[split].append(str(label))
        content_key = coordinate_blind_content_sha256(patches)
        ordered_patch_mean_key = tuple(
            tuple(sum(patch[channel::3]) for channel in range(3))
            for patch in patches
        )
        by_split_content[split][content_key][str(label)] += 1
        by_split_ordered_patch_mean[split][ordered_patch_mean_key][str(label)] += 1
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
    per_split_ordered_patch_mean_accuracy: dict[str, float] = {}
    per_split_interval: dict[str, list[float]] = {}
    per_split_power: dict[str, float] = {}
    per_split_position_mod_4_accuracy: dict[str, float] = {}
    per_split_previous_label_accuracy: dict[str, float] = {}
    per_split_order_leak_bound: dict[str, float] = {}
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
        ordered_patch_mean_groups = by_split_ordered_patch_mean[split]
        if not ordered_patch_mean_groups or any(
            set(labels) != set(_LABELS) or len(set(labels.values())) != 1
            for labels in ordered_patch_mean_groups.values()
        ):
            raise ValueError("ordered per-patch RGB means carry a relation shortcut")
        per_split_ordered_patch_mean_accuracy[split] = (
            sum(max(labels.values()) for labels in ordered_patch_mean_groups.values()) / total
        )
        per_split_interval[split] = _wilson_interval(successes, total)
        per_split_power[split] = _power_for_10pp_effect(total)
        if per_split_accuracy[split] != 0.25:
            raise ValueError("content-only oracle exceeds preregistered chance within a split")
        if per_split_ordered_patch_mean_accuracy[split] != 0.25:
            raise ValueError("ordered per-patch RGB-mean oracle exceeds preregistered chance within a split")
        labels = serialized_labels[split]
        position_accuracy = _best_order_oracle_accuracy(labels, [index % len(_LABELS) for index in range(len(labels))])
        previous_accuracy = _best_order_oracle_accuracy(labels[1:], labels[:-1])
        bound = _order_leak_acceptance_bound(len(labels) - 1)
        per_split_position_mod_4_accuracy[split] = position_accuracy
        per_split_previous_label_accuracy[split] = previous_accuracy
        per_split_order_leak_bound[split] = bound
        if position_accuracy > bound:
            raise ValueError("position-mod-4 serialized-order oracle exceeds preregistered chance bound")
        if previous_accuracy > bound:
            raise ValueError("previous-label serialized-order oracle exceeds preregistered chance bound")
    return {
        "schema_version": "ember-owned-vision-shortcut-control-v3",
        "serialized_order_schema_version": _ORDER_LEAK_SCHEMA,
        "result": "MEASURED_NONMATERIALIZING_NONDISPATCHABLE",
        "record_count": len(records),
        "declared_support_records": declared_split_plan()["record_count"],
        "content_only_chance": 0.25,
        "declared_split_ratio": plan["ratio"],
        "per_split_record_counts": per_split_counts,
        "per_split_content_only_oracle_accuracy": per_split_accuracy,
        "per_split_ordered_patch_mean_oracle_accuracy": per_split_ordered_patch_mean_accuracy,
        "per_split_confidence_interval_95": per_split_interval,
        "per_split_power_for_10pp_effect": per_split_power,
        "wilson_and_power_report_only": True,
        "order_leak_alpha": _ORDER_LEAK_ALPHA,
        "order_leak_fitted_hypotheses": _ORDER_LEAK_HYPOTHESES,
        "per_split_position_mod_4_oracle_accuracy": per_split_position_mod_4_accuracy,
        "per_split_previous_label_oracle_accuracy": per_split_previous_label_accuracy,
        "per_split_order_leak_acceptance_bound": per_split_order_leak_bound,
        "permutation_support": {split: sorted(values) for split, values in support.items()},
        "raw_patch_mask_rejected": raw_mask_rejected,
        "paired_coordinate_shuffle_preserved": paired_preserved,
        "unpaired_coordinate_shuffle_changed": unpaired_changed,
        "model_allocation": False,
        "corpus_materialized": False,
        "gpu_dispatched": False,
    }