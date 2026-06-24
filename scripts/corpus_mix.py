"""corpus_mix.py — eng-44 (#168): CORPUS-MIX-V0 receipt.

Extends the merged tokenizer-freeze receipt with the corpus-side mix audit
that feeds #167's packed loader and the fp-22 mix plan:

  - EXACT per-source mean tokens/doc (freeze real total / manifest doc count)
    + sample-based median / p95 token-length distribution,
  - packing-efficiency ESTIMATE at seq 1024 (waste fraction WITHOUT packing —
    motivates #167's no-pad sequence packing),
  - code/prose mix vs the fp-22 60/40 plan (delta receipted, not prose),
  - corpus-side reserved-band verification: ids 1-7 NEVER occur in the
    tokenized stream (NC2 v0 LOCK #1 second half; the freeze receipt verified
    the tokenizer side, this verifies the corpus side).

Pins (fail-closed): the merged tokenizer-freeze receipt by name + sha256, the
eng-36 assembly receipt by name + sha256 (reused from tokenizer_freeze), and
the frozen tokenizer.json by sha256. CPU-only, no GPU.

Band-check equivalence (airtight, recorded in the receipt): ids 0-7 are the
special ADDED tokens; the BpeTrainer assigns specials the first ids, so the
learned BPE vocab occupies ids >= 8. A BPE merge therefore CANNOT emit ids
1-7 — they appear in the tokenized stream iff a document contains one of the
7 literal special strings. A full-corpus scan for those strings is thus
exactly equivalent to "ids 1-7 occur", and is confirmed empirically on the
sample (encode -> assert no id in 1-7).

Run:       python scripts/corpus_mix.py --mix-stats
Selftest:  python scripts/corpus_mix.py --selftest   (fixture, no network)
"""
import argparse
import json
import math
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import tokenizer_freeze as tf  # noqa: E402 — reuse the proven primitives
from receipt_write import checked_write  # noqa: E402

OUT_ROOT_DEFAULT = tf.OUT_ROOT_DEFAULT
SEQ_PACK = 1024                     # c03 seq (fp-19 pin) — the packing window
SAMPLE_BUDGET_BYTES = 300_000_000   # distribution estimate; band scan is FULL
CODE_SOURCE = "code_github_clean"
PLAN_CODE_FRACTION = 0.60           # fp-22 60/40 plan

# The band the corpus must never carry (ids 1-7 — <|endoftext|>=0 is a legal
# document delimiter and is excluded from this check by design).
BAND_IDS = list(range(1, 8))
BAND_STRINGS = tf.SPECIAL_TOKENS[1:8]

# The merged tokenizer-freeze receipt, pinned by name + sha256 (the same
# discipline as the assembly-sha gate; refuse on absent/drift).
FREEZE_RECEIPT_BASENAME = "tokenizer-freeze-20260611T060423Z.json"
FREEZE_RECEIPT_SHA256 = \
    "cefd8238e5ff414273a0954be4399262aad064a8cb312356dca43d6e4a4e009e"

SHA_CONVENTION = tf.SHA_CONVENTION


def band_regex():
    """Compiled alternation of the 7 reserved special strings (ids 1-7)."""
    return re.compile("|".join(re.escape(s) for s in BAND_STRINGS))


def pinned_freeze_receipt(repo):
    """The ONE merged tokenizer-freeze receipt, by name AND sha256. Absent or
    byte-drifted -> refuse (same gate shape as the assembly-sha pin)."""
    path = os.path.join(repo, "receipts", FREEZE_RECEIPT_BASENAME)
    if not os.path.exists(path):
        raise SystemExit(f"corpus_mix: pinned tokenizer-freeze receipt "
                         f"absent: {FREEZE_RECEIPT_BASENAME}")
    got = tf.file_sha256(path)
    if got != FREEZE_RECEIPT_SHA256:
        raise SystemExit(f"corpus_mix: freeze receipt sha mismatch "
                         f"({got[:12]} != pinned "
                         f"{FREEZE_RECEIPT_SHA256[:12]})")
    return path, json.load(open(path, encoding="utf-8"))


def length_stats(hist):
    """From a {token_length: doc_count} Counter -> n_docs, sum_tokens, mean,
    median, p95. Median/p95 are exact over the histogram (sample, when the
    histogram is built from a sample)."""
    n = sum(hist.values())
    if n == 0:
        return {"n_docs": 0, "sum_tokens": 0, "mean": None,
                "median": None, "p95": None}
    total = sum(length * c for length, c in hist.items())
    items = sorted(hist.items())

    def _quantile(q):
        target = q * n
        cum = 0
        for length, c in items:
            cum += c
            if cum >= target:
                return length
        return items[-1][0]

    return {"n_docs": int(n), "sum_tokens": int(total),
            "mean": round(total / n, 3),
            "median": int(_quantile(0.5)), "p95": int(_quantile(0.95))}


def packing_waste(hist, seq):
    """Waste fraction WITHOUT packing: model each doc as padded up to a whole
    multiple of `seq` (ceil(len/seq) sequences). waste = padded_slots_unused /
    padded_slots_total. With sequence packing this collapses to ~0 (one final
    partial window) — that delta is why #167 packs. Pure function of the
    distribution."""
    used = 0
    slots = 0
    for length, c in hist.items():
        used += length * c
        slots += int(math.ceil(length / seq)) * seq * c
    if slots == 0:
        return None
    return round(1.0 - used / slots, 6)


def scan_source(manifest, corpus_dir, tok, band_re, sample_k,
                sample_budget_bytes):
    """ONE streaming pass over a source's shards:
      - FULL band scan: count docs containing any reserved string (ids 1-7),
      - SAMPLE (every k-th doc up to budget): encode with the frozen tokenizer,
        add the token length to the histogram, and assert no id in 1-7.
    Returns a dict of the pass results."""
    band_string_hits = 0
    sample_hist = Counter()
    sample_id_band_hits = 0
    sample_docs = 0
    sample_bytes = 0
    n_docs = 0
    batch, batch_bytes = [], 0

    def _flush(batch):
        nonlocal sample_id_band_hits
        encs = tok.encode_batch(batch)
        for e in encs:
            sample_hist[len(e.ids)] += 1
            if any(i in BAND_IDS for i in e.ids):
                sample_id_band_hits += 1

    for text in tf.iter_shard_docs(manifest, corpus_dir):
        if band_re.search(text):
            band_string_hits += 1
        if n_docs % sample_k == 0 and sample_bytes < sample_budget_bytes:
            batch.append(text)
            batch_bytes += len(text)
            sample_bytes += len(text.encode("utf-8"))
            sample_docs += 1
            if len(batch) >= 512 or batch_bytes >= 32_000_000:
                _flush(batch)
                batch, batch_bytes = [], 0
        n_docs += 1
    if batch:
        _flush(batch)

    return {
        "n_docs": n_docs,
        "band_string_hits": band_string_hits,
        "sample_docs": sample_docs,
        "sample_bytes": sample_bytes,
        "sample_id_band_hits": sample_id_band_hits,
        "sample_hist": sample_hist,
    }


def build_mix(repo, out_root, sample_budget):
    """Produce the CORPUS-MIX-V0 receipt body (no write). Fail-closed on any
    band occurrence."""
    from tokenizers import Tokenizer

    freeze_path, freeze = pinned_freeze_receipt(repo)
    tf.pinned_assembly_receipt(repo)  # reuse the eng-36 assembly-sha gate
    manifests = tf.load_manifests(repo)

    tok_path = os.path.join(repo, "tokenizer", "tokenizer.json")
    tok_sha = tf.file_sha256(tok_path)
    if tok_sha != freeze["tokenizer_json_sha256"]:
        raise SystemExit(f"corpus_mix: tokenizer.json sha {tok_sha[:12]} != "
                         f"freeze receipt {freeze['tokenizer_json_sha256'][:12]}")
    tok = Tokenizer.from_file(tok_path)
    band_re = band_regex()

    real_counts = freeze["real_token_counts"]
    source_bytes = {s: m["counts"]["text_bytes_kept"]
                    for s, (m, _) in manifests.items()}
    budgets = tf.stratified_budgets(source_bytes, sample_budget)

    per_source = {}
    total_string_hits = 0
    total_sample_id_hits = 0
    agg_hist = Counter()
    for src in sorted(manifests):
        m, _ = manifests[src]
        corpus_dir = os.path.join(out_root, src)
        k = max(1, source_bytes[src] // max(1, budgets[src]))
        res = scan_source(m, corpus_dir, tok, band_re, k, budgets[src])
        total_string_hits += res["band_string_hits"]
        total_sample_id_hits += res["sample_id_band_hits"]
        agg_hist.update(res["sample_hist"])

        docs_real = m["counts"]["docs_kept"]
        tokens_real = real_counts[src]
        # cross-check: the manifest doc count is the band-scan doc count
        if res["n_docs"] != docs_real:
            raise SystemExit(
                f"corpus_mix: {src} doc-count drift — scanned {res['n_docs']} "
                f"!= manifest {docs_real}")
        stats = length_stats(res["sample_hist"])
        per_source[src] = {
            "tokens_real": tokens_real,
            "docs": docs_real,
            "mean_tokens_per_doc_exact": round(tokens_real / docs_real, 3),
            "sample": {"docs": res["sample_docs"],
                       "bytes": res["sample_bytes"],
                       "stride_k": k,
                       "median_tokens": stats["median"],
                       "p95_tokens": stats["p95"],
                       "mean_tokens": stats["mean"]},
            "packing_waste_no_packing_at_seq1024":
                packing_waste(res["sample_hist"], SEQ_PACK),
            "band_string_hits": res["band_string_hits"],
            "sample_id_band_hits": res["sample_id_band_hits"],
        }
        print(f"[mix] {src}: docs={docs_real} tokens={tokens_real} "
              f"mean={per_source[src]['mean_tokens_per_doc_exact']} "
              f"median~{stats['median']} p95~{stats['p95']} "
              f"band_hits={res['band_string_hits']}", flush=True)

    # corpus-side band verdict — fail closed
    if total_string_hits != 0 or total_sample_id_hits != 0:
        raise SystemExit(
            f"corpus_mix: RESERVED BAND VIOLATION — string_hits="
            f"{total_string_hits} sample_id_hits={total_sample_id_hits} "
            f"(ids 1-7 must never occur in the corpus)")

    code_tokens = real_counts[CODE_SOURCE]
    real_total = real_counts["total"]
    code_fraction = code_tokens / real_total
    corpus_waste = packing_waste(agg_hist, SEQ_PACK)

    return {
        "ticket": "CORPUS-MIX-V0",
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "issue": "wordingone/ember#168",
        "scope": ("corpus-side mix audit on the frozen v0 tokenizer + corpus: "
                  "per-source distributions, packing-efficiency estimate, "
                  "code/prose mix, reserved-band corpus-side verification"),
        "tokenizer_receipt": FREEZE_RECEIPT_BASENAME,
        "tokenizer_receipt_sha256": FREEZE_RECEIPT_SHA256,
        "tokenizer_json_sha256": tok_sha,
        "assembly_receipt_sha256": tf.ASSEMBLY_RECEIPT_SHA256,
        "seq_pack": SEQ_PACK,
        "real_total_tokens": real_total,
        "per_source": per_source,
        "packing": {
            "model": ("each doc padded up to ceil(len/seq)*seq; waste = unused "
                      "padded slots / total padded slots at seq 1024"),
            "corpus_waste_fraction_no_packing": corpus_waste,
            "note": ("sequence packing collapses this to ~0 (one final partial "
                     "window) — the delta is why #167 packs no-pad"),
            "estimate_basis": ("aggregate over the stratified sample "
                               "(distribution shape); exact per-source token "
                               "totals are from the freeze receipt"),
        },
        "mix": {
            "code_source": CODE_SOURCE,
            "code_fraction_real": round(code_fraction, 4),
            "plan_code_fraction": PLAN_CODE_FRACTION,
            "delta": round(code_fraction - PLAN_CODE_FRACTION, 4),
            "note": ("real code fraction vs the fp-22 60/40 plan; delta "
                     "receipted (not prose)"),
        },
        "reserved_band_corpus_side": {
            "band_ids": BAND_IDS,
            "special_strings": BAND_STRINGS,
            "total_string_hits": total_string_hits,
            "total_sample_id_hits": total_sample_id_hits,
            "verdict": "CLEAN",
            "equivalence_basis": (
                "ids 0-7 are special added tokens; learned BPE vocab is ids "
                ">= 8, so a merge cannot emit ids 1-7 — they occur iff a doc "
                "carries a literal special string. Full-corpus string scan = "
                "the id-occurrence check; confirmed on the sample (encode -> "
                "no id in 1-7). NC2 v0 LOCK #1 corpus side."),
        },
        "sample_budget_bytes": sample_budget,
        "sampler": ("deterministic stride per source (k = source_bytes // "
                    "budget), no RNG — same as tokenizer_freeze.sample_source"),
        "sha_convention": SHA_CONVENTION,
        "no_gpu": True,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-root", default=OUT_ROOT_DEFAULT)
    ap.add_argument("--sample-budget", type=int, default=SAMPLE_BUDGET_BYTES)
    ap.add_argument("--mix-stats", action="store_true",
                    help="required to run the full corpus pass + write receipt")
    args, _unknown = ap.parse_known_args()

    if not args.mix_stats:
        raise SystemExit("corpus_mix: pass --mix-stats explicitly")

    receipt = build_mix(REPO, args.out_root, args.sample_budget)
    out = os.path.join(REPO, "receipts", f"corpus-mix-{receipt['ts']}.json")
    checked_write(out, receipt)
    print(json.dumps({k: receipt[k] for k in
                      ("real_total_tokens", "mix", "packing",
                       "reserved_band_corpus_side")}, indent=2))
    print(f"[mix] receipt: {out}")
    print("CORPUS_MIX_DONE")


if __name__ == "__main__":
    main()
