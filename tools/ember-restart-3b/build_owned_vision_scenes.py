# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Build owned, raw-RGB spatial-relation records for the vision specialist."""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from specialist_semantics import IMAGE_BYTES, PALETTE, spatial_relation_caption, structural_scene_sha256


_COORDINATES = [[0, 0], [1, 0], [0, 1], [1, 1]]
_RELATIONS = ("left", "right", "above", "below")
_SPLITS = ("train", "validation", "test")
_LOCAL_ORIGINS = tuple(2 + 4 * index for index in range(10))


def _patch(rectangles: list[tuple[str, int, int]]) -> bytes:
    pixels = bytearray(IMAGE_BYTES)
    for color, x, y in rectangles:
        rgb = PALETTE[color]
        for row in range(y, y + 4):
            for column in range(x, x + 4):
                offset = (row * 48 + column) * 3
                pixels[offset : offset + 3] = bytes(rgb)
    return bytes(pixels)


def _scene(index: int) -> list[bytes]:
    """Generate a deterministic two-object relation spanning distinct 2D patch coordinates."""

    relation = _RELATIONS[index % len(_RELATIONS)]
    variation = index // len(_RELATIONS)
    local_x = _LOCAL_ORIGINS[(variation // 2) % len(_LOCAL_ORIGINS)]
    local_y = _LOCAL_ORIGINS[(variation // 20) % len(_LOCAL_ORIGINS)]
    patches: list[list[tuple[str, int, int]]] = [[], [], [], []]
    if relation in {"left", "right"}:
        row = variation % 2
        left_patch, right_patch = row * 2, row * 2 + 1
        red_patch, green_patch = (left_patch, right_patch) if relation == "left" else (right_patch, left_patch)
    else:
        column = variation % 2
        top_patch, bottom_patch = column, column + 2
        red_patch, green_patch = (top_patch, bottom_patch) if relation == "above" else (bottom_patch, top_patch)
    patches[red_patch].append(("red", local_x, local_y))
    patches[green_patch].append(("green", local_x, local_y))
    return [_patch(rectangles) for rectangles in patches]


def build_records(tokenizer: Any, *, count: int, image_marker: int) -> list[dict[str, object]]:
    """Build balanced raw-spatial scenes whose target is recomputed from patch bytes and coordinates."""

    if not isinstance(count, int) or count < 512 or count % len(_RELATIONS):
        raise ValueError("owned vision semantic records require a relation-balanced multiple of at least 512 scenes")
    if not isinstance(image_marker, int) or image_marker < 0:
        raise ValueError("image marker must be a nonnegative token ID")
    records: list[dict[str, object]] = []
    for index in range(count):
        patches = _scene(index)
        caption = spatial_relation_caption(patches, _COORDINATES)
        encoded = list(tokenizer.encode(caption).ids)
        if len(encoded) < 2:
            raise ValueError("frozen tokenizer cannot encode an owned spatial relation caption")
        scene_sha256 = structural_scene_sha256(patches, _COORDINATES)
        records.append({
            "schema_version": "ember-owned-semantic-record-v1",
            "sample_id": f"owned-vision-spatial-{index:08d}",
            "scene_split": _SPLITS[(index // len(_RELATIONS)) % len(_SPLITS)],
            "active_expert": "vision",
            "token_ids": [*[image_marker] * 4, *encoded[:-1]],
            "target_ids": [*[image_marker] * 3, *encoded],
            "target_text": caption,
            "image_patches_u8_base64": [base64.b64encode(patch).decode("ascii") for patch in patches],
            "image_coordinates": _COORDINATES,
            "multimodal_spans": [{"start": 0, "length": 4, "modality": "image", "attention_mode": "isolated"}],
            "capability_evidence": {"image": {
                "target_sha256": hashlib.sha256(caption.encode("utf-8")).hexdigest(),
                "scene_sha256": scene_sha256,
                "derivation": "raw_image_spatial_relation_execution",
            }},
        })
    return records