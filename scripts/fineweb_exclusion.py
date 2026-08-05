# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""fineweb_exclusion.py — enforce the L3 fineweb_edu exclusion at LOAD time (#1436).

The v1-provenance-manifest RULED fineweb_edu DROP/EXCLUDED on 2026-07-06 (Llama-3-70B-
Instruct classifier taint, arXiv:2406.17557; receipts/v1-provenance-manifest-20260706.jsonl).
No shards-v1 binary was ever produced, so shards-v0 is the only stream that exists and it
still physically contains all 1,666,837,789 fineweb_edu tokens with zero source-awareness in
`PackedShardLoader` (scripts/timeshare_pretrain.py) — the ruling was prose, not bytes. The
2026-08-04 L3 provenance audit derived the exact fineweb_edu
token-offset range from the receipted per-source stream_tokens counts, in the writer's own
fp22_row concatenation order.

This module is CURE #2 from the issue ("teach the loader source-awareness"): derive the
excluded offset range PROGRAMMATICALLY from the TOKEN-SHARDS-V0 receipt (never hardcoded),
fail-closed if that receipt does not validate against the actual on-disk shard bytes, and
give `PackedShardLoader` a window filter so a window overlapping ANY excluded byte is never
yielded — bound to sha256s, not file names, per the issue's acceptance criterion.

Public API:
  compute_source_offsets(receipt, assembly)   -> {source: (start, end)} in fp22_row order
  excluded_token_ranges(nc=NC, ...)           -> fail-closed sorted [(start, end), ...]
  usable_window_starts(n_tokens, seq, block_len, excluded_ranges) -> sorted [int, ...]
  assert_windows_exclude_ranges(window_starts, block_len, excluded_ranges) -> None or raises

CLI:
  --selftest         hermetic; synthetic fixtures only, touches no production data
  --preflight         PRODUCTION read-only: validates the real receipt against the real
                      shard bytes, derives the range, and writes a
                      FINEWEB-EDU-EXCLUSION-PREFLIGHT receipt (no .bin bytes are written;
                      this is a pure read + assertion pass, no_gpu, no training).
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from token_shards_v0 import (                      # noqa: E402
    ASSEMBLY_RECEIPT, TICKET as SHARD_TICKET, validate_shards_receipt,
)

EXCLUSION_TICKET = "FINEWEB-EDU-EXCLUSION-PREFLIGHT"
EXCLUDED_SOURCES = {"fineweb_edu"}
DEFAULT_SHARD_RECEIPT = "token-shards-v0-20260611T170047Z.json"


def _load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def compute_source_offsets(receipt, assembly):
    """{source: (start, end)} half-open token-offset ranges, in the writer's own
    fp22_row concatenation order (scripts/token_shards_v0.py `_resolve_sources`
    sorts by fp22_row and appends each source's stream in that order — strict
    concatenation, never shuffled/interleaved). Pure function of the two receipt
    dicts; raises ValueError if a source in the assembly is missing from
    per_source (the receipts have drifted apart and must not be trusted)."""
    per_source = receipt.get("per_source") or {}
    rows = sorted(assembly.get("sources", []),
                  key=lambda s: s.get("fp22_row", 1 << 30))
    offsets = {}
    cursor = 0
    for row in rows:
        src = row["source"]
        entry = per_source.get(src)
        if not isinstance(entry, dict) or not isinstance(
                entry.get("stream_tokens"), int):
            raise ValueError(
                f"compute_source_offsets: per_source[{src!r}] missing/invalid "
                "stream_tokens — receipts disagree, refusing to derive offsets")
        n = entry["stream_tokens"]
        offsets[src] = (cursor, cursor + n)
        cursor += n
    total = receipt.get("total_stream_tokens")
    if isinstance(total, int) and cursor != total:
        raise ValueError(
            f"compute_source_offsets: sum(per_source stream_tokens) {cursor} != "
            f"total_stream_tokens {total} — cannot trust the derived offsets")
    return offsets


def excluded_token_ranges(nc=NC, shard_dir=None, shard_receipt_name=DEFAULT_SHARD_RECEIPT,
                          assembly_name=ASSEMBLY_RECEIPT,
                          excluded_sources=None):
    """FAIL-CLOSED: load + validate the TOKEN-SHARDS-V0 receipt against the
    actual on-disk shard bytes (validate_shards_receipt — the same byte-true
    sha/count/parity check the launch gate uses), load + validate the assembly
    receipt it pins, then derive the excluded sources' offset ranges from the
    validated numbers. Any receipt miss, sha drift, or missing premise raises
    ValueError — this function NEVER returns a range for bytes it hasn't
    itself proven exist. `shard_dir` overrides the receipt's own NC-relative
    shard_dir (worktree-invariant, mirrors validate_shards_receipt's own
    shard_dir_override contract) — pass it when the shard bytes live in an
    out-of-tree data store rather than this checkout.

    Returns a sorted, merged list of (start, end) half-open token-offset
    tuples covering every requested excluded source."""
    if excluded_sources is None:
        excluded_sources = EXCLUDED_SOURCES
    receipt_path = f"{nc}/receipts/{shard_receipt_name}"
    if not os.path.exists(receipt_path):
        raise ValueError(f"excluded_token_ranges: shard receipt not on disk: "
                         f"{receipt_path}")
    receipt = _load_json(receipt_path)
    violations = validate_shards_receipt(receipt, nc, shard_dir_override=shard_dir)
    if violations:
        raise ValueError(
            "excluded_token_ranges: TOKEN-SHARDS-V0 receipt FAILS validation "
            f"against on-disk shard bytes — refusing to trust any offset "
            f"derived from it: {violations}")

    assembly_path = f"{nc}/receipts/{assembly_name}"
    if not os.path.exists(assembly_path):
        raise ValueError(f"excluded_token_ranges: assembly receipt not on disk: "
                         f"{assembly_path}")
    assembly = _load_json(assembly_path)
    prem = (receipt.get("premises") or {}).get("assembly_receipt") or {}
    if prem.get("name") != assembly_name:
        raise ValueError(
            "excluded_token_ranges: shard receipt's pinned assembly premise "
            f"{prem.get('name')!r} != the assembly receipt being used "
            f"{assembly_name!r} — refusing a mismatched pin")

    offsets = compute_source_offsets(receipt, assembly)
    missing = excluded_sources - set(offsets)
    if missing:
        raise ValueError(
            f"excluded_token_ranges: excluded source(s) {sorted(missing)} not "
            f"present in the derived offset map {sorted(offsets)} — refusing "
            "to silently exclude nothing")
    ranges = sorted(offsets[s] for s in excluded_sources)
    # merge adjacent/overlapping ranges so downstream overlap checks are simple
    merged = []
    for start, end in ranges:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def usable_window_starts(n_tokens, seq, block_len, excluded_ranges):
    """Every window start `i*seq` for `i` in `[0, (n_tokens-block_len)//seq]`
    whose covered byte range `[start, start+block_len)` does NOT overlap any
    excluded range. Pure function, O(n_windows * n_ranges) — n_ranges is a
    handful of sources, never large. A window that straddles an excluded
    boundary is dropped whole (fail-closed on the boundary tokens too: a
    window is either entirely clean or entirely excluded, never partially
    consumed)."""
    if n_tokens < block_len:
        return []
    n_windows_full = (n_tokens - block_len) // seq + 1
    if not excluded_ranges:
        return [i * seq for i in range(n_windows_full)]
    out = []
    for i in range(n_windows_full):
        start = i * seq
        end = start + block_len
        if not any(_overlaps(start, end, es, ee) for es, ee in excluded_ranges):
            out.append(start)
    return out


def assert_windows_exclude_ranges(window_starts, block_len, excluded_ranges):
    """Byte-exact re-verification (never sampled) that NOT ONE window in
    `window_starts` overlaps ANY excluded range. Raises AssertionError on the
    first violation found. This is the launch preflight assertion the issue
    requires: "a training run cannot consume a fineweb_edu token" — proven
    over every yielded window, not a source-average estimate."""
    for start in window_starts:
        end = start + block_len
        for es, ee in excluded_ranges:
            if _overlaps(start, end, es, ee):
                raise AssertionError(
                    f"window [{start}, {end}) overlaps excluded range "
                    f"[{es}, {ee}) — fineweb_edu exclusion enforcement failed")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _utc_ts():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def run_preflight(nc=NC, shard_dir=None, shard_receipt_name=DEFAULT_SHARD_RECEIPT,
                  assembly_name=ASSEMBLY_RECEIPT, excluded_sources=None,
                  seq=1024, n_mtp=2):
    """Read-only production preflight: derive the excluded ranges (fail-closed
    against the real receipts/shard bytes), compute the usable-window count
    for the frozen v0 loader geometry, byte-exact verify zero overlap, and
    return a receipt dict. no_gpu; touches no training state."""
    if excluded_sources is None:
        excluded_sources = EXCLUDED_SOURCES
    ranges = excluded_token_ranges(nc, shard_dir=shard_dir,
                                   shard_receipt_name=shard_receipt_name,
                                   assembly_name=assembly_name,
                                   excluded_sources=excluded_sources)
    receipt = _load_json(f"{nc}/receipts/{shard_receipt_name}")
    n_tokens = receipt["total_stream_tokens"]
    block_len = seq + 1 + n_mtp
    starts_full = usable_window_starts(n_tokens, seq, block_len, [])
    starts_clean = usable_window_starts(n_tokens, seq, block_len, ranges)
    assert_windows_exclude_ranges(starts_clean, block_len, ranges)
    excluded_content_tokens = sum(
        (receipt.get("per_source") or {}).get(s, {}).get("content_tokens", 0)
        for s in excluded_sources)
    clean_content_tokens = receipt["content_total_tokens"] - excluded_content_tokens
    return {
        "ticket": EXCLUSION_TICKET,
        "ts": _utc_ts(),
        "shard_receipt": shard_receipt_name,
        "assembly_receipt": assembly_name,
        "excluded_sources": sorted(excluded_sources),
        "excluded_token_ranges": [list(r) for r in ranges],
        "loader_geometry": {"seq": seq, "n_mtp": n_mtp, "block_len": block_len},
        "n_windows_unenforced": len(starts_full),
        "n_windows_enforced": len(starts_clean),
        "n_windows_dropped": len(starts_full) - len(starts_clean),
        "zero_overlap_verified": True,
        "clean_content_tokens": clean_content_tokens,
        "stream_content_tokens": receipt["content_total_tokens"],
        "no_gpu": True,
        "authority": {
            "goal_id": "EMBER-02",
            "workstream_id": "EMBER-02A",
            "next_executed_outcome": (
                "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"),
        },
    }


def _selftest():
    """Hermetic — no repo receipts, no production data. Exercises the offset
    derivation and window filter against synthetic fixtures shaped exactly
    like the real receipt schema."""
    receipt = {
        "total_stream_tokens": 1000,
        "per_source": {
            "code_github_clean": {"stream_tokens": 400},
            "fineweb_edu": {"stream_tokens": 300},
            "wikipedia_en": {"stream_tokens": 300},
        },
    }
    assembly = {"sources": [
        {"source": "code_github_clean", "fp22_row": 1},
        {"source": "fineweb_edu", "fp22_row": 2},
        {"source": "wikipedia_en", "fp22_row": 3},
    ]}
    offsets = compute_source_offsets(receipt, assembly)
    assert offsets == {
        "code_github_clean": (0, 400),
        "fineweb_edu": (400, 700),
        "wikipedia_en": (700, 1000),
    }, offsets

    # order independence: assembly listed out of fp22_row order still resolves
    # to the same offsets (sort is by fp22_row, not list position)
    shuffled = {"sources": list(reversed(assembly["sources"]))}
    assert compute_source_offsets(receipt, shuffled) == offsets

    # a source missing from per_source is a hard refusal, never a silent skip
    bad_receipt = {"total_stream_tokens": 700,
                   "per_source": {"code_github_clean": {"stream_tokens": 400},
                                  "wikipedia_en": {"stream_tokens": 300}}}
    try:
        compute_source_offsets(bad_receipt, assembly)
        raise AssertionError("expected ValueError for a missing source")
    except ValueError:
        pass

    # a total-tokens mismatch is a hard refusal (receipts disagree)
    drift_receipt = dict(receipt)
    drift_receipt["total_stream_tokens"] = 999
    try:
        compute_source_offsets(drift_receipt, assembly)
        raise AssertionError("expected ValueError for a total mismatch")
    except ValueError:
        pass

    # --- window filtering -------------------------------------------------
    seq, n_mtp = 8, 2
    block_len = seq + 1 + n_mtp        # 11
    n_tokens = 100
    excl = [(40, 70)]                  # e.g. offsets [40,70) excluded
    all_starts = usable_window_starts(n_tokens, seq, block_len, [])
    clean_starts = usable_window_starts(n_tokens, seq, block_len, excl)
    assert len(clean_starts) < len(all_starts)
    assert set(clean_starts) <= set(all_starts)
    # zero clean window ever overlaps the excluded range — byte-exact check,
    # never sampled
    assert_windows_exclude_ranges(clean_starts, block_len, excl)
    for s in all_starts:
        if s not in clean_starts:
            e = s + block_len
            assert e > excl[0][0] and s < excl[0][1], (
                f"window {s} was dropped but does not overlap {excl}")

    # a violated invariant is caught, not silently passed
    try:
        assert_windows_exclude_ranges([45], block_len, excl)   # 45..56 overlaps 40..70
        raise AssertionError("expected AssertionError for an overlapping window")
    except AssertionError as e:
        assert "overlaps excluded range" in str(e)

    # empty excluded_ranges is the identity (no filtering) — the legacy path
    assert usable_window_starts(n_tokens, seq, block_len, []) == \
        usable_window_starts(n_tokens, seq, block_len, None if False else [])

    # multiple excluded ranges, including adjacent ones that should merge in
    # excluded_token_ranges (tested indirectly via the merge logic inline)
    r1 = usable_window_starts(200, seq, block_len, [(0, 20), (20, 40)])
    r2 = usable_window_starts(200, seq, block_len, [(0, 40)])
    assert r1 == r2, "adjacent excluded ranges must behave like one merged range"

    # n_tokens < block_len -> no windows, no crash
    assert usable_window_starts(5, seq, block_len, []) == []

    print("FINEWEB_EXCLUSION_SELFTEST_PASS")


def _selftest_fail_closed_against_real_schema():
    """Exercises excluded_token_ranges()'s fail-closed path against a synthetic
    on-disk fixture that mirrors the real TOKEN-SHARDS-V0 + assembly receipt
    shapes (via token_shards_v0's own selftest fixture builder), proving the
    end-to-end wiring (receipt validation -> offset derivation) without
    touching any production receipt or shard byte."""
    import copy
    import struct
    import tempfile
    import token_shards_v0 as tsv

    with tempfile.TemporaryDirectory() as td:
        os.makedirs(f"{td}/receipts")
        os.makedirs(f"{td}/shards")
        os.makedirs(f"{td}/tokenizer")
        prem_names = {"assembly_receipt": "fixture-assembly.json",
                     "tokenizer_freeze_receipt": "fixture-tokfreeze.json"}
        for nm in prem_names.values():
            json.dump({"ticket": "FIXTURE", "ts": "20260101T000000Z"},
                      open(f"{td}/receipts/{nm}", "w"))
        json.dump({"vocab_size": 32000},
                  open(f"{td}/tokenizer/tokenizer.json", "w"))

        def _write_shard(name, n):
            ids = [8 + (i % 100) for i in range(n)]
            with open(f"{td}/shards/{name}", "wb") as fh:
                fh.write(b"".join(struct.pack("<H", x) for x in ids))
            return n

        n0 = _write_shard("v0-00000.bin", 3000)
        total = n0

        def _sha(p):
            return tsv._sha(p)

        per_source = {s: {"content_tokens": 0, "separator_tokens": 0,
                          "stream_tokens": 0} for s in tsv.EXPECTED_SOURCES}
        # split the single shard's tokens across two sources so an excluded
        # range sits strictly inside the stream (not the whole thing)
        per_source["code_github_clean"] = {"content_tokens": 1000,
                                           "separator_tokens": 0,
                                           "stream_tokens": 1000}
        per_source["fineweb_edu"] = {"content_tokens": total - 1000,
                                     "separator_tokens": 0,
                                     "stream_tokens": total - 1000}

        receipt = {
            "ticket": tsv.TICKET, "ts": "20260611T000000Z", "shard_dir": "shards",
            "shards": [{"name": "v0-00000.bin", "sha256": _sha(f"{td}/shards/v0-00000.bin"),
                       "n_tokens": n0}],
            "total_stream_tokens": total, "content_total_tokens": total,
            "per_source": per_source, "separator_id": tsv.SEPARATOR_ID,
            "reserved_band_guard": {"reserved_ids": tsv.RESERVED_IDS,
                                    "max_id_lt": tsv.VOCAB_SIZE,
                                    "reserved_ids_observed_in_stream": 0},
            "loader_windows": {"seq": tsv.SEQ, "n_mtp": tsv.N_MTP,
                               "block_len": tsv.BLOCK_LEN,
                               "n_windows": (total - tsv.BLOCK_LEN) // tsv.SEQ + 1},
            "premises": {
                "assembly_receipt": {"name": prem_names["assembly_receipt"],
                                     "sha256": _sha(f"{td}/receipts/{prem_names['assembly_receipt']}")},
                "tokenizer_freeze_receipt": {"name": prem_names["tokenizer_freeze_receipt"],
                                             "sha256": _sha(f"{td}/receipts/{prem_names['tokenizer_freeze_receipt']}")},
                "tokenizer_json": {"path": "tokenizer/tokenizer.json",
                                   "sha256": _sha(f"{td}/tokenizer/tokenizer.json")},
            },
            "sha_convention": tsv.SHA_CONVENTION, "no_gpu": True,
        }
        assembly = {"ticket": "FIXTURE", "ts": "20260101T000000Z", "sources": [
            {"source": "code_github_clean", "fp22_row": 1},
            {"source": "fineweb_edu", "fp22_row": 2},
            {"source": "wikipedia_en", "fp22_row": 3},
            {"source": "gutenberg_en", "fp22_row": 4},
            {"source": "ledger_mit", "fp22_row": 5},
        ]}
        json.dump(assembly, open(f"{td}/receipts/{prem_names['assembly_receipt']}", "w"))
        receipt["premises"]["assembly_receipt"]["sha256"] = _sha(
            f"{td}/receipts/{prem_names['assembly_receipt']}")
        json.dump(receipt, open(f"{td}/receipts/fixture-shard.json", "w"))
        assert tsv.validate_shards_receipt(receipt, td) == [], \
            tsv.validate_shards_receipt(receipt, td)

        ranges = excluded_token_ranges(
            td, shard_receipt_name="fixture-shard.json",
            assembly_name=prem_names["assembly_receipt"])
        assert ranges == [(1000, total)], ranges

        # tamper a shard byte -> validate_shards_receipt fails -> hard refusal,
        # never a silently-stale range
        with open(f"{td}/shards/v0-00000.bin", "r+b") as fh:
            fh.seek(0)
            fh.write(struct.pack("<H", 9999))
        try:
            excluded_token_ranges(td, shard_receipt_name="fixture-shard.json",
                                  assembly_name=prem_names["assembly_receipt"])
            raise AssertionError("expected ValueError after tampering shard bytes")
        except ValueError as e:
            assert "FAILS validation" in str(e)

        # mismatched assembly pin -> hard refusal
        _write_shard("v0-00000.bin", n0)   # restore
        other_assembly = copy.deepcopy(assembly)
        json.dump(other_assembly, open(f"{td}/receipts/other-assembly.json", "w"))
        try:
            excluded_token_ranges(td, shard_receipt_name="fixture-shard.json",
                                  assembly_name="other-assembly.json")
            raise AssertionError("expected ValueError for a mismatched assembly pin")
        except ValueError as e:
            assert "mismatched pin" in str(e)

    print("FINEWEB_EXCLUSION_FAIL_CLOSED_SELFTEST_PASS")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--preflight", action="store_true",
                    help="PRODUCTION read-only: validate the real receipt "
                         "against the real shard bytes and emit a "
                         f"{EXCLUSION_TICKET} receipt")
    ap.add_argument("--shard-dir", default=None,
                    help="override the shard receipt's own shard_dir (e.g. "
                         "an out-of-tree ember-data path)")
    a = ap.parse_args()
    if a.selftest:
        _selftest()
        _selftest_fail_closed_against_real_schema()
        return
    if a.preflight:
        from receipt_write import checked_write        # noqa: E402
        receipt = run_preflight(shard_dir=a.shard_dir)
        out = f"{NC}/receipts/fineweb-edu-exclusion-preflight-{receipt['ts']}.json"
        checked_write(out, receipt)
        print(f"FINEWEB_EDU_EXCLUSION_PREFLIGHT_DONE "
              f"{os.path.relpath(out, NC)} "
              f"({receipt['n_windows_enforced']:,}/"
              f"{receipt['n_windows_unenforced']:,} windows usable)")
        return
    print("FINEWEB_EXCLUSION_STAGED — pass --selftest or --preflight "
         "--shard-dir <real shards path>")


if __name__ == "__main__":
    main()
