# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Shard-ledger boundary refresh of the manifest-bound token stream (#2135)."""

from __future__ import annotations

import hashlib
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"))

from semantic_stream import ManifestBoundTokenStream  # noqa: E402

LEDGER_SCHEMA = "ember-catalog-train-shard-ledger-v1"


def _row_sha(row: dict) -> str:
    body = {k: v for k, v in row.items() if k != "row_sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _ledger_row(index: int, name: str, digest: str, n_tokens: int, token_start: int, prev: str, exhausted: bool = False) -> dict:
    row = {
        "schema_version": LEDGER_SCHEMA, "index": index, "name": name, "sha256": digest, "n_tokens": n_tokens, "token_start": token_start,
        "spans": [{"sha256": "a" * 64, "token_start": token_start, "token_end": token_start + n_tokens}],
        "resume": {"object_index": 0, "carry_tokens": 0}, "staged_objects_exhausted": exhausted, "prev_row_sha256": prev,
    }
    row["row_sha256"] = _row_sha(row)
    return row


class SemanticStreamLedgerTests(unittest.TestCase):
    def _world(self, root: Path) -> tuple[Path, Path, list[dict]]:
        tokenizer = root / "tokenizer.json"
        vocab = {f"token-{index}": index for index in range(8, 1025)}
        tokenizer.write_text(json.dumps({"model": {"vocab": vocab}}, sort_keys=True), encoding="utf-8")
        shards = []
        for index, tokens in enumerate([[10, 11, 12, 13], [14, 15, 16, 17]]):
            shard = root / f"v1-{index:05d}.bin"
            shard.write_bytes(struct.pack(f"<{len(tokens)}H", *tokens))
            shards.append({"name": shard.name, "sha256": hashlib.sha256(shard.read_bytes()).hexdigest(), "n_tokens": len(tokens)})
        receipt = {
            "ticket": "TOKEN-SHARDS-V0", "shards": shards, "total_stream_tokens": 8, "reserved_band_guard": {"max_id_lt": 32},
            "premises": {"tokenizer_json": {"path": tokenizer.name, "sha256": hashlib.sha256(tokenizer.read_bytes()).hexdigest()}},
            "catalog_binding": {"shard_tokens": 4},
        }
        receipt_path = root / "catalog-train-stream-receipt-k2-s4.json"
        receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
        return receipt_path, tokenizer, shards

    def _ledger(self, root: Path, shards: list[dict], extra: list[list[int]]) -> tuple[Path, list[dict]]:
        rows = []
        prev = "0" * 64
        running = 0
        for index, item in enumerate(shards):
            row = _ledger_row(index, item["name"], item["sha256"], item["n_tokens"], running, prev)
            rows.append(row); prev = row["row_sha256"]; running += item["n_tokens"]
        for offset, tokens in enumerate(extra):
            raw = struct.pack(f"<{len(tokens)}H", *tokens)
            digest = hashlib.sha256(raw).hexdigest()
            name = f"v1-{len(rows):05d}-{digest[:12]}.bin"
            (root / name).write_bytes(raw)
            row = _ledger_row(len(rows), name, digest, len(tokens), running, prev, exhausted=offset == len(extra) - 1)
            rows.append(row); prev = row["row_sha256"]; running += len(tokens)
        ledger = root / "shard-ledger-s4.jsonl"
        ledger.write_bytes(b"".join(json.dumps(r, sort_keys=True, separators=(",", ":")).encode() + b"\n" for r in rows))
        return ledger, rows

    def test_reads_past_the_receipt_only_after_the_ledger_grows_and_keeps_the_receipt_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt_path, tokenizer, shards = self._world(root)
            stream = ManifestBoundTokenStream.from_receipt(receipt_path=receipt_path, shards_root=root, tokenizer_path=tokenizer)
            identity = stream.receipt_sha256
            self.assertIsNone(stream.shard_ledger_path)
            episode, cursor = stream.next_episode(shard_index=0, token_offset=0, sequence_length=4)
            self.assertEqual(cursor, {"shard_index": 0, "token_offset": 4, "tokens_seen": 4})
            # The receipt ends after 8 tokens: an episode needing tokens 4..8 plus the lookahead refuses.
            with self.assertRaisesRegex(ValueError, "end of the receipt"):
                stream.next_episode(shard_index=1, token_offset=0, sequence_length=4)
            # Production happens beside the stream; a fresh open finds the default-named ledger and a
            # live stream can be pointed at it too.
            ledger, rows = self._ledger(root, shards, extra=[[18, 19, 20, 21], [22, 23]])
            object.__setattr__(stream, "shard_ledger_path", ledger)
            episode, cursor = stream.next_episode(shard_index=1, token_offset=0, sequence_length=4)
            self.assertEqual(episode["token_ids"], [14, 15, 16, 17])
            self.assertEqual(episode["target_ids"], [15, 16, 17, 18])
            self.assertEqual(cursor, {"shard_index": 1, "token_offset": 4, "tokens_seen": 4})
            self.assertEqual(len(stream.shards), 4)
            self.assertEqual(stream.total_stream_tokens, 14)
            self.assertEqual(stream.receipt_sha256, identity)
            self.assertEqual(len(stream.receipt["shards"]), 2, "the receipt object itself is never extended")
            episode, cursor = stream.next_episode(shard_index=2, token_offset=0, sequence_length=5)
            self.assertEqual(episode["token_ids"], [18, 19, 20, 21, 22])
            self.assertEqual(cursor, {"shard_index": 3, "token_offset": 1, "tokens_seen": 5})
            reopened = ManifestBoundTokenStream.from_receipt(receipt_path=receipt_path, shards_root=root, tokenizer_path=tokenizer)
            self.assertEqual(reopened.shard_ledger_path, ledger.resolve())
            self.assertEqual(reopened.receipt_sha256, identity)
            self.assertEqual(reopened.refresh_from_ledger(), 2)

    def test_refuses_a_broken_chain_a_drifted_shard_and_a_ledger_that_contradicts_the_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt_path, tokenizer, shards = self._world(root)
            ledger, rows = self._ledger(root, shards, extra=[[18, 19, 20, 21]])
            stream = ManifestBoundTokenStream.from_receipt(receipt_path=receipt_path, shards_root=root, tokenizer_path=tokenizer, shard_ledger=ledger)
            # drifted bytes of a ledger shard
            (root / rows[2]["name"]).write_bytes(struct.pack("<4H", 18, 19, 20, 99))
            with self.assertRaisesRegex(ValueError, "ledger shard sha256"):
                stream.next_episode(shard_index=1, token_offset=0, sequence_length=4)
            (root / rows[2]["name"]).write_bytes(struct.pack("<4H", 18, 19, 20, 21))
            # a tampered row breaks the chain for the whole file
            lines = ledger.read_bytes().split(b"\n")
            tampered = json.loads(lines[2]); tampered["n_tokens"] = 3
            lines[2] = json.dumps(tampered, sort_keys=True, separators=(",", ":")).encode()
            ledger.write_bytes(b"\n".join(lines))
            with self.assertRaisesRegex(ValueError, "chain is broken at row 2"):
                stream.next_episode(shard_index=1, token_offset=0, sequence_length=4)
            # a ledger whose genesis disagrees with the receipt refuses before any byte is read
            rows2 = [_ledger_row(0, "other.bin", "b" * 64, 4, 0, "0" * 64)]
            ledger.write_bytes(json.dumps(rows2[0], sort_keys=True, separators=(",", ":")).encode() + b"\n")
            with self.assertRaisesRegex(ValueError, "shorter than the receipt|does not restate receipt shard 0"):
                stream.refresh_from_ledger()


if __name__ == "__main__":
    unittest.main()
