"""corpus_mix_selftest.py — eng-44 (#168) fixture-level pins for the
CORPUS-MIX-V0 harness. No network, no GPU, no real corpus.

Pins:
  1. length_stats: exact n/sum/mean/median/p95 over a known histogram.
  2. packing_waste: exact ceil-model waste at seq 1024 on known cases.
  3. band_regex: detects every one of the 7 reserved strings.
  4. scan_source CLEAN: a band-free fixture source -> 0 string hits, 0 sample
     id-band hits; the sample histogram == direct encode lengths; n_docs exact.
  5. scan_source PLANTED: a doc carrying "<boi>" -> string hit AND (encoded)
     sample id-band hit (the equivalence the corpus-side check relies on).
  6. Fail-closed wiring (source asserts): freeze+assembly+tokenizer pins,
     band fail-closed, sha_convention, receipt via checked_write.

Run: python scripts/corpus_mix_selftest.py
"""
import json
import os
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import corpus_mix as cm  # noqa: E402
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
    with open(os.path.join(src_dir, shard), "wb") as f:
        f.write(cctx.compress(raw.encode("utf-8")))
    total_bytes = sum(len(t.encode("utf-8")) for t in docs)
    manifest = {
        "source": name,
        "counts": {"text_bytes_kept": total_bytes, "docs_kept": len(docs)},
        "shards": [{"file": shard, "docs": len(docs)}],
    }
    return manifest


def main():
    checks = {}

    # 1. length_stats over a known histogram
    st = cm.length_stats(Counter({10: 3, 20: 1}))
    assert st == {"n_docs": 4, "sum_tokens": 50, "mean": 12.5,
                  "median": 10, "p95": 20}, st
    assert cm.length_stats(Counter())["n_docs"] == 0
    checks["length_stats_exact"] = True

    # 2. packing_waste ceil-model at seq 1024
    assert cm.packing_waste(Counter({1024: 1}), 1024) == 0.0      # exact fit
    assert cm.packing_waste(Counter({512: 1}), 1024) == 0.5       # half wasted
    assert cm.packing_waste(Counter({1536: 1}), 1024) == 0.25     # 2 windows
    checks["packing_waste_math"] = True

    # 3. band_regex detects every reserved string
    br = cm.band_regex()
    assert cm.BAND_IDS == [1, 2, 3, 4, 5, 6, 7]
    assert cm.BAND_STRINGS == tf.SPECIAL_TOKENS[1:8]
    for s in cm.BAND_STRINGS:
        assert br.search(f"prefix {s} suffix"), s
    assert not br.search("plain text without any reserved marker")
    checks["band_regex_detects_all"] = True

    with tempfile.TemporaryDirectory() as td:
        # a tiny frozen-style tokenizer (special band at ids 0..7)
        sample = os.path.join(td, "sample.txt")
        with open(sample, "w", encoding="utf-8", newline="\n") as f:
            for i in range(200):
                f.write(f"def f{i}(x): return x + {i}\n<|endoftext|>\n")
        tdir = os.path.join(td, "tok")
        os.makedirs(tdir)
        tok_path = tf.train_tokenizer(sample, 320, tdir)
        from tokenizers import Tokenizer
        tok = Tokenizer.from_file(tok_path)
        assert tok.token_to_id("<boi>") == 1  # band id present in the fixture

        # 4. scan_source CLEAN
        clean_docs = [f"def f{i}(x): return x + {i}" for i in range(20)]
        m = make_fixture_source(td, "clean", clean_docs)
        res = cm.scan_source(m, os.path.join(td, "clean"), tok, br,
                             sample_k=1, sample_budget_bytes=10_000_000)
        assert res["n_docs"] == 20 and res["sample_docs"] == 20
        assert res["band_string_hits"] == 0
        assert res["sample_id_band_hits"] == 0
        assert sum(res["sample_hist"].values()) == 20
        # histogram == direct encode lengths
        want = Counter(len(e.ids) for e in tok.encode_batch(clean_docs))
        assert res["sample_hist"] == want, (res["sample_hist"], want)
        checks["scan_source_clean"] = True

        # 5. scan_source PLANTED — a reserved string occurs
        planted = clean_docs + ["use the <boi> marker here"]
        m2 = make_fixture_source(td, "planted", planted)
        res2 = cm.scan_source(m2, os.path.join(td, "planted"), tok, br,
                              sample_k=1, sample_budget_bytes=10_000_000)
        assert res2["band_string_hits"] >= 1, "string scan missed <boi>"
        assert res2["sample_id_band_hits"] >= 1, "encode missed band id 1"
        checks["scan_source_planted_detected"] = True

    # 6. fail-closed wiring (source asserts)
    src = open(os.path.join(HERE, "corpus_mix.py"), encoding="utf-8").read()
    assert len(cm.FREEZE_RECEIPT_SHA256) == 64
    assert "def pinned_freeze_receipt" in src
    assert "tf.pinned_assembly_receipt(repo)" in src, \
        "must reuse the eng-36 assembly-sha gate"
    assert 'freeze["tokenizer_json_sha256"]' in src, \
        "tokenizer.json sha must be checked against the freeze receipt"
    assert "RESERVED BAND VIOLATION" in src
    assert ("if total_string_hits != 0 or total_sample_id_hits != 0:"
            in src), "band check must be fail-closed"
    assert '"sha_convention": SHA_CONVENTION' in src
    assert 'checked_write(out, receipt)' in src
    assert 'if not args.mix_stats:' in src and '"--mix-stats"' in src
    # band scan is FULL (every doc), sampling only gates the encode
    build_src = src.split("def scan_source")[1].split("def build_mix")[0]
    assert "if band_re.search(text):" in build_src
    pos_search = build_src.index("band_re.search(text)")
    pos_sample = build_src.index("n_docs % sample_k")
    assert pos_search < pos_sample, "band scan must run on every doc"
    checks["fail_closed_wiring"] = True

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "CORPUS-MIX-SELFTEST",
        "ts": ts,
        "issue": "wordingone/ember#168",
        "checks": checks,
        "sha_convention": tf.SHA_CONVENTION,
        "note": ("fixture-level harness pins; the PRODUCTION mix run "
                 "(--mix-stats) runs over the merged v0 corpus against the "
                 "frozen tokenizer"),
        "no_network": True,
        "no_gpu": True,
    }
    out = os.path.join(REPO, "receipts", f"corpus-mix-selftest-{ts}.json")
    checked_write(out, receipt)
    print(json.dumps(receipt, indent=2))
    print(f"[selftest] receipt: {out}")
    print("CORPUS_MIX_SELFTEST_PASS")


if __name__ == "__main__":
    main()
