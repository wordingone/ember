# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Locally recompute specialist supervision from raw owned samples."""

from __future__ import annotations

import hashlib
from collections import deque
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


def _component_count(patch: bytes, rgb: tuple[int, int, int]) -> int:
    if len(patch) != IMAGE_BYTES:
        raise ValueError("image patch does not have the authorized 48x48x3 shape")
    visited: set[int] = set()
    count = 0
    for index in range(IMAGE_WIDTH * IMAGE_HEIGHT):
        if index in visited:
            continue
        offset = index * IMAGE_CHANNELS
        if tuple(patch[offset : offset + IMAGE_CHANNELS]) != rgb:
            continue
        count += 1
        queue = deque([index])
        visited.add(index)
        while queue:
            current = queue.popleft()
            x, y = current % IMAGE_WIDTH, current // IMAGE_WIDTH
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                candidate = ny * IMAGE_WIDTH + nx
                if nx < 0 or nx >= IMAGE_WIDTH or ny < 0 or ny >= IMAGE_HEIGHT or candidate in visited:
                    continue
                candidate_offset = candidate * IMAGE_CHANNELS
                if tuple(patch[candidate_offset : candidate_offset + IMAGE_CHANNELS]) == rgb:
                    visited.add(candidate)
                    queue.append(candidate)
    return count


def image_caption(patches: Sequence[bytes]) -> str:
    if not patches:
        raise ValueError("image supervision requires at least one raw patch")
    counts = {name: sum(_component_count(patch, rgb) for patch in patches) for name, rgb in PALETTE.items()}
    return "image scene has {red} red squares {green} green squares {blue} blue squares".format(**counts)


def verify_image_supervision(
    record: Mapping[str, object], *, patches: Sequence[bytes], tokenizer: object, image_marker: int,
) -> None:
    """Prove target IDs encode the caption recomputed from exact raw RGB patches."""

    caption = image_caption(patches)
    evidence = record.get("capability_evidence")
    expected_evidence = {
        "image": {
            "caption_sha256": hashlib.sha256(caption.encode("utf-8")).hexdigest(),
            "derivation": "raw_image_property_execution",
        }
    }
    if evidence != expected_evidence or record.get("target_text") != caption:
        raise ValueError("image semantic target is not the locally derived raw-scene caption")
    encoded = list(tokenizer.encode(caption).ids)
    token_ids = record.get("token_ids")
    target_ids = record.get("target_ids")
    if len(encoded) < 2 or target_ids != [*[image_marker] * (len(patches) - 1), *encoded] or token_ids != [*[image_marker] * len(patches), *encoded[:-1]]:
        raise ValueError("image semantic target tokenization does not bind the frozen tokenizer and raw scene")

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