"""tokenizer_freeze_selftest.py — fixture-level pins for the fp-22
tokenizer-freeze harness. No network, no GPU, no real corpus access.

Pins:
  1. stratified_budgets: proportional split, small source taken whole,
     pure + deterministic.
  2. sample_source: stride sampling is deterministic (two runs over the
     same fixture shards -> identical sample), respects the budget,
     takes a small source whole.
  3. train_tokenizer: ByteLevel BPE double-train on the same fixture
     sample is byte-identical (the determinism claim in the freeze
     receipt).
  4. Fail-closed wiring: --freeze required; existing freeze receipt
     refuses re-freeze; missing corpus-manifests/ refuses; sample sha +
     strata + tokenizer sha land in the receipt via checked_write.

Run: python scripts/tokenizer_freeze_selftest.py
"""
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import tokenizer_freeze as tf  # noqa: E402
from receipt_write import checked_write  # noqa: E402


def make_fixture_source(root, name, docs):
    """Write a one-shard zstd fixture source + manifest dict."""
    import zstandard
    src_dir = os.path.join(root, name)
    os.makedirs(src_dir, exist_ok=True)
    shard = f"{name}-00000.jsonl.zst"
    raw = "".join(json.dumps({"text": t}) + "\n" for t in docs)
    cctx = zstandard.ZstdCompressor(level=6)
    payload = cctx.compress(raw.encode("utf-8"))
    with open(os.path.join(src_dir, shard), "wb") as f:
        f.write(payload)
    total_bytes = sum(len(t.encode("utf-8")) for t in docs)
    manifest = {
        "source": name,
        "counts": {"text_bytes_kept": total_bytes, "docs_kept": len(docs)},
        "shards": [{"file": shard, "docs": len(docs)}],
    }
    return manifest


def main():
    checks = {}

    # 1. stratified_budgets
    b = tf.stratified_budgets({"a": 800, "b": 150, "c": 50}, 100)
    assert b == {"a": 80, "b": 15, "c": 5}, b
    # small source taken whole when share rounds to 0
    b2 = tf.stratified_budgets({"big": 10_000, "tiny": 3}, 100)
    assert b2["tiny"] == 3 and b2["big"] == 99, b2
    checks["stratified_budgets"] = True

    # 2. sample_source determinism + budget + take-whole
    with tempfile.TemporaryDirectory() as td:
        docs = [f"doc-{i}-" + "x" * 50 for i in range(40)]
        m = make_fixture_source(td, "srcA", docs)
        corpus_dir = os.path.join(td, "srcA")
        t1, seen1, k1 = tf.sample_source(m, corpus_dir, 300)
        t2, seen2, k2 = tf.sample_source(m, corpus_dir, 300)
        assert (t1, seen1, k1) == (t2, seen2, k2), "stride not deterministic"
        assert k1 >= 300 and t1, "budget not reached on ample source"
        assert all(t in docs for t in t1)
        # whole-source when budget >= source bytes
        t3, _, k3 = tf.sample_source(m, corpus_dir,
                                     m["counts"]["text_bytes_kept"] * 2)
        assert len(t3) == len(docs) and k3 == m["counts"]["text_bytes_kept"]
    checks["sample_source_deterministic"] = True

    # 3. double-train byte-identical
    with tempfile.TemporaryDirectory() as td:
        sample = os.path.join(td, "sample.txt")
        with open(sample, "w", encoding="utf-8", newline="\n") as f:
            for i in range(200):
                f.write(f"def f{i}(x): return x + {i}\n<|endoftext|>\n")
        d1 = os.path.join(td, "t1")
        d2 = os.path.join(td, "t2")
        os.makedirs(d1)
        os.makedirs(d2)
        p1 = tf.train_tokenizer(sample, 300, d1)
        p2 = tf.train_tokenizer(sample, 300, d2)
        s1, s2 = tf.file_sha256(p1), tf.file_sha256(p2)
        assert s1 == s2, f"double-train not byte-identical: {s1} != {s2}"
        # the trained artifact actually tokenizes
        from tokenizers import Tokenizer
        tok = Tokenizer.from_file(p1)
        enc = tok.encode("def f0(x): return x + 0")
        assert len(enc.ids) > 0
        # NC2 v0 LOCK #1: the 8-token band sits at ids 0..7 exactly
        band = tf.verify_reserved_band(p1)
        assert band == tf.RESERVED_BAND
        assert band == {t: i for i, t in enumerate(tf.SPECIAL_TOKENS)}
        assert len(tf.SPECIAL_TOKENS) == 8 and \
            tf.SPECIAL_TOKENS[0] == "<|endoftext|>"
        assert set(tf.SPECIAL_TOKENS[1:]) == {
            "<boi>", "<eoi>", "<image_soft>", "<boa>", "<eoa>",
            "<audio_soft>", "<video_soft>"}, "gemma-pattern 7-token band"
        # count_tokens == direct encode sum over the same fixture docs
        docs = [f"def f{i}(x): return x + {i}" for i in range(40)]
        m = make_fixture_source(td, "cnt", docs)
        per = tf.count_tokens(p1, {"cnt": (m, "unused-mirror-path")},
                              td, batch_docs=7, batch_bytes=200)
        want = sum(len(e.ids) for e in tok.encode_batch(docs))
        assert per == {"cnt": want}, (per, want)
    checks["double_train_byte_identical"] = True
    checks["reserved_band_fixed_ids"] = True
    checks["count_tokens_exact"] = True

    # 3a. re-freeze refusal matches PRODUCTION receipts only — selftest
    # receipts share the filename prefix and must not trip it
    with tempfile.TemporaryDirectory() as td:
        rdir = os.path.join(td, "receipts")
        os.makedirs(rdir)
        open(os.path.join(
            rdir, "tokenizer-freeze-selftest-20260611T000000Z.json"),
            "w").close()
        assert tf.existing_freeze_receipts(td) == [], \
            "selftest receipt must not trip the re-freeze refusal"
        prod = os.path.join(rdir, "tokenizer-freeze-20260611T000000Z.json")
        open(prod, "w").close()
        assert [os.path.basename(p)
                for p in tf.existing_freeze_receipts(td)] == \
            ["tokenizer-freeze-20260611T000000Z.json"]
    checks["refreeze_refusal_scoped_to_production"] = True

    # 3b. assembly-sha pin behavior (eng #160 AC-1, Kai 14560)
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "receipts"))
        try:
            tf.pinned_assembly_receipt(td)
            raise AssertionError("absent assembly receipt must refuse")
        except SystemExit as e:
            assert "absent" in str(e)
        p = os.path.join(td, "receipts", tf.ASSEMBLY_RECEIPT_BASENAME)
        with open(p, "wb") as f:
            f.write(b'{"tampered": true}')
        try:
            tf.pinned_assembly_receipt(td)
            raise AssertionError("drifted assembly receipt must refuse")
        except SystemExit as e:
            assert "sha" in str(e) and "mismatch" in str(e)
    checks["assembly_pin_fail_closed"] = True

    # 4. fail-closed wiring (source asserts — behavior pinned above)
    src = open(os.path.join(HERE, "tokenizer_freeze.py"),
               encoding="utf-8").read()
    assert 'if not args.freeze:' in src and '"--freeze"' in src
    assert "freeze receipt already exists" in src
    assert "no corpus-manifests/ mirrors" in src
    assert "pinned_assembly_receipt(repo)" in src, \
        "build_sample must consume the PINNED assembly receipt"
    assert "latest_assembly_receipt" not in src, \
        "the latest-glob assembly lookup must be gone (pin-only)"
    assert '"sample_sha256": sample_sha' in src
    assert '"tokenizer_json_sha256": tok_sha' in src
    assert '"strata": strata' in src
    assert '"reserved_band": band' in src
    assert '"assembly_receipt_sha256": ASSEMBLY_RECEIPT_SHA256' in src
    assert '"tokens_pending_tokenizer_freeze": False' in src
    assert '"real_token_counts"' in src and '"resolves_heuristic"' in src
    assert '"sha_convention": SHA_CONVENTION' in src
    assert "checked_write(out, receipt)" in src
    assert tf.VOCAB_SIZE == 32_000, "fp-19 pin: vocab 32k"
    assert len(tf.ASSEMBLY_RECEIPT_SHA256) == 64
    main_src = src.split("def main():")[1]
    pos_prior = main_src.index("existing_freeze_receipts")
    pos_sample = main_src.index("build_sample")
    assert pos_prior < pos_sample, \
        "re-freeze refusal must precede any sampling work"
    # band verification + token counting happen BEFORE the receipt write
    pos_band = main_src.index("verify_reserved_band")
    pos_count = main_src.index("count_tokens")
    pos_write = main_src.index("checked_write(out, receipt)")
    assert pos_band < pos_write and pos_count < pos_write
    checks["fail_closed_wiring"] = True

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "TOKENIZER-FREEZE-SELFTEST", "ts": ts,
        "checks": checks,
        "sha_convention": tf.SHA_CONVENTION,
        "note": ("harness prep for the fp-22 tokenizer leg (launch order: "
                 "eng-36 gate -> tokenizer freeze); the PRODUCTION freeze "
                 "runs only after the corpus gate, via --freeze"),
        "no_network": True, "no_gpu": True,
    }
    out = os.path.join(REPO, "receipts",
                       f"tokenizer-freeze-selftest-{ts}.json")
    checked_write(out, receipt)
    print(json.dumps(receipt, indent=2))
    print(f"[selftest] receipt: {out}")
    print("TOKENIZER_FREEZE_SELFTEST_PASS")


if __name__ == "__main__":
    main()
