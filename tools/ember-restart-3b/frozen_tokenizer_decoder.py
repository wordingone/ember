# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""Fail-closed in-memory decoder wiring for Ember's frozen ByteLevel tokenizer."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def attach_frozen_bytelevel_decoder(
    tokenizer: Any,
    tokenizer_json_bytes: bytes,
) -> dict[str, object]:
    """Attach ByteLevel decoding only when exact tokenizer bytes require it."""

    try:
        decoded = tokenizer_json_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("tokenizer bytes must be strict UTF-8") from error
    try:
        document = json.loads(decoded)
    except json.JSONDecodeError as error:
        raise ValueError("tokenizer bytes must contain a valid JSON object") from error
    if not isinstance(document, Mapping):
        raise ValueError("tokenizer bytes must contain a valid JSON object")

    pre_tokenizer = document.get("pre_tokenizer")
    if (
        not isinstance(pre_tokenizer, Mapping)
        or pre_tokenizer.get("type") != "ByteLevel"
    ):
        raise ValueError("tokenizer pre_tokenizer.type must be ByteLevel")

    if document.get("decoder") is not None:
        return {
            "attached": False,
            "reason": "explicit on-disk decoder preserved",
        }

    from tokenizers import decoders

    tokenizer.decoder = decoders.ByteLevel()
    return {
        "attached": True,
        "reason": "attached ByteLevel decoder in memory",
    }
