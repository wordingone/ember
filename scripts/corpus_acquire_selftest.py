"""corpus_acquire_selftest.py — eng-36 (#130) acquisition harness receipt.

Pure logic + source-wiring asserts; NO network, NO GPU. Exercises the
ingest core (dedup / fail-closed license filter / budget stop / empty
skip), the shard writer round-trip (zstd write -> decompress -> line
count + sha), and the registry invariants (budgets under the disk bars,
license stamps complete, substitution source gated behind ack).

Writes receipts/eng36-acquire-selftest-<ts>.json. Sentinel:
ENG36_ACQUIRE_SELFTEST_PASS.
"""
import hashlib
import io
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import corpus_acquire as ca  # noqa: E402


def main():
    checks = {}

    # 1. registry invariants
    total_budget = sum(s["byte_budget"] for s in ca.SOURCES.values())
    assert total_budget < 30_000_000_000, \
        f"budgets exceed the ~30GB raw target: {total_budget}"
    assert total_budget < 100_000_000_000, "budgets exceed the HARD bar"
    for name, spec in ca.SOURCES.items():
        assert spec["license_class"] and spec["license_basis"], \
            f"{name}: license stamp incomplete"
        assert spec["fp22_row"] in (1, 2, 3, 4, 5), f"{name}: fp22 row"
        if spec.get("license_field"):
            allow = spec["license_allow"]
            assert allow and "UNKNOWN" not in allow, \
                f"{name}: UNKNOWN must never be allowable"
    assert ca.SOURCES["code_github_clean"].get("requires_ack") is True, \
        "substitution source must be gated behind --ack-code-source"
    fp22_rows = sorted(s["fp22_row"] for s in ca.SOURCES.values())
    assert fp22_rows == [1, 2, 3, 4, 5], "fp-22 §1 coverage incomplete"
    checks["registry"] = True

    # 2. ingest core: dedup + license fail-closed + budget stop + empty
    class ListWriter:
        def __init__(self):
            self.docs = []

        def write_doc(self, obj):
            self.docs.append(obj)

    recs = [
        {"code": "print(1)", "license": "mit"},
        {"code": "print(1)", "license": "mit"},          # exact dup
        {"code": "print(2)", "license": "gpl-3.0"},      # copyleft -> reject
        {"code": "print(3)", "license": None},           # missing -> reject
        {"code": "print(4)"},                            # absent -> reject
        {"code": "", "license": "mit"},                  # empty -> skip
        {"code": "print(5)", "license": "apache-2.0"},
        {"code": "print(6)", "license": "mit"},          # past budget
    ]
    w = ListWriter()
    counts = ca.ingest_stream(
        iter(recs), text_field="code", byte_budget=16, writer=w,
        license_field="license", license_allow=ca.PERMISSIVE_CODE)
    assert counts["docs_in"] == 7, counts          # budget stops before #8
    assert counts["docs_kept"] == 2, counts        # print(1), print(5)
    assert counts["dups_dropped"] == 1, counts
    assert counts["license_rejected"] == 3, counts
    assert counts["empty_skipped"] == 1, counts
    assert counts["text_bytes_kept"] == 16, counts
    assert [d["text"] for d in w.docs] == ["print(1)", "print(5)"]
    assert all(d["license"] in ca.PERMISSIVE_CODE for d in w.docs)
    for c, v in counts.items():
        assert isinstance(v, int), f"count {c} must be int (receipt rule)"
    checks["ingest_core"] = True

    # 2b. license_field without allow-list is fail-open -> refuse
    try:
        ca.ingest_stream(iter([]), text_field="code", byte_budget=1,
                         writer=ListWriter(), license_field="license",
                         license_allow=None)
        raise AssertionError("fail-open license filter must refuse")
    except SystemExit:
        pass
    checks["license_failclosed"] = True

    # 3. shard writer round-trip (zstd) + rotation + sha
    import zstandard
    with tempfile.TemporaryDirectory() as td:
        sw = ca.ShardWriter(td, "t", shard_bytes=40)
        for i in range(6):
            sw.write_doc({"text": f"doc-{i}"})
        shards = sw.close()
        assert len(shards) >= 2, "rotation by uncompressed bytes failed"
        got = []
        total_docs = 0
        for s in shards:
            p = os.path.join(td, s["file"])
            assert ca.file_sha256(p) == s["sha256"], "shard sha mismatch"
            dctx = zstandard.ZstdDecompressor()
            with open(p, "rb") as f:
                data = dctx.stream_reader(f).read()
            lines = [ln for ln in data.decode("utf-8").splitlines() if ln]
            assert len(lines) == s["docs"], "doc count mismatch"
            total_docs += s["docs"]
            got += [json.loads(ln)["text"] for ln in lines]
        assert total_docs == 6 and got == [f"doc-{i}" for i in range(6)]
    checks["shard_writer_roundtrip"] = True

    # 4. file_sha256 matches hashlib over raw bytes
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "b.bin")
        with open(p, "wb") as f:
            f.write(b"abc\r\nxyz\n")
        assert ca.file_sha256(p) == hashlib.sha256(b"abc\r\nxyz\n").hexdigest()
    checks["file_sha256"] = True

    # 5. source wiring: receipts via checked_write; manifests carry the
    # pending-tokenizer flag + heuristic label; ack gate wired in main()
    src = open(os.path.join(HERE, "corpus_acquire.py"),
               encoding="utf-8").read()
    assert "from receipt_write import checked_write" in src
    assert "checked_write(receipt_path, receipt)" in src
    assert '"tokens_pending_tokenizer_freeze": True' in src
    assert "HEURISTIC ONLY" in src, "token estimate must be labeled non-AC"
    assert "requires_ack" in src and "--ack-code-source" in src
    assert '"sha_convention": SHA_CONVENTION' in src
    assert "effective_class(rec) == \"arc-dsl-mit\"" in src, \
        "ledger slice must classify via the fp-6 single source"
    # parquet-direct load path (mail 14542): same dataset, same pinned
    # revision — the @revision must be inside the hf:// data_files URL
    # (load-bearing pin), and the registry must route the code source
    # through it since its legacy script loader is unsupported.
    assert ca.SOURCES["code_github_clean"].get("parquet_glob") == \
        "data/train-*.parquet"
    assert "hf://datasets/{spec['dataset']}@{revision}/" in src, \
        "revision pin must be load-bearing in the parquet-direct URL"
    assert 'url_pin["load_path"]' in src, \
        "manifest must record the parquet-direct load path"
    checks["source_wiring"] = True

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "ENG36-ACQUIRE-SELFTEST", "ts": ts,
        "issue": "wordingone/ember#130",
        "checks": checks,
        "sha_convention": ca.SHA_CONVENTION,
        "substitution_note": ("code_github_clean is a source substitution "
                              "vs the issue text (the-stack-v2 references-"
                              "only; march sample lacks per-file license "
                              "metadata) — runner refuses it without "
                              "--ack-code-source until the gate-holder "
                              "acks"),
        "no_network": True,
        "no_gpu": True,
    }
    out = os.path.join(REPO, "receipts", f"eng36-acquire-selftest-{ts}.json")
    from receipt_write import checked_write
    checked_write(out, receipt)
    print(json.dumps(receipt, indent=2))
    print(f"[selftest] receipt: {out}")
    print("ENG36_ACQUIRE_SELFTEST_PASS")


if __name__ == "__main__":
    main()
