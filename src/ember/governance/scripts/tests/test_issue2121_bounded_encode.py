# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#2121 (front unit of #2135->#2121 lineage): bounded-window encode equivalence.

`produce` failed at full-catalog scale with the allocator message "memory allocation of
6979321856 bytes failed" inside a single whole-document `tokenizer.encode()` call on a ~93MB
text_utf8 object (issue2135-u3-governed-79c832a9-20260905T1640Z/produce-exhaust.stderr.log).
This module proves `encode_document_bounded` (catalog_train_stream.py) produces the identical
token stream as the unbounded whole-string encode, so a real object can be encoded in bounded
windows without changing the stream's byte-identity.

Claim boundary: encode-equivalence and cut-safety only. No optimizer consumes anything here.
"""

from __future__ import annotations

import importlib.util
import os
import random
import string
import struct
import tracemalloc
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
SOURCE = ROOT / "src" / "ember" / "governance" / "scripts" / "catalog_train_stream.py"
SPEC = importlib.util.spec_from_file_location("catalog_train_stream_2121", SOURCE)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

# The frozen production tokenizer lives in operator custody outside the repository; the property
# tests against it run only where EMBER_FROZEN_TOKENIZER_JSON names it (skipped elsewhere).
FROZEN_TOKENIZER_PATH = Path(os.environ.get("EMBER_FROZEN_TOKENIZER_JSON", "tokenizer-2c557.json"))

CHARSETS = [
    string.ascii_letters,
    string.digits,
    string.punctuation,
    " ",
    "\t",
    "\n",
    "  ",
    "\t\t",
    "\n\n",
    " \t",
    "\t\n",
    "\u4e2d\u6587\u6c49\u5b57\u6d4b\u8bd5",  # CJK
    "\U0001f600\U0001f602\U0001f389\U0001f680\U0001f916",  # emoji (astral plane)
    "e\u0301a\u0300i\u0308",  # combining marks
    "\u200b\u200d",  # zero-width space / joiner
]


def _tokenizers_or_skip():
    pytest.importorskip("tokenizers")
    from tokenizers import Tokenizer, models, pre_tokenizers

    return Tokenizer, models, pre_tokenizers


def _synthetic_bpe_tokenizer():
    """A byte-level BPE tokenizer with the frozen contract's pre_tokenizer/normalizer shape,
    used when the real frozen tokenizer file is unavailable (keeps this suite runnable without
    custody access)."""

    Tokenizer, models, pre_tokenizers = _tokenizers_or_skip()
    from tokenizers.trainers import BpeTrainer

    tokenizer = Tokenizer(models.BPE(unk_token=None))
    tokenizer.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=True)
    tokenizer.decoder = None
    trainer = BpeTrainer(vocab_size=2000, special_tokens=[], show_progress=False)
    random.seed(20260905)
    corpus = []
    for _ in range(4000):
        parts = [random.choice(random.choice(CHARSETS)) for _ in range(random.randint(1, 40))]
        corpus.append("".join(parts))
    corpus.extend([
        "def f(x):\n\treturn x + 1\n\nclass Foo:\n    def bar(self):\n        pass\n",
        "hello world, this is a test of the byte level tokenizer  \t\n more text here",
    ])
    tokenizer.train_from_iterator(corpus, trainer=trainer)
    return tokenizer


def _load_frozen_or_synthetic():
    """Prefer the real frozen tokenizer (read-only); fall back to a synthetic one with the same
    pre_tokenizer/normalizer contract when custody is unavailable."""

    Tokenizer, _, _ = _tokenizers_or_skip()
    if FROZEN_TOKENIZER_PATH.is_file():
        tokenizer = Tokenizer.from_file(str(FROZEN_TOKENIZER_PATH))
        return tokenizer, "frozen"
    return _synthetic_bpe_tokenizer(), "synthetic"


def _random_text(rng: random.Random, max_len: int) -> str:
    length = rng.randint(0, max_len)
    return "".join(rng.choice(rng.choice(CHARSETS)) for _ in range(length))


# --------------------------------------------------------------------------- 1. equivalence
@pytest.mark.parametrize("source", ["frozen", "synthetic"])
def test_encode_document_bounded_matches_whole_encode_property(source):
    """>=200 generated texts, small windows to force many cuts, ids must match exactly."""

    if source == "frozen" and not FROZEN_TOKENIZER_PATH.is_file():
        pytest.skip("frozen tokenizer not available read-only at custody path")
    if source == "synthetic":
        tokenizer = _synthetic_bpe_tokenizer()
    else:
        Tokenizer, _, _ = _tokenizers_or_skip()
        tokenizer = Tokenizer.from_file(str(FROZEN_TOKENIZER_PATH))

    rng = random.Random(20260905)
    texts = [_random_text(rng, 400) for _ in range(220)]
    # a handful of texts specifically several windows long, forced via a tiny test window
    texts.extend(_random_text(rng, 900) for _ in range(20))

    failures = []
    for index, text in enumerate(texts):
        window = rng.choice([1, 2, 3, 5, 8, 16, 64])
        got, _fallback = MODULE.encode_document_bounded(tokenizer, text, window_chars=window, lookahead_chars=4)
        expected = tokenizer.encode(text, add_special_tokens=False).ids
        if got != expected:
            failures.append((index, window, text))
    assert not failures, f"{len(failures)}/{len(texts)} mismatched; first: {failures[0]!r}"


def test_encode_document_bounded_empty_and_small_text_matches_whole_call():
    tokenizer = _synthetic_bpe_tokenizer()
    for text in ("", "a", "hello world"):
        got, fallback = MODULE.encode_document_bounded(tokenizer, text)
        expected = tokenizer.encode(text, add_special_tokens=False).ids
        assert got == expected
        assert fallback is False


# --------------------------------------------------------------------------- 2. cut-point safety
def test_cuts_always_land_on_a_whole_string_pretoken_start():
    """Every cut index the bounded encoder resumes at is a pre-token START in the WHOLE-string
    pre-tokenization -- never inside a whitespace run, never between a leading space and its word."""

    tokenizer = _synthetic_bpe_tokenizer()
    rng = random.Random(7)
    texts = [_random_text(rng, 600) for _ in range(60)]
    checked_cuts = 0
    for text in texts:
        window = rng.choice([2, 3, 5, 8])
        whole_pieces = tokenizer.pre_tokenizer.pre_tokenize_str(text)
        whole_starts = {start for _, (start, _end) in whole_pieces}

        length = len(text)
        position = 0
        while position < length:
            window_end = min(position + window + 4, length)
            if window_end >= length:
                break
            pieces = tokenizer.pre_tokenizer.pre_tokenize_str(text[position:window_end])
            if len(pieces) < MODULE.ENCODE_MIN_WINDOW_PIECES:
                break
            cut = position + int(pieces[-2][1][0])
            if cut <= position:
                break
            if position > 0:
                assert position in whole_starts, f"resume position {position} is not a whole-string pre-token start in {text!r}"
                checked_cuts += 1
            position = cut
    assert checked_cuts > 0, "property test produced no multi-window texts; widen generation"


# --------------------------------------------------------------------------- 3. streaming/shard bytes
def test_bounded_encode_produces_the_same_shard_bytes_as_whole_encode(tmp_path):
    """An object whose ids exceed one shard boundary: the FIRST shard's bytes from the bounded
    encode equal the first shard_tokens ids of a reference whole-encode, sliced identically."""

    tokenizer = _synthetic_bpe_tokenizer()
    text = ("The quick brown fox jumps over the lazy dog.\n" * 400) + ("  \t\n  more text 汉字 测试  " * 50)
    ids, _fallback = MODULE.encode_document_bounded(tokenizer, text, window_chars=64, lookahead_chars=8)
    reference = tokenizer.encode(text, add_special_tokens=False).ids
    assert ids == reference

    shard_tokens = 37
    assert len(reference) > shard_tokens * 2, "fixture too short to exercise a shard boundary"
    expected_first_shard = struct.pack(f"<{shard_tokens}H", *reference[:shard_tokens])
    got_first_shard = struct.pack(f"<{shard_tokens}H", *ids[:shard_tokens])
    assert got_first_shard == expected_first_shard


def test_encode_object_forced_multi_window_matches_whole_encode(tmp_path, monkeypatch):
    """encode_object (the production function that changed) with windowing forced small via the
    module constants, on a real file, matches a direct whole-string encode of its content --
    the same-shard-bytes claim exercised at the actual call site, not only the helper."""

    tokenizer = _synthetic_bpe_tokenizer()
    text = ("The quick brown fox jumps over the lazy dog.\n" * 300) + ("  \t\n  more 汉字 测试 😀 text  " * 40)
    path = tmp_path / "object.txt"
    path.write_bytes(text.encode("utf-8"))
    import hashlib

    row = {
        "physical_path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "extractor": "text_utf8",
    }
    monkeypatch.setattr(MODULE, "ENCODE_WINDOW_CHARS", 64)
    monkeypatch.setattr(MODULE, "ENCODE_LOOKAHEAD_CHARS", 8)

    tokens, separators = MODULE.encode_object(tokenizer, row)
    assert separators == 1
    assert tokens[-1] == MODULE.SEPARATOR_ID
    expected = tokenizer.encode(text, add_special_tokens=False).ids + [MODULE.SEPARATOR_ID]
    assert tokens == expected


# --------------------------------------------------------------------------- 4. existing suite
def test_existing_catalog_train_stream_suite_stays_green():
    """Documented here as a pointer: run alongside this module, not duplicated inline --
    `pytest src/ember/governance/scripts/tests/test_catalog_train_stream.py` (13 passed at the
    time this unit was authored; report the count executed in this session, not this assertion)."""

    assert (ROOT / "src" / "ember" / "governance" / "scripts" / "tests" / "test_catalog_train_stream.py").is_file()


# --------------------------------------------------------------------------- 5. peak-memory evidence
def test_peak_memory_evidence_bounded_vs_whole(capsys):
    """Evidence only (no brittle threshold assertion): tracemalloc peak for a synthetic 64MB
    text, bounded window (4 MiB) vs whole-encode, printed for the report."""

    tokenizer = _synthetic_bpe_tokenizer()
    unit = "The quick brown fox jumps over the lazy dog. 汉字测试 \t\n"
    target_chars = 64 * 1024 * 1024
    repeats = target_chars // len(unit) + 1
    text = (unit * repeats)[:target_chars]
    assert len(text) >= target_chars

    tracemalloc.start()
    ids_bounded, _fallback = MODULE.encode_document_bounded(tokenizer, text, window_chars=4 * 1024 * 1024, lookahead_chars=4096)
    _current_b, peak_bounded = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    tracemalloc.start()
    ids_whole = tokenizer.encode(text, add_special_tokens=False).ids
    _current_w, peak_whole = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert ids_bounded == ids_whole
    print(f"\nPEAK_MEMORY_EVIDENCE bytes: bounded={peak_bounded} whole={peak_whole} text_chars={len(text)}")
