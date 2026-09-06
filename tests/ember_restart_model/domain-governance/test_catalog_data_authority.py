# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#2155: the catalog shard ledger as a governed run's data authority.

The semantic runner (`run_vertical_slice.run_semantic`) already reads past its immutable receipt
through the shard ledger (#2135). What was missing is the BINDING: a run declaring the catalog
stream as its data authority must pin the ledger bytes it consumed from, prove its planned span
fits the verified stream before any model construction, and leave a terminal `data_authority`
block from which the consumption receipt is derivable without the run's process state.
"""

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


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CatalogDataAuthorityTests(unittest.TestCase):
    """Fixture: receipt with 2 shards x 4 tokens; ledger restates them and adds 1 shard x 4 (12 tokens total)."""

    def _world(self, root: Path) -> tuple[Path, Path, Path]:
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
        rows, prev, running = [], "0" * 64, 0
        for index, item in enumerate(shards):
            row = _ledger_row(index, item["name"], item["sha256"], item["n_tokens"], running, prev)
            rows.append(row); prev = row["row_sha256"]; running += item["n_tokens"]
        extra = struct.pack("<4H", 18, 19, 20, 21)
        digest = hashlib.sha256(extra).hexdigest()
        name = f"v1-00002-{digest[:12]}.bin"
        (root / name).write_bytes(extra)
        rows.append(_ledger_row(2, name, digest, 4, running, prev, exhausted=True))
        ledger = root / "shard-ledger-s4.jsonl"
        ledger.write_bytes(b"".join(json.dumps(r, sort_keys=True, separators=(",", ":")).encode() + b"\n" for r in rows))
        return receipt_path, tokenizer, ledger

    def _stream(self, root: Path, ledger: Path | None = None) -> ManifestBoundTokenStream:
        receipt_path, tokenizer, default_ledger = self._world(root)
        return ManifestBoundTokenStream.from_receipt(receipt_path=receipt_path, shards_root=root, tokenizer_path=tokenizer, shard_ledger=ledger)

    def test_binding_the_ledger_pins_its_bytes_and_admits_every_row(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stream = self._stream(root)
            self.assertEqual(len(stream.shards), 2)
            binding = stream.bind_shard_ledger(expected_sha256=_sha_file(root / "shard-ledger-s4.jsonl"))
            self.assertEqual(binding["ledger_rows"], 3)
            self.assertEqual(binding["total_stream_tokens"], 12)
            self.assertEqual(binding["shard_ledger_sha256"], stream.ledger_sha256_now())
            self.assertEqual(len(stream.shards), 3)

    def test_a_ledger_whose_bytes_differ_from_the_pin_refuses_before_any_row_is_admitted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stream = self._stream(root)
            with self.assertRaises(ValueError) as caught:
                stream.bind_shard_ledger(expected_sha256="0" * 64)
            self.assertTrue(str(caught.exception).startswith("CATALOG_STREAM_LEDGER_SHA_MISMATCH"))
            self.assertEqual(len(stream.shards), 2)
            with self.assertRaises(ValueError) as malformed:
                stream.bind_shard_ledger(expected_sha256="not-a-sha")
            self.assertTrue(str(malformed.exception).startswith("CATALOG_STREAM_LEDGER_SHA_MISMATCH"))

    def test_planted_negative_one_altered_row_hash_refuses_with_the_ledger_sha_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt_path, tokenizer, ledger = self._world(root)
            expected = _sha_file(ledger)
            lines = ledger.read_bytes().split(b"\n")
            row = json.loads(lines[2])
            row["row_sha256"] = ("0" if row["row_sha256"][0] != "0" else "1") + row["row_sha256"][1:]
            altered = root / "altered-ledger.jsonl"
            lines[2] = json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
            altered.write_bytes(b"\n".join(lines))
            stream = ManifestBoundTokenStream.from_receipt(receipt_path=receipt_path, shards_root=root, tokenizer_path=tokenizer, shard_ledger=altered)
            with self.assertRaises(ValueError) as caught:
                stream.bind_shard_ledger(expected_sha256=expected)
            self.assertTrue(str(caught.exception).startswith("CATALOG_STREAM_LEDGER_SHA_MISMATCH"))

    def test_a_span_beyond_the_verified_stream_refuses_and_an_exact_fit_is_admitted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stream = self._stream(root)
            stream.bind_shard_ledger(expected_sha256=_sha_file(root / "shard-ledger-s4.jsonl"))
            # 12 tokens exist; an episode span of N tokens needs N + 1 (the final target token).
            self.assertEqual(stream.check_cursor_span(shard_index=0, token_offset=0, tokens=11), {"token_start": 0, "token_end": 11, "total_stream_tokens": 12})
            with self.assertRaises(ValueError) as caught:
                stream.check_cursor_span(shard_index=0, token_offset=0, tokens=12)
            self.assertTrue(str(caught.exception).startswith("CATALOG_STREAM_CURSOR_BEYOND_LEDGER"))
            with self.assertRaises(ValueError) as beyond:
                stream.absolute_token_position(shard_index=3, token_offset=1)
            self.assertTrue(str(beyond.exception).startswith("CATALOG_STREAM_CURSOR_BEYOND_LEDGER"))
            self.assertEqual(stream.absolute_token_position(shard_index=1, token_offset=2), 6)

    def test_without_the_ledger_pin_the_receipt_alone_bounds_the_span(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stream = self._stream(root)
            with self.assertRaises(ValueError):
                stream.check_cursor_span(shard_index=0, token_offset=0, tokens=8)
            self.assertEqual(stream.check_cursor_span(shard_index=0, token_offset=0, tokens=7)["total_stream_tokens"], 8)

    def test_consumed_tokens_derive_from_cursor_positions_alone(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stream = self._stream(root)
            stream.bind_shard_ledger(expected_sha256=_sha_file(root / "shard-ledger-s4.jsonl"))
            shard_index, token_offset, consumed = 0, 0, 0
            for _ in range(3):
                _episode, cursor = stream.next_episode(shard_index=shard_index, token_offset=token_offset, sequence_length=3)
                shard_index, token_offset = cursor["shard_index"], cursor["token_offset"]
                consumed += cursor["tokens_seen"]
            end = stream.absolute_token_position(shard_index=shard_index, token_offset=token_offset)
            self.assertEqual(end, 9)
            self.assertEqual(end - 0, consumed)


class RunSemanticArgumentPairingTests(unittest.TestCase):
    def test_a_ledger_without_its_pin_or_a_pin_without_its_ledger_refuses_before_any_preflight(self) -> None:
        import run_vertical_slice  # noqa: PLC0415  (heavy import kept local to this test)

        common = dict(
            seed=0, artifact_root=Path("unused"), receipt_path=Path("unused"), shards_root=Path("unused"), tokenizer_path=Path("unused"),
            expected_receipt_sha256="r" * 64, expected_tokenizer_sha256="t" * 64, expected_architecture_sha256="a" * 64,
            steps=1, sequence_length=1, checkpoint_interval=1, write_budget_bytes=1,
        )
        for kwargs in ({"shard_ledger": Path("ledger.jsonl")}, {"expected_shard_ledger_sha256": "0" * 64}):
            with self.assertRaises(ValueError) as caught:
                run_vertical_slice.run_semantic(**common, **kwargs)
            self.assertIn("together", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
