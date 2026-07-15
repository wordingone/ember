# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Build owned, raw-RGB scene records for the vision specialist."""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from specialist_semantics import IMAGE_BYTES, PALETTE, image_caption


_PLACEMENTS = [(2 + 8 * column, 2 + 8 * row) for row in range(5) for column in range(5)]


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
    """Generate a deterministic high-variation four-patch scene from its index."""

    counts = {"red": 1 + index % 4, "green": 1 + (index // 4) % 4, "blue": 1 + (index // 16) % 4}
    per_patch: list[list[tuple[str, int, int]]] = [[], [], [], []]
    stride_choices = (1, 2, 3, 4, 6, 7, 8, 9, 11, 12)
    stride = stride_choices[(index // 25) % len(stride_choices)]
    placement = (index * 7 + index // 125) % len(_PLACEMENTS)
    object_index = 0
    for color in ("red", "green", "blue"):
        for _ in range(counts[color]):
            x, y = _PLACEMENTS[(placement + object_index * stride) % len(_PLACEMENTS)]
            patch_index = (index + object_index + index // 7) % len(per_patch)
            per_patch[patch_index].append((color, x, y))
            object_index += 1
    return [_patch(rectangles) for rectangles in per_patch]
def build_records(tokenizer: Any, *, count: int, image_marker: int) -> list[dict[str, object]]:
    """Build deterministic, diverse owned scenes; labels are recomputed from raw pixels."""

    if not isinstance(count, int) or count < 512:
        raise ValueError("owned vision semantic records require at least 512 scenes")
    if not isinstance(image_marker, int) or image_marker < 0:
        raise ValueError("image marker must be a nonnegative token ID")
    records: list[dict[str, object]] = []
    for index in range(count):
        patches = _scene(index)
        caption = image_caption(patches)
        encoded = list(tokenizer.encode(caption).ids)
        if len(encoded) < 2:
            raise ValueError("frozen tokenizer cannot encode an owned vision caption")
        records.append({
            "schema_version": "ember-owned-semantic-record-v1",
            "sample_id": f"owned-vision-scene-{index:08d}",
            "active_expert": "vision",
            "token_ids": [*[image_marker] * 4, *encoded[:-1]],
            "target_ids": [*[image_marker] * 3, *encoded],
            "target_text": caption,
            "image_patches_u8_base64": [base64.b64encode(patch).decode("ascii") for patch in patches],
            "image_coordinates": [[0, 0], [1, 0], [0, 1], [1, 1]],
            "multimodal_spans": [{"start": 0, "length": 4, "modality": "image", "attention_mode": "isolated"}],
            "capability_evidence": {"image": {"caption_sha256": hashlib.sha256(caption.encode("utf-8")).hexdigest(), "derivation": "raw_image_property_execution"}},
        })
    return records