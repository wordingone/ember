# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Build owned, raw-RGB spatial-relation records for the vision specialist."""

from __future__ import annotations

import base64
import hashlib
import itertools
from typing import Any

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


def _scene(index: int) -> tuple[list[bytes], list[list[int]]]:
    """Build one unique scene; patch order never stands in for its 2D coordinates."""

    relation = _RELATIONS[index % len(_RELATIONS)]
    variation = index // len(_RELATIONS)
    local_x = variation % 32
    local_y = (variation // 32) % 32
    grid = (variation // (32 * 32)) % 16
    grid_x, grid_y = 2 * (grid % 4), 2 * (grid // 4)
    coordinates = [[grid_x, grid_y], [grid_x + 1, grid_y], [grid_x, grid_y + 1], [grid_x + 1, grid_y + 1]]
    patches: list[list[tuple[str, int, int]]] = [[], [], [], []]
    if relation in {"left", "right"}:
        row = (variation // (32 * 32 * 16)) % 2
        left_patch, right_patch = row * 2, row * 2 + 1
        red_patch, green_patch = (left_patch, right_patch) if relation == "left" else (right_patch, left_patch)
    else:
        column = (variation // (32 * 32 * 16 * 2)) % 2
        top_patch, bottom_patch = column, column + 2
        red_patch, green_patch = (top_patch, bottom_patch) if relation == "above" else (bottom_patch, top_patch)
    patches[red_patch].append(("red", local_x, local_y))
    patches[green_patch].append(("green", local_x, local_y))
    permutation = _PATCH_PERMUTATIONS[(variation * 7) % len(_PATCH_PERMUTATIONS)]
    return ([_patch(patches[position]) for position in permutation], [coordinates[position] for position in permutation])


def build_records(tokenizer: Any, *, count: int, image_marker: int) -> list[dict[str, object]]:
    """Build balanced raw-spatial scenes whose target is recomputed from patch bytes and coordinates."""

    if not isinstance(count, int) or count < 512 or count % len(_RELATIONS):
        raise ValueError("owned vision semantic records require a relation-balanced multiple of at least 512 scenes")
    if not isinstance(image_marker, int) or image_marker < 0:
        raise ValueError("image marker must be a nonnegative token ID")
    records: list[dict[str, object]] = []
    for index in range(count):
        patches, coordinates = _scene(index)
        caption = spatial_relation_caption(patches, coordinates)
        encoded = list(tokenizer.encode(caption).ids)
        if len(encoded) < 2:
            raise ValueError("frozen tokenizer cannot encode an owned spatial relation caption")
        scene_sha256 = structural_scene_sha256(patches, coordinates)
        records.append({
            "schema_version": "ember-owned-semantic-record-v1",
            "sample_id": f"owned-vision-spatial-{index:08d}",
            "scene_split": _SPLITS[(index // len(_RELATIONS)) % len(_SPLITS)],
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
