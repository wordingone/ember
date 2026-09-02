# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Locally recompute specialist supervision from raw owned samples."""

from __future__ import annotations

import base64
import hashlib
import json
import struct
from typing import Mapping, Sequence

IMAGE_WIDTH = 48
IMAGE_HEIGHT = 48
IMAGE_CHANNELS = 3
IMAGE_BYTES = IMAGE_WIDTH * IMAGE_HEIGHT * IMAGE_CHANNELS
PALETTE = {
    "red": (224, 32, 32),
    "green": (32, 176, 64),
    "blue": (48, 96, 224),
}


def _coordinate_pair(value: object) -> tuple[int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2 or any(not isinstance(axis, int) for axis in value):
        raise ValueError("image coordinates must be integer [x, y] pairs")
    return int(value[0]), int(value[1])


def _color_center(patches: Sequence[bytes], coordinates: Sequence[object], rgb: tuple[int, int, int]) -> tuple[int, int]:
    if len(patches) != len(coordinates) or not patches:
        raise ValueError("spatial image supervision requires one coordinate per raw patch")
    points: list[tuple[int, int]] = []
    for patch, coordinate in zip(patches, coordinates):
        if len(patch) != IMAGE_BYTES:
            raise ValueError("image patch does not have the authorized 48x48x3 shape")
        patch_x, patch_y = _coordinate_pair(coordinate)
        for pixel in range(IMAGE_WIDTH * IMAGE_HEIGHT):
            offset = pixel * IMAGE_CHANNELS
            if tuple(patch[offset : offset + IMAGE_CHANNELS]) == rgb:
                points.append((patch_x * IMAGE_WIDTH + pixel % IMAGE_WIDTH, patch_y * IMAGE_HEIGHT + pixel // IMAGE_WIDTH))
    if len(points) != 16:
        raise ValueError("spatial image scene must contain exactly one 4x4 object of each queried color")
    sum_x = sum(point[0] for point in points)
    sum_y = sum(point[1] for point in points)
    return sum_x, sum_y


def spatial_relation_caption(patches: Sequence[bytes], coordinates: Sequence[object]) -> str:
    """Derive the red-versus-green relation from raw patch content and explicit 2D coordinates."""

    red_x, red_y = _color_center(patches, coordinates, PALETTE["red"])
    green_x, green_y = _color_center(patches, coordinates, PALETTE["green"])
    if red_y == green_y and red_x != green_x:
        relation = "left" if red_x < green_x else "right"
    elif red_x == green_x and red_y != green_y:
        relation = "above" if red_y < green_y else "below"
    else:
        raise ValueError("spatial image scene is not an unambiguous axial relation")
    return f"red is {relation} of green" if relation in {"left", "right"} else f"red is {relation} green"


def structural_scene_sha256(patches: Sequence[bytes], coordinates: Sequence[object]) -> str:
    """Hash the canonical coordinate-to-patch mapping for split/dedup custody."""

    if len(patches) != len(coordinates) or not patches:
        raise ValueError("structural scene hash requires one coordinate per patch")
    rows = []
    for patch, coordinate in zip(patches, coordinates):
        if len(patch) != IMAGE_BYTES:
            raise ValueError("image patch does not have the authorized 48x48x3 shape")
        x, y = _coordinate_pair(coordinate)
        rows.append({"coordinate": [x, y], "patch_sha256": hashlib.sha256(patch).hexdigest()})
    payload = json.dumps(sorted(rows, key=lambda row: tuple(row["coordinate"])), separators=(",", ":"), sort_keys=True).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def verify_image_supervision(
    record: Mapping[str, object], *, patches: Sequence[bytes], tokenizer: object, image_marker: int,
) -> None:
    """Prove target IDs encode a relation recomputed from exact raw RGB patches and 2D positions."""

    coordinates = record.get("image_coordinates")
    if not isinstance(coordinates, list):
        raise ValueError("image semantic record lacks explicit image coordinates")
    caption = spatial_relation_caption(patches, coordinates)
    expected_evidence = {"image": {
        "target_sha256": hashlib.sha256(caption.encode("utf-8")).hexdigest(),
        "scene_sha256": structural_scene_sha256(patches, coordinates),
        "derivation": "raw_image_spatial_relation_execution",
    }}
    if record.get("capability_evidence") != expected_evidence or record.get("target_text") != caption:
        raise ValueError("image semantic target is not the locally derived raw-spatial scene relation")
    encoded = list(tokenizer.encode(caption).ids)
    token_ids = record.get("token_ids")
    target_ids = record.get("target_ids")
    if len(encoded) < 2 or target_ids != [*[image_marker] * (len(patches) - 1), *encoded] or token_ids != [*[image_marker] * len(patches), *encoded[:-1]]:
        raise ValueError("image semantic target tokenization does not bind the frozen tokenizer and raw spatial scene")


def _audio_frame_polarity(frame: bytes) -> str:
    if len(frame) != 640 * 2:
        raise ValueError("audio frame does not have the authorized 640-sample int16 shape")
    total = sum(struct.unpack("<640h", frame))
    return "positive" if total > 0 else "negative" if total < 0 else "silent"


def audio_caption(frames: Sequence[bytes]) -> str:
    if not frames:
        raise ValueError("audio supervision requires at least one raw frame")
    counts = {name: sum(_audio_frame_polarity(frame) == name for frame in frames) for name in ("positive", "negative", "silent")}
    return "audio signal has {positive} positive frames {negative} negative frames {silent} silent frames".format(**counts)


def verify_audio_supervision(record: Mapping[str, object], *, frames: Sequence[bytes], tokenizer: object, audio_marker: int) -> None:
    """Prove target IDs encode the caption recomputed from exact raw PCM frames."""
    caption = audio_caption(frames)
    expected_evidence = {"audio": {"caption_sha256": hashlib.sha256(caption.encode("utf-8")).hexdigest(), "derivation": "raw_audio_signal_execution"}}
    if record.get("capability_evidence") != expected_evidence or record.get("target_text") != caption:
        raise ValueError("audio semantic target is not the locally derived raw-signal caption")
    encoded = list(tokenizer.encode(caption).ids)
    if len(encoded) < 2 or record.get("target_ids") != [*[audio_marker] * (len(frames) - 1), *encoded] or record.get("token_ids") != [*[audio_marker] * len(frames), *encoded[:-1]]:
        raise ValueError("audio semantic target tokenization does not bind the frozen tokenizer and raw signal")