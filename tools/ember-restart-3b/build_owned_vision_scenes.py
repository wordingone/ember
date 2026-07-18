# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Build owned, raw-RGB spatial-relation records for the vision specialist."""

from __future__ import annotations

import base64
import hashlib
import itertools
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

    # Every raw scene remains distinct after a geometry cycle repeats.  The
    # distractor is deliberately non-query colour and never overwrites a red or
    # green pixel, so the locally derived supervision remains unchanged.
    content_variant = variation // (32 * 32 * 16)
    occupied = {
        (patch, local_x + dx, local_y + dy)
        for patch in (red_patch, green_patch)
        for dx in range(4)
        for dy in range(4)
    }
    candidate = (content_variant * 17) % (4 * 48 * 48)
    for _ in range(4 * 48 * 48):
        patch_index, remainder = divmod(candidate, 48 * 48)
        pixel_y, pixel_x = divmod(remainder, 48)
        if (patch_index, pixel_x, pixel_y) not in occupied:
            payload = bytearray(raw_patches[patch_index])
            offset = (pixel_y * 48 + pixel_x) * 3
            payload[offset : offset + 3] = bytes(PALETTE["blue"])
            raw_patches[patch_index] = bytes(payload)
            break
        candidate = (candidate + 1) % (4 * 48 * 48)
    else:
        raise RuntimeError("no safe non-query distractor pixel exists")

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
    return records
