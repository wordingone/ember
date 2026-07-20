# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The semantic stream binds the recovered tokenizer through a sanitized public chain."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tokenizers import Tokenizer


ROOT = Path(__file__).resolve().parents[2]
TOKENIZER = ROOT / "tokenizer" / "tokenizer.json"
RECEIPTS = ROOT / "receipts"
ASSEMBLY = RECEIPTS / "eng36-assembly-20260611T052337Z.json"
FREEZE = RECEIPTS / "tokenizer-freeze-20260611T154111Z.json"
SHARDS = RECEIPTS / "token-shards-v0-20260611T170047Z.json"

RESTORED_TOKENIZER_SHA256 = (
    "2c557e7ffe64706112ea947d056be503005d90b16f64c57ec354267c7e9e9c97"
)
INVALID_TOKENIZER_SHA256 = (
    "6923a52304637f48eb4cc421b58e6cdce29c1f5da860abaea5d57baa6ad6d97d"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_token_shards_bind_loadable_tokenizer_and_sanitized_public_receipts() -> None:
    tokenizer = Tokenizer.from_file(str(TOKENIZER))
    assert tokenizer.get_vocab_size() == 32_000
    assert sha256(TOKENIZER) == RESTORED_TOKENIZER_SHA256

    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    assert freeze["tokenizer_json_sha256"] == RESTORED_TOKENIZER_SHA256
    assert sha256(ASSEMBLY) == (
        "f6d0734e090fcaef84ac2361f42c7419f5e40b586355bc4a385e7a695250c841"
    )
    assert sha256(FREEZE) == (
        "2e96e70fe7463b272c00ea49e61e001402319a398a447debb9afe283586ac1c4"
    )

    receipt = json.loads(SHARDS.read_text(encoding="utf-8"))
    assert receipt["goal_id"] == "EMBER-02"
    assert receipt["workstream_id"] == "EMBER-02A"
    assert (
        receipt["next_executed_outcome"]
        == "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
    )
    assert receipt["ticket"] == "TOKEN-SHARDS-V0"
    assert "provenance_230" not in receipt
    assert receipt["superseded_provenance_230"]
    restoration = receipt["provenance_restoration_20260714"]
    assert restoration["status"] == "CURRENT"
    assert restoration["invalid_tokenizer_sha256"] == INVALID_TOKENIZER_SHA256
    assert restoration["restored_tokenizer_sha256"] == RESTORED_TOKENIZER_SHA256
    assert restoration["restored_from_content_addressed_lineage"] is True
    assert restoration["assembly_and_freeze_public_bytes_unchanged"] is True
    assert restoration["shard_bytes_unchanged"] is True
    assert receipt["premises"] == {
        "assembly_receipt": {
            "name": ASSEMBLY.name,
            "sha256": sha256(ASSEMBLY),
        },
        "tokenizer_freeze_receipt": {
            "name": FREEZE.name,
            "sha256": sha256(FREEZE),
        },
        "tokenizer_json": {
            "path": "tokenizer/tokenizer.json",
            "sha256": sha256(TOKENIZER),
        },
    }
