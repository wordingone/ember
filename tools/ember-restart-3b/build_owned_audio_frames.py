# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Build owned, raw-PCM frame records for the audio specialist."""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from specialist_semantics import audio_caption


def _frame(polarity: str, variant: int) -> bytes:
    """Emit a deterministic signed or zero-sum 40ms frame with index-bound variation."""

    amplitude = 400 + (variant % 1024) * 12
    phase = (variant * 37) % 97
    if polarity == "positive":
        samples = [amplitude + ((sample * (1 + variant % 31) + phase) % 97) - 48 for sample in range(640)]
    elif polarity == "negative":
        samples = [-(amplitude + ((sample * (1 + variant % 31) + phase) % 97) - 48) for sample in range(640)]
    elif polarity == "silent":
        samples = [amplitude if sample % 2 == 0 else -amplitude for sample in range(640)]
    else:
        raise ValueError("unknown owned audio frame polarity")
    return b"".join(int(value).to_bytes(2, "little", signed=True) for value in samples)
def _episode_frames(index: int) -> list[bytes]:
    patterns = tuple(
        tuple(["positive"] * positive + ["negative"] * negative + ["silent"] * (4 - positive - negative))
        for positive in range(5)
        for negative in range(5 - positive)
    )
    pattern = patterns[index % len(patterns)]
    return [_frame(polarity, index * 4 + offset) for offset, polarity in enumerate(pattern)]

def build_records(tokenizer: Any, *, count: int, audio_marker: int) -> list[dict[str, object]]:
    """Build deterministic, diverse owned PCM episodes; targets derive from the raw frames."""
    if not isinstance(count, int) or count < 512:
        raise ValueError("owned audio semantic records require at least 512 episodes")
    if not isinstance(audio_marker, int) or audio_marker < 0:
        raise ValueError("audio marker must be a nonnegative token ID")
    records: list[dict[str, object]] = []
    for index in range(count):
        frames = _episode_frames(index)
        caption = audio_caption(frames)
        encoded = list(tokenizer.encode(caption).ids)
        if len(encoded) < 2:
            raise ValueError("frozen tokenizer cannot encode an owned audio caption")
        records.append({
            "schema_version": "ember-owned-semantic-record-v1",
            "sample_id": f"owned-audio-frame-{index:08d}",
            "active_expert": "audio",
            "token_ids": [*[audio_marker] * 4, *encoded[:-1]],
            "target_ids": [*[audio_marker] * 3, *encoded],
            "target_text": caption,
            "audio_frames_i16le_base64": [base64.b64encode(frame).decode("ascii") for frame in frames],
            "image_coordinates": [],
            "multimodal_spans": [{"start": 0, "length": 4, "modality": "audio", "attention_mode": "causal"}],
            "capability_evidence": {"audio": {"caption_sha256": hashlib.sha256(caption.encode("utf-8")).hexdigest(), "derivation": "raw_audio_signal_execution"}},
        })
    return records
def record_at(tokenizer: Any, *, count: int, audio_marker: int, index: int) -> dict[str, object]:
    """Regenerate one owned audio episode without allocating its family."""
    if not isinstance(count, int) or count < 512 or not isinstance(index, int) or not 0 <= index < count:
        raise ValueError("owned audio stream index is outside the declared range")
    if not isinstance(audio_marker, int) or audio_marker < 0:
        raise ValueError("audio marker must be a nonnegative token ID")
    frames = _episode_frames(index)
    caption = audio_caption(frames)
    encoded = list(tokenizer.encode(caption).ids)
    if len(encoded) < 2:
        raise ValueError("frozen tokenizer cannot encode an owned audio caption")
    return {
        "schema_version": "ember-owned-semantic-record-v1", "sample_id": f"owned-audio-frame-{index:08d}", "active_expert": "audio",
        "token_ids": [*[audio_marker] * 4, *encoded[:-1]], "target_ids": [*[audio_marker] * 3, *encoded], "target_text": caption,
        "audio_frames_i16le_base64": [base64.b64encode(frame).decode("ascii") for frame in frames], "image_coordinates": [],
        "multimodal_spans": [{"start": 0, "length": 4, "modality": "audio", "attention_mode": "causal"}],
        "capability_evidence": {"audio": {"caption_sha256": hashlib.sha256(caption.encode("utf-8")).hexdigest(), "derivation": "raw_audio_signal_execution"}},
    }
