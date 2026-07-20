# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Build owned, raw-RGB spatial-relation records for the vision specialist."""

from __future__ import annotations

import base64
import hashlib
import itertools
import json
from dataclasses import dataclass
from typing import Any, Iterable

from specialist_semantics import IMAGE_BYTES, PALETTE, spatial_relation_caption, structural_scene_sha256


_RELATIONS = ("left", "right", "above", "below")
_SPLITS = ("train", "validation", "test")
_PATCH_PERMUTATIONS = tuple(itertools.permutations(range(4)))
_DEFAULT_RECORD_COUNT = 65_536
_SPLIT_GROUP_WEIGHTS = {"train": 2, "validation": 1, "test": 1}
_CAPTIONS = {"red is left of green", "red is right of green", "red is above green", "red is below green"}


def _patch(rectangles: list[tuple[str, int, int]]) -> bytes:
    pixels = bytearray(IMAGE_BYTES)
    for color, x, y in rectangles:
        rgb = PALETTE[color]
        for row in range(y, y + 4):
            for column in range(x, x + 4):
                offset = (row * 48 + column) * 3
                pixels[offset : offset + 3] = bytes(rgb)
    return bytes(pixels)


def patch_permutation_class(index: int) -> int:
    """Return the declared raw patch-order class for one deterministic scene index."""

    if not isinstance(index, int) or index < 0:
        raise ValueError("scene index must be a nonnegative integer")
    variation = index // len(_RELATIONS)
    return (variation * 7) % len(_PATCH_PERMUTATIONS)


def coordinate_blind_content_sha256(patches: Iterable[bytes]) -> str:
    """Hash the exact unordered raw patch bytes while intentionally excluding coordinates."""

    values = []
    for patch in patches:
        if not isinstance(patch, bytes) or len(patch) != IMAGE_BYTES:
            raise ValueError("coordinate-blind content requires exact 48x48x3 raw patch bytes")
        values.append(patch)
    if len(values) != 4:
        raise ValueError("coordinate-blind content requires exactly four image patches")
    payload = b"ember-owned-vision-content-v1\\0" + len(values).to_bytes(4, "big") + b"".join(sorted(values))
    return hashlib.sha256(payload).hexdigest()


def declared_split_plan(*, record_count: int = _DEFAULT_RECORD_COUNT) -> dict[str, object]:
    """Return the preregistered whole-group split plan without allocating any raw records."""

    if not isinstance(record_count, int) or record_count < 512 or record_count % (len(_RELATIONS) * sum(_SPLIT_GROUP_WEIGHTS.values())):
        raise ValueError("owned vision split plan requires a relation-balanced multiple of sixteen with at least 512 records")
    group_count = record_count // len(_RELATIONS)
    group_counts = {split: group_count * weight // sum(_SPLIT_GROUP_WEIGHTS.values()) for split, weight in _SPLIT_GROUP_WEIGHTS.items()}
    return {
        "record_count": record_count,
        "group_count": group_count,
        "group_counts": group_counts,
        "record_counts": {split: groups * len(_RELATIONS) for split, groups in group_counts.items()},
        "ratio": {split: weight / sum(_SPLIT_GROUP_WEIGHTS.values()) for split, weight in _SPLIT_GROUP_WEIGHTS.items()},
    }


def _scene(index: int) -> tuple[list[bytes], list[list[int]]]:
    """Build one raw-unique scene; patch order never stands in for its 2D coordinates."""

    relation = _RELATIONS[index % len(_RELATIONS)]
    variation = index // len(_RELATIONS)
    local_x = variation % 32
    local_y = (variation // 32) % 32
    grid = (variation // (32 * 32)) % 16
    grid_x, grid_y = 2 * (grid % 4), 2 * (grid // 4)
    if relation == "left":
        local_coordinates = ((0, 0), (1, 0), (0, 1), (1, 1))
    elif relation == "right":
        local_coordinates = ((1, 0), (0, 0), (0, 1), (1, 1))
    elif relation == "above":
        local_coordinates = ((0, 0), (0, 1), (1, 0), (1, 1))
    else:
        local_coordinates = ((0, 1), (0, 0), (1, 0), (1, 1))
    coordinates = [[grid_x + x, grid_y + y] for x, y in local_coordinates]

    # The unordered raw patch multiset deliberately carries no relation class.
    # Relation is available only through the explicit coordinate pairing.
    red_patch, green_patch = 0, 1
    patches: list[list[tuple[str, int, int]]] = [[], [], [], []]
    patches[red_patch].append(("red", local_x, local_y))
    patches[green_patch].append(("green", local_x, local_y))
    raw_patches = [_patch(patch) for patch in patches]

    # Two fixed-count blue markers make each variation's raw content distinct
    # across the target scale while remaining non-query pixels.  Their positions
    # occupy disjoint ranges in patch 2, so the unordered patch content encodes
    # the variation without leaking a relation label or changing the histogram.
    marker_patch = 2
    first_marker = variation % 1_024
    second_marker = 1_024 + (variation // 1_024) % 1_280
    payload = bytearray(raw_patches[marker_patch])
    for marker in (first_marker, second_marker):
        pixel_y, pixel_x = divmod(marker, 48)
        offset = (pixel_y * 48 + pixel_x) * 3
        payload[offset : offset + 3] = bytes(PALETTE["blue"])
    raw_patches[marker_patch] = bytes(payload)

    permutation = _PATCH_PERMUTATIONS[patch_permutation_class(index)]
    return ([raw_patches[position] for position in permutation], [coordinates[position] for position in permutation])


@dataclass(frozen=True)
class SceneDescriptor:
    index: int
    patches: list[bytes]
    coordinates: list[list[int]]
    caption: str


def group_and_split_scenes(scenes: Iterable[SceneDescriptor]) -> dict[int, str]:
    """Deduplicate exact structures, then split complete coordinate-blind four-label groups."""

    scenes = list(scenes)
    structures: dict[str, SceneDescriptor] = {}
    by_content: dict[str, list[SceneDescriptor]] = {}
    for scene in scenes:
        raw_key = structural_scene_sha256(scene.patches, scene.coordinates)
        prior = structures.get(raw_key)
        if prior is not None:
            if prior.caption != scene.caption:
                raise ValueError("conflicting labels for identical raw structure")
            raise ValueError("duplicate raw structure before split assignment")
        if spatial_relation_caption(scene.patches, scene.coordinates) != scene.caption:
            raise ValueError("scene caption is not derived from its exact raw structure")
        structures[raw_key] = scene
        by_content.setdefault(coordinate_blind_content_sha256(scene.patches), []).append(scene)

    plan = declared_split_plan(record_count=len(scenes))
    by_permutation: dict[int, list[tuple[str, list[SceneDescriptor]]]] = {}
    for content_key, members in by_content.items():
        if len(members) != len(_RELATIONS) or {member.caption for member in members} != _CAPTIONS:
            raise ValueError("coordinate-blind counterfactual group must contain each owned relation exactly once")
        classes = {patch_permutation_class(member.index) for member in members}
        if len(classes) != 1:
            raise ValueError("counterfactual group has inconsistent patch-permutation class")
        by_permutation.setdefault(classes.pop(), []).append((content_key, members))

    target_groups = dict(plan["group_counts"])
    assigned_groups = {split: 0 for split in _SPLITS}
    split_by_index: dict[int, str] = {}
    remaining: list[tuple[str, list[SceneDescriptor]]] = []
    for permutation_class in sorted(by_permutation):
        members = sorted(by_permutation[permutation_class], key=lambda item: item[0])
        if len(members) < len(_SPLITS):
            raise ValueError("preregistered split lacks complete permutation-class support")
        for split, (_content_key, group_members) in zip(_SPLITS, members[:len(_SPLITS)]):
            for member in group_members:
                split_by_index[member.index] = split
            assigned_groups[split] += 1
        remaining.extend(members[len(_SPLITS):])
    for _content_key, group_members in sorted(remaining, key=lambda item: item[0]):
        candidates = [split for split in _SPLITS if assigned_groups[split] < target_groups[split]]
        if not candidates:
            raise ValueError("counterfactual group assignment exceeded declared split ratio")
        split = max(candidates, key=lambda name: (target_groups[name] - assigned_groups[name], -_SPLITS.index(name)))
        for member in group_members:
            split_by_index[member.index] = split
        assigned_groups[split] += 1
    if assigned_groups != target_groups or len(split_by_index) != len(scenes):
        raise ValueError("counterfactual group assignment does not match declared split ratio")
    return split_by_index


def _serialized_order_content_sha256(record: dict[str, object]) -> str:
    """Hash semantic/raw record content without the source-index display identifier."""

    content = {key: value for key, value in record.items() if key != "sample_id"}
    payload = json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(b"ember-owned-vision-order-v1\0" + payload).hexdigest()


def _shuffle_serialized_records_within_splits(records: list[dict[str, object]]) -> list[dict[str, object]]:
    """Return the v1 content-bound final serialization order for complete split members."""

    by_split: dict[str, list[dict[str, object]]] = {split: [] for split in _SPLITS}
    for record in records:
        split = record.get("scene_split")
        if split not in by_split:
            raise ValueError("serialized vision order requires one declared split per record")
        by_split[str(split)].append(record)
    ordered: list[dict[str, object]] = []
    for split in _SPLITS:
        members = by_split[split]
        identities = [_serialized_order_content_sha256(record) for record in members]
        if len(set(identities)) != len(identities):
            raise ValueError("serialized vision order requires unique record content identities")
        seed = hashlib.sha256(
            b"ember-owned-vision-order-v1\0" + split.encode("utf-8") +
            b"".join(bytes.fromhex(identity) for identity in sorted(identities))
        ).digest()
        ranked = sorted(
            zip(identities, members),
            key=lambda item: (hashlib.sha256(seed + bytes.fromhex(item[0])).digest(), item[0]),
        )
        ordered.extend(record for _identity, record in ranked)
    return ordered

def build_records(tokenizer: Any, *, count: int, image_marker: int) -> list[dict[str, object]]:
    """Build balanced raw-spatial scenes whose target is recomputed from patch bytes and coordinates."""

    declared_split_plan(record_count=count)
    if not isinstance(image_marker, int) or image_marker < 0:
        raise ValueError("image marker must be a nonnegative token ID")
    scenes = [
        SceneDescriptor(index=index, patches=patches, coordinates=coordinates, caption=spatial_relation_caption(patches, coordinates))
        for index in range(count)
        for patches, coordinates in (_scene(index),)
    ]
    split_by_index = group_and_split_scenes(scenes)
    records: list[dict[str, object]] = []
    for scene in scenes:
        index, patches, coordinates, caption = scene.index, scene.patches, scene.coordinates, scene.caption
        encoded = list(tokenizer.encode(caption).ids)
        if len(encoded) < 2:
            raise ValueError("frozen tokenizer cannot encode an owned spatial relation caption")
        scene_sha256 = structural_scene_sha256(patches, coordinates)
        records.append({
            "schema_version": "ember-owned-semantic-record-v1",
            "sample_id": f"owned-vision-spatial-{index:08d}",
            "scene_split": split_by_index[index],
            "active_expert": "vision",
            "token_ids": [*[image_marker] * 4, *encoded[:-1]],
            "target_ids": [*[image_marker] * 3, *encoded],
            "target_text": caption,
            "image_patches_u8_base64": [base64.b64encode(patch).decode("ascii") for patch in patches],
            "image_coordinates": coordinates,
            "multimodal_spans": [{"start": 0, "length": 4, "modality": "image", "attention_mode": "isolated"}],
            "capability_evidence": {"image": {
                "target_sha256": hashlib.sha256(caption.encode("utf-8")).hexdigest(),
                "scene_sha256": scene_sha256,
                "derivation": "raw_image_spatial_relation_execution",
            }},
        })
    return _shuffle_serialized_records_within_splits(records)

def record_at(tokenizer: Any, *, count: int, image_marker: int, index: int) -> dict[str, object]:
    """Regenerate one new-lineage stream scene in O(1), preserving group-atomic split membership."""
    declared_split_plan(record_count=count)
    if not isinstance(image_marker, int) or image_marker < 0 or not isinstance(index, int) or not 0 <= index < count:
        raise ValueError("owned vision stream index is outside the declared range")
    source_index = (12_289 * index + 4_093) % count
    variation = source_index // len(_RELATIONS)
    group_count = count // len(_RELATIONS)
    rank = (8_191 * variation + 3_137) % group_count
    split = "train" if rank < group_count // 2 else "validation" if rank < group_count * 3 // 4 else "test"
    patches, coordinates = _scene(source_index)
    caption = spatial_relation_caption(patches, coordinates)
    encoded = list(tokenizer.encode(caption).ids)
    if len(encoded) < 2:
        raise ValueError("frozen tokenizer cannot encode an owned spatial relation caption")
    return {"schema_version": "ember-owned-semantic-record-v1", "sample_id": f"owned-vision-spatial-{source_index:08d}", "scene_split": split, "active_expert": "vision", "token_ids": [*[image_marker] * 4, *encoded[:-1]], "target_ids": [*[image_marker] * 3, *encoded], "target_text": caption, "image_patches_u8_base64": [base64.b64encode(patch).decode("ascii") for patch in patches], "image_coordinates": coordinates, "multimodal_spans": [{"start": 0, "length": 4, "modality": "image", "attention_mode": "isolated"}], "capability_evidence": {"image": {"target_sha256": hashlib.sha256(caption.encode("utf-8")).hexdigest(), "scene_sha256": structural_scene_sha256(patches, coordinates), "derivation": "raw_image_spatial_relation_execution"}}}
