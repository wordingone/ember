"""w1c_certification_e2e.py -- Tier-2 synthetic end-to-end pipeline for the
#372 W1c certification re-scope (RE-SCOPE RULING, issue #374 comment
4920277395). Proves the FULL production wiring is correct on a small
synthetic corpus:

  heldout_v21_fcalib.py CLI (--emit-boilerplate-keys)
    -> w2-boilerplate-keys/v1 JSON artifact
    -> BoilerplateBloomIndex.build_from_fcalib_boilerplate_keys (rework372)
    -> HeldoutCertifier (source-disjointness + Bloom + exact-recheck)
    -> certification verdicts, checked against a ground-truth oracle that
       re-derives each window's real corpus-wide doc-frequency directly
       from the synthetic token stream (never trusts the Bloom/fcalib
       output alone)

SCOPE (frozen spec, RE-SCOPE RULING landing instructions): synthetic/pilot
data ONLY -- no corpus-scale pass, no GPU, no multi-hour job. cap=15 here is
a TEST-SCALE parameter (production cap is 256); this module never touches
a real shard directory.

This module is deliberately run BOTH as an importable pipeline (for
test_w1c_certification_e2e.py, which asserts on the returned dict with no
filesystem writes of its own) and as a standalone CLI (`python -m
scripts.w2_heldout.w1c_certification_e2e` or direct invocation) that writes
ONE receipt under receipts/ -- the AC5 deliverable.

Schema: w2-w1c-certification-e2e/v1.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_ROOT = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS_ROOT)
sys.path.insert(0, SCRIPTS_ROOT)
sys.path.insert(0, REPO_ROOT)

import heldout_v21_fcalib as fcalib  # noqa: E402
from w2_heldout.corpus_boilerplate_bloom import BoilerplateBloomIndex  # noqa: E402
from w2_heldout.certify_heldout_batch import HeldoutCertifier  # noqa: E402

try:
    from scripts.lib.invariant import stamp as stamp_invariant
except Exception:  # noqa: BLE001 -- disclose, never silently omit
    stamp_invariant = None

TICKET = "W1C-CERTIFICATION-E2E"
SCHEMA = "w2-w1c-certification-e2e/v1"
SPEC_REF = (
    "https://github.com/wordingone/ember/issues/374#issuecomment-4920277395")
W = 4                      # window_tokens -- tiny, matches fcalib's own toy fixtures
TEST_CAP = 15              # TEST-SCALE cap (production default is 256)
F_VALUES_CSV = "1e-05,1e-04,1e-03"
F_KEY = "1e-03"            # frozen recommended f (RE-SCOPE RULING receipt reference)
CERT_SOURCE = "code_github_clean"


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _pack_docs(docs: list[list[int]]) -> list[int]:
    toks = []
    for d in docs:
        toks.extend(d)
        toks.append(fcalib.SEPARATOR_ID)
    return toks


def _synthetic_corpus() -> dict[str, list[list[int]]]:
    """A small, deliberately-engineered synthetic corpus over all 5 fixed
    production sources (fcalib.SOURCE_ORDER). Only CERT_SOURCE carries real
    duplication; the other 4 are trivial single-doc stubs so the fixed
    5-source shape checksum_boundaries requires is satisfied cheaply.

    CERT_SOURCE = 28 documents:
      - 12 "filler" docs sharing window (10,11,12,13) -> real freq=12,
        below TEST_CAP(15) -> classified EXACT (not cap-saturated); with
        n_docs=28 the k_source floor of 10 applies at every f in
        F_VALUES_CSV, so 12 > 10 -> GENUINE (non-cap) boilerplate.
      - 15 "capped" docs sharing window (20,21,22,23) -> real freq=15 ==
        TEST_CAP -> sentinel-capped -> CAP_SATURATED (conservative drop,
        unconditional, regardless of k).
      - 1 "clean" doc with window (30,31,32,33) -> real freq=1 -> never
        crosses any k -> CLEAN (never enters boilerplate_keys at all).
    """
    cert_docs = ([[10, 11, 12, 13, 200 + i] for i in range(12)]
                 + [[20, 21, 22, 23, 300 + i] for i in range(15)]
                 + [[30, 31, 32, 33]])
    return {
        CERT_SOURCE: cert_docs,
        "fineweb_edu": [[40, 41, 42, 43]],
        "wikipedia_en": [[50, 51, 52, 53]],
        "gutenberg_en": [[60, 61, 62, 63]],
        "ledger_mit": [[70, 71, 72, 73]],
    }


def _write_synthetic_shard(tmpdir: str, docs_by_source: dict) -> tuple[str, str]:
    """Writes a toy token-shards-v0-shaped receipt + binary shard, in the
    fixed SOURCE_ORDER, matching heldout_v21_fcalib.py's expected input
    exactly (same pattern as its own _selftest())."""
    shard_dir = os.path.join(tmpdir, "shards")
    os.makedirs(shard_dir, exist_ok=True)

    all_tokens: list[int] = []
    per_source = {}
    for src in fcalib.SOURCE_ORDER:
        docs = docs_by_source[src]
        toks = _pack_docs(docs)
        per_source[src] = {
            "content_tokens": sum(len(d) for d in docs),
            "separator_tokens": len(docs),
            "stream_tokens": len(toks),
        }
        all_tokens.extend(toks)

    arr = np.asarray(all_tokens, dtype="<u2")
    arr.tofile(os.path.join(shard_dir, "v0-00000.bin"))

    shard_receipt = {
        "ticket": "TOKEN-SHARDS-V0",
        "ts": "20260611T000000Z",
        "total_stream_tokens": len(all_tokens),
        "per_source": per_source,
        "separator_id": fcalib.SEPARATOR_ID,
        "sha_convention": fcalib.SHA_CONVENTION,
    }
    receipt_path = os.path.join(tmpdir, "toy-shard-receipt.json")
    with open(receipt_path, "w", encoding="utf-8") as f:
        json.dump(shard_receipt, f)

    return shard_dir, receipt_path


def _ground_truth_doc_freq(docs: list[list[int]], window_tokens: int,
                           key_tuple: tuple[int, ...]) -> int:
    """Re-derives a window's TRUE corpus-wide doc-frequency directly from
    the raw synthetic token stream (never trusts the Bloom or the fcalib
    JSON output) -- the exact-recheck oracle. Counts DISTINCT documents in
    which `key_tuple` occurs as a contiguous W-token subsequence at least
    once (matches the predicate's own "distinct documents" definition)."""
    n = 0
    for doc in docs:
        found = any(
            tuple(doc[i:i + window_tokens]) == key_tuple
            for i in range(len(doc) - window_tokens + 1))
        if found:
            n += 1
    return n


def run_synthetic_e2e(target_fp_rate: float = 0.01) -> dict:
    """Runs the full Tier-2 synthetic pipeline and returns a receipt-shaped
    dict. No corpus-scale pass, no GPU, no network -- entirely local,
    hermetic, cheap (matches --selftest-class scope). Safe to call
    unconditionally from CI (no env-var skip)."""
    docs_by_source = _synthetic_corpus()
    cert_docs = docs_by_source[CERT_SOURCE]
    n_docs_cert_source = len(cert_docs)

    with tempfile.TemporaryDirectory() as tmpdir:
        shard_dir, receipt_path = _write_synthetic_shard(tmpdir, docs_by_source)
        fcalib_out = os.path.join(tmpdir, "fcalib-receipt.json")
        keys_out = os.path.join(tmpdir, "boilerplate-keys.json")

        argv = [
            "--shard-dir", shard_dir,
            "--shard-receipt", receipt_path,
            "--cache-dir", os.path.join(tmpdir, "cache"),
            "--window-tokens", str(W),
            "--cap", str(TEST_CAP),
            "--sample-rate", "1.0",
            "--f-values", F_VALUES_CSV,
            "--emit-boilerplate-keys",
            "--boilerplate-keys-out", keys_out,
            "--out", fcalib_out,
            "--commit-floor-gib", "0",
        ]
        rc = fcalib.main(argv)
        if rc not in (0, None):
            raise SystemExit(f"W1C_E2E_FCALIB_NONZERO_EXIT: rc={rc}")
        if not os.path.exists(keys_out):
            raise SystemExit(
                "W1C_E2E_NO_BOILERPLATE_KEYS_FILE: heldout_v21_fcalib.py "
                "--emit-boilerplate-keys produced no output file for a run "
                "with genuine boilerplate present -- this is exactly the "
                "single-call-path regression this test guards against")

        with open(fcalib_out, "r", encoding="utf-8") as f:
            fcalib_receipt = json.load(f)
        with open(keys_out, "r", encoding="utf-8") as f:
            keys_payload = json.load(f)

        index, cap_saturated_per_source = (
            BoilerplateBloomIndex.build_from_fcalib_boilerplate_keys(
                keys_out, f_key=F_KEY, target_fp_rate=target_fp_rate))

    # Ground-truth exact-recheck oracle: re-derive doc-frequency directly
    # from the raw synthetic corpus (never from the Bloom or fcalib JSON)
    k_by_f_cert_source = fcalib.k_source(float(F_KEY), n_docs_cert_source)

    def exact_recheck_fn(key_bytes: bytes, source: str) -> bool:
        key_tuple = tuple(int(x) for x in np.frombuffer(key_bytes, dtype="<u2"))
        docs = docs_by_source[source]
        freq = _ground_truth_doc_freq(docs, W, key_tuple)
        return freq > k_by_f_cert_source

    certifier = HeldoutCertifier(
        index, cap_saturated_per_source=cap_saturated_per_source,
        exact_recheck_fn=exact_recheck_fn)

    def _key(tokens: list[int]) -> bytes:
        return np.asarray(tokens, dtype="<u2").tobytes()

    candidates = [
        (_key([10, 11, 12, 13]), CERT_SOURCE),   # genuine boilerplate (freq=12>10)
        (_key([20, 21, 22, 23]), CERT_SOURCE),   # cap-saturated (freq=15==cap)
        (_key([30, 31, 32, 33]), CERT_SOURCE),   # clean (freq=1)
    ]
    cert_receipt = certifier.certify_batch(candidates, {CERT_SOURCE})

    # ------------------------------------------------------------------
    # Assemble the top-level e2e receipt (AC5 deliverable)
    # ------------------------------------------------------------------
    verdicts = {r["reason"]: r["certified"] for r in cert_receipt.results}
    receipt = {
        "ticket": TICKET,
        "schema": SCHEMA,
        "ts": _utc_ts(),
        "spec_ref": SPEC_REF,
        "scope": "synthetic/pilot-scale only -- no corpus-scale pass, no GPU",
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
        "window_tokens": W,
        "test_cap": TEST_CAP,
        "f_key": F_KEY,
        "f_values": F_VALUES_CSV,
        "cert_source": CERT_SOURCE,
        "n_docs_cert_source": n_docs_cert_source,
        "k_source_at_f": k_by_f_cert_source,
        "fcalib_run_status": fcalib_receipt.get("status"),
        "fcalib_predicate_version": fcalib_receipt.get("predicate_version"),
        "boilerplate_keys_by_source_buckets": {
            src: sorted(buckets.keys())
            for src, buckets in keys_payload.get(
                "boilerplate_keys_by_source", {}).items()
        },
        "bloom_index": {
            "n_boilerplate_keys": index.n_boilerplate_keys,
            "n_cap_saturated_keys": index.n_cap_saturated_keys,
            "bloom_m": index.bloom_filter.m,
            "bloom_k": index.bloom_filter.k,
            "target_fp_rate": target_fp_rate,
            "n_sources": index.n_sources,
        },
        "certification_batch": {
            "candidates": cert_receipt.candidates,
            "dropped_disjointness": cert_receipt.dropped_disjointness,
            "bloom_hits": cert_receipt.bloom_hits,
            "exact_confirmed": cert_receipt.exact_confirmed,
            "bloom_fp_absorbed": cert_receipt.bloom_fp_absorbed,
            "cap_dropped": cert_receipt.cap_dropped,
            "certified_count": cert_receipt.certified_count,
            "results": cert_receipt.results,
        },
        "verdicts_by_reason": verdicts,
        "sha_convention": fcalib.SHA_CONVENTION,
    }
    if stamp_invariant is not None:
        try:
            stamp_invariant(receipt, repo_root=REPO_ROOT)
        except Exception as e:  # noqa: BLE001 -- disclose, never silently omit
            receipt["invariant_stamp_error"] = str(e)
    return receipt


def main(out_path: str | None = None) -> int:
    receipt = run_synthetic_e2e()
    out_path = out_path or os.path.join(
        REPO_ROOT, "receipts", f"w1c-certification-e2e-{receipt['ts']}.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)
    print(f"[done] receipt written to {out_path}")
    print(f"  boilerplate keys: {receipt['bloom_index']['n_boilerplate_keys']}, "
          f"cap-saturated: {receipt['bloom_index']['n_cap_saturated_keys']}")
    print(f"  certification: {receipt['certification_batch']['certified_count']}/"
          f"{receipt['certification_batch']['candidates']} certified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
