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
    """Reject raw duplicates/conflicting labels, then deterministically split unique structural groups."""

    groups: dict[str, SceneDescriptor] = {}
    for scene in scenes:
        raw_key = structural_scene_sha256(scene.patches, scene.coordinates)
        prior = groups.get(raw_key)
        if prior is not None:
            if prior.caption != scene.caption:
                raise ValueError("conflicting labels for identical raw structure")
            raise ValueError("duplicate raw structure before split assignment")
        if spatial_relation_caption(scene.patches, scene.coordinates) != scene.caption:
            raise ValueError("scene caption is not derived from its exact raw structure")
        groups[raw_key] = scene

    split_by_index: dict[int, str] = {}
    by_support_stratum: dict[tuple[str, int], list[tuple[str, SceneDescriptor]]] = {}
    for raw_key, scene in groups.items():
        permutation_class = patch_permutation_class(scene.index)
        by_support_stratum.setdefault((scene.caption, permutation_class), []).append((raw_key, scene))
    for _stratum, members in by_support_stratum.items():
        for ordinal, (_raw_key, scene) in enumerate(sorted(members, key=lambda member: member[0])):
            split_by_index[scene.index] = _SPLITS[ordinal % len(_SPLITS)]
    return split_by_index

def build_records(tokenizer: Any, *, count: int, image_marker: int) -> list[dict[str, object]]:
    """Build balanced raw-spatial scenes whose target is recomputed from patch bytes and coordinates."""

    if not isinstance(count, int) or count < 512 or count % len(_RELATIONS):
        raise ValueError("owned vision semantic records require a relation-balanced multiple of at least 512 scenes")
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
