# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Receipt-bound streaming access to owned little-endian uint16 token shards."""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tokenizer_vocab_size(tokenizer_path: Path, expected_sha256: str) -> int:
    if _sha256(tokenizer_path) != expected_sha256:
        raise ValueError("semantic stream tokenizer sha256 does not match the receipt premise")
    try:
        payload = json.loads(tokenizer_path.read_text(encoding="utf-8"))
        vocabulary = payload["model"]["vocab"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("semantic stream tokenizer bytes do not declare a frozen vocabulary") from error
    if isinstance(vocabulary, dict) and vocabulary and all(isinstance(value, int) and value >= 0 for value in vocabulary.values()):
        return max(vocabulary.values()) + 1
    if isinstance(vocabulary, list) and vocabulary:
        return len(vocabulary)
    raise ValueError("semantic stream tokenizer vocabulary is invalid")


@dataclass(frozen=True)
class ManifestBoundTokenStream:
    """Read only receipt-verified shards and emit shared-core next-token episodes."""

    receipt: dict[str, Any]
    receipt_sha256: str
    shards_root: Path
    tokenizer_receipt_path: str
    tokenizer_sha256: str
    vocab_size: int

    @classmethod
    def from_receipt(cls, *, receipt_path: Path, shards_root: Path, tokenizer_path: Path) -> "ManifestBoundTokenStream":
        try:
            receipt_bytes = receipt_path.read_bytes()
            receipt = json.loads(receipt_bytes)
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("semantic stream receipt must be readable JSON") from error
        shards = receipt.get("shards") if isinstance(receipt, dict) else None
        premises = receipt.get("premises") if isinstance(receipt, dict) else None
        tokenizer = premises.get("tokenizer_json") if isinstance(premises, dict) else None
        if receipt.get("ticket") != "TOKEN-SHARDS-V0" or not isinstance(shards, list) or not shards:
            raise ValueError("semantic stream receipt does not declare TOKEN-SHARDS-V0 shards")
        if not isinstance(tokenizer, dict) or not isinstance(tokenizer.get("path"), str) or not isinstance(tokenizer.get("sha256"), str):
            raise ValueError("semantic stream receipt does not bind frozen tokenizer bytes")
        tokenizer_sha256 = str(tokenizer["sha256"])
        vocab_size = _tokenizer_vocab_size(tokenizer_path.resolve(), tokenizer_sha256)
        total = 0
        root = shards_root.resolve()
        for item in shards:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not isinstance(item.get("sha256"), str) or not isinstance(item.get("n_tokens"), int):
                raise ValueError("semantic stream receipt shard declaration is invalid")
            path = (root / item["name"]).resolve()
            if path.parent != root or not path.is_file() or path.stat().st_size != item["n_tokens"] * 2:
                raise ValueError("semantic stream shard bytes do not match the receipt declaration")
            if _sha256(path) != item["sha256"]:
                raise ValueError("semantic stream shard sha256 does not match the receipt")
            total += item["n_tokens"]
        if receipt.get("total_stream_tokens") != total:
            raise ValueError("semantic stream receipt total does not equal declared shard tokens")
        return cls(
            receipt=receipt,
            receipt_sha256=hashlib.sha256(receipt_bytes).hexdigest(),
            shards_root=root,
            tokenizer_receipt_path=str(tokenizer["path"]),
            tokenizer_sha256=tokenizer_sha256,
            vocab_size=vocab_size,
        )

    def _read_tokens(self, *, shard_index: int, token_offset: int, count: int) -> list[int]:
        shards = self.receipt["shards"]
        index = shard_index
        offset = token_offset
        tokens: list[int] = []
        while len(tokens) < count:
            if index >= len(shards):
                raise ValueError("semantic stream reached the end of the receipt")
            item = shards[index]
            available = int(item["n_tokens"]) - offset
            if available < 0:
                raise ValueError("semantic stream token offset is out of range")
            if available == 0:
                index += 1
                offset = 0
                continue
            take = min(count - len(tokens), available)
            path = self.shards_root / str(item["name"])
            with path.open("rb") as handle:
                handle.seek(offset * 2)
                raw = handle.read(take * 2)
            if len(raw) != take * 2:
                raise ValueError("semantic stream shard became truncated after verification")
            tokens.extend(struct.unpack(f"<{take}H", raw))
            index += 1
            offset = 0
        return tokens

    def _advance(self, *, shard_index: int, token_offset: int, count: int) -> tuple[int, int]:
        shards = self.receipt["shards"]
        index, offset, remaining = shard_index, token_offset, count
        while remaining:
            if index >= len(shards):
                raise ValueError("semantic stream reached the end of the receipt")
            available = int(shards[index]["n_tokens"]) - offset
            if available <= 0:
                index += 1
                offset = 0
                continue
            moved = min(remaining, available)
            offset += moved
            remaining -= moved
            if offset == int(shards[index]["n_tokens"]) and remaining:
                index += 1
                offset = 0
        return index, offset

    def next_episode(self, *, shard_index: int, token_offset: int, sequence_length: int) -> tuple[dict[str, Any], dict[str, int]]:
        shards = self.receipt["shards"]
        if not isinstance(shard_index, int) or not 0 <= shard_index < len(shards):
            raise ValueError("semantic stream shard index is out of range")
        if not isinstance(token_offset, int) or token_offset < 0 or not isinstance(sequence_length, int) or sequence_length < 1:
            raise ValueError("semantic stream offset and sequence length must be positive")
        tokens = self._read_tokens(shard_index=shard_index, token_offset=token_offset, count=sequence_length + 1)
        if any(token >= self.vocab_size for token in tokens):
            raise ValueError("semantic stream token IDs violate the receipt-bound tokenizer vocabulary")
        next_index, next_offset = self._advance(shard_index=shard_index, token_offset=token_offset, count=sequence_length)
        return (
            {"schema_version": "ember-owned-semantic-text-v1", "active_expert": "shared", "token_ids": tokens[:-1], "target_ids": tokens[1:]},
            {"shard_index": next_index, "token_offset": next_offset, "tokens_seen": sequence_length},
        )