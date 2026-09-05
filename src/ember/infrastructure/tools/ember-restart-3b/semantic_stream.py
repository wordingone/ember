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
    shards: list[dict[str, Any]]
    shard_ledger_path: Path | None

    LEDGER_SCHEMA = "ember-catalog-train-shard-ledger-v1"
    LEDGER_GENESIS_PREV = "0" * 64

    @classmethod
    def from_receipt(cls, *, receipt_path: Path, shards_root: Path, tokenizer_path: Path, shard_ledger: Path | None = None) -> "ManifestBoundTokenStream":
        """Open the immutable receipt; a shard ledger beside it (default name, or `shard_ledger`) is
        consulted only when a read reaches the end of the shards verified so far (#2135)."""

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
        if shard_ledger is None:
            binding = receipt.get("catalog_binding") if isinstance(receipt.get("catalog_binding"), dict) else {}
            shard_tokens = binding.get("shard_tokens")
            candidate = receipt_path.resolve().parent / f"shard-ledger-s{shard_tokens}.jsonl" if isinstance(shard_tokens, int) else None
            shard_ledger = candidate if candidate is not None and candidate.is_file() else None
        return cls(
            receipt=receipt,
            receipt_sha256=hashlib.sha256(receipt_bytes).hexdigest(),
            shards_root=root,
            tokenizer_receipt_path=str(tokenizer["path"]),
            tokenizer_sha256=tokenizer_sha256,
            vocab_size=vocab_size,
            shards=[dict(item) for item in shards],
            shard_ledger_path=shard_ledger.resolve() if shard_ledger is not None else None,
        )

    @property
    def total_stream_tokens(self) -> int:
        return sum(int(item["n_tokens"]) for item in self.shards)

    @staticmethod
    def _ledger_row_sha256(row: dict[str, Any]) -> str:
        body = {key: value for key, value in row.items() if key != "row_sha256"}
        return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()

    def _read_ledger(self) -> list[dict[str, Any]]:
        """Parse the self-chained ledger; any break in the chain refuses the whole file."""

        assert self.shard_ledger_path is not None
        rows: list[dict[str, Any]] = []
        prev = self.LEDGER_GENESIS_PREV
        running = 0
        for line in self.shard_ledger_path.read_bytes().split(b"\n"):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError as error:
                raise ValueError("semantic stream shard ledger row is not readable JSON") from error
            if not isinstance(row, dict) or row.get("schema_version") != self.LEDGER_SCHEMA:
                raise ValueError("semantic stream shard ledger schema is not recognized")
            if row.get("index") != len(rows) or row.get("prev_row_sha256") != prev or row.get("row_sha256") != self._ledger_row_sha256(row):
                raise ValueError(f"semantic stream shard ledger chain is broken at row {len(rows)}")
            if type(row.get("n_tokens")) is not int or row["n_tokens"] < 1 or row.get("token_start") != running:
                raise ValueError(f"semantic stream shard ledger geometry is invalid at row {len(rows)}")
            if not isinstance(row.get("name"), str) or not isinstance(row.get("sha256"), str):
                raise ValueError(f"semantic stream shard ledger identity is invalid at row {len(rows)}")
            running += row["n_tokens"]
            prev = row["row_sha256"]
            rows.append(row)
        return rows

    def refresh_from_ledger(self) -> int:
        """Extend the verified shard list from the ledger; returns how many shards were appended.

        The receipt stays the identity spine (`receipt_sha256` never changes). Rows 0..K-1 of the
        ledger must restate the receipt's K shards; every later row is admitted only after its chain
        link and its shard bytes (size and sha256) verify, exactly as `from_receipt` verified the
        receipt's own shards.
        """

        if self.shard_ledger_path is None or not self.shard_ledger_path.is_file():
            return 0
        rows = self._read_ledger()
        receipt_shards = self.receipt["shards"]
        if len(rows) < len(receipt_shards):
            raise ValueError("semantic stream shard ledger is shorter than the receipt it extends")
        for index, item in enumerate(receipt_shards):
            row = rows[index]
            if (row["name"], row["sha256"], row["n_tokens"]) != (item["name"], item["sha256"], item["n_tokens"]):
                raise ValueError(f"semantic stream shard ledger does not restate receipt shard {index}")
        appended = 0
        for row in rows[len(self.shards):]:
            path = (self.shards_root / str(row["name"])).resolve()
            if path.parent != self.shards_root or not path.is_file() or path.stat().st_size != row["n_tokens"] * 2:
                raise ValueError("semantic stream ledger shard bytes do not match the ledger declaration")
            if _sha256(path) != row["sha256"]:
                raise ValueError("semantic stream ledger shard sha256 does not match the ledger")
            self.shards.append({"name": row["name"], "sha256": row["sha256"], "n_tokens": row["n_tokens"]})
            appended += 1
        return appended

    def _read_tokens(self, *, shard_index: int, token_offset: int, count: int) -> list[int]:
        shards = self.shards
        index = shard_index
        offset = token_offset
        tokens: list[int] = []
        while len(tokens) < count:
            if index >= len(shards):
                if self.refresh_from_ledger() == 0:
                    raise ValueError("semantic stream reached the end of the receipt")
                continue
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
        shards = self.shards
        index, offset, remaining = shard_index, token_offset, count
        while remaining:
            if index >= len(shards):
                if self.refresh_from_ledger() == 0:
                    raise ValueError("semantic stream reached the end of the receipt")
                continue
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
        if isinstance(shard_index, int) and shard_index >= len(self.shards):
            self.refresh_from_ledger()
        shards = self.shards
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