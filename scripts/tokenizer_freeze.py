"""tokenizer_freeze.py — fp-22 tokenizer leg: train-on-sample 32k vocab,
frozen pre-step-0, sha-stamped.

Spec (fp-22 §1 + launch order §4): 32k vocab (fp-19 config pin), trained
on a stratified ~1GB sample of THE v0 corpus (the eng-36 artifacts —
NOT external text), frozen BEFORE pretrain step 0, tokenizer sha stamped
into every checkpoint receipt thereafter.

Determinism: NO RNG anywhere. Stratified sampling is stride-based over
the corpus shards in manifest order (shards are sha-frozen by the
eng-36 assembly receipt, so the sample is a pure function of the corpus
+ the budgets). ByteLevel BPE training on a fixed sample is
deterministic; the selftest pins byte-identical double-train.

eng #160 ACs on top of the prep harness:
  - AC-1: the production freeze pins the MERGED eng-36 assembly receipt
    by name AND sha256 (Kai 14560) — absent/drifted = refuse before any
    sampling work;
  - AC-2: freeze receipt carries the reserved multimodal special-token
    band (NC2 contract component 8, v0 LOCK #1 — gemma-4 pattern,
    fixed ids verified post-train) and REAL per-source + total token
    counts from the frozen tokenizer, resolving the assembly receipt's
    HEURISTIC-ONLY estimate (tokens_pending_tokenizer_freeze -> false).

Fail-closed interlocks:
  - refuses to run without corpus-manifests/ + the PINNED assembly
    receipt (eng-36 must be GATED/merged first — launch order);
  - refuses if a freeze receipt already exists (frozen = frozen; one
    tokenizer for v0, no re-freeze path);
  - reserved band verified at its pre-assigned ids post-train;
  - sample sha256 + per-source strata + tokenizer.json sha256 all land
    in the freeze receipt via checked_write.

Run:  python scripts/tokenizer_freeze.py --freeze
Selftest: tokenizer_freeze_selftest.py (fixture corpus, no network).
"""
import argparse
import glob
import hashlib
import io
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from receipt_write import checked_write  # noqa: E402

OUT_ROOT_DEFAULT = "B:/M/avir/eli/state/ember-eng/corpus-v0"

VOCAB_SIZE = 32_000  # fp-19 config pin: "vocab 32k"
SAMPLE_BUDGET_BYTES = 1_000_000_000  # fp-22: "stratified ~1GB sample"

# Reserved multimodal special-token band — NC2 own-technique contract
# component 8, v0 LOCK #1 ("Reserved vocab band with pre-assigned
# multimodal delimiter/placeholder token IDs"); names follow the
# gemma-4 deep-dive pattern (research/gemma4-unified-architecture.md:
# boi/eoi/image_soft/boa/eoa/audio_soft/video_soft). v0 is text-only —
# the IDs are pre-assigned, never produced by training data; the
# embedder that splices over them is a proven retrofit. Fixed
# positions: BpeTrainer assigns special tokens the FIRST ids in list
# order, so the band is ids 0..7 by construction (verified post-train,
# fail-closed).
SPECIAL_TOKENS = ["<|endoftext|>", "<boi>", "<eoi>", "<image_soft>",
                  "<boa>", "<eoa>", "<audio_soft>", "<video_soft>"]
RESERVED_BAND = {t: i for i, t in enumerate(SPECIAL_TOKENS)}

# eng #160 AC-1 (Kai 14560 assembly-sha gate): the production freeze
# runs ONLY against the merged eng-36 assembly receipt, pinned BY
# sha256. Absent or mismatching -> refuse before any sampling work.
ASSEMBLY_RECEIPT_BASENAME = "eng36-assembly-20260611T052337Z.json"
ASSEMBLY_RECEIPT_SHA256 = \
    "a29d2e567f1853966cc72a4890eadc963164265e4f24a89cadea24d9ff5b80c2"

SHA_CONVENTION = ("sha256 over on-disk raw bytes "
                  "(binary read, no line-ending normalization)")


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stratified_budgets(source_bytes, total_budget):
    """{source: text_bytes} -> {source: sample_budget_bytes}.
    Proportional to corpus share; a source smaller than its share is
    taken whole (the remainder is NOT redistributed — determinism and
    simplicity beat squeezing the last MB). Pure."""
    total = sum(source_bytes.values())
    budgets = {}
    for src, b in source_bytes.items():
        share = int(total_budget * b / total)
        budgets[src] = min(b, share if share > 0 else b)
    return budgets


def iter_shard_docs(manifest, corpus_dir):
    """Yield text docs from a source's shards in manifest order.
    Deterministic: shard order + line order are frozen by the
    assembly-receipt sha chain."""
    import zstandard
    for s in manifest["shards"]:
        p = os.path.join(corpus_dir, s["file"])
        dctx = zstandard.ZstdDecompressor()
        with open(p, "rb") as f:
            reader = io.TextIOWrapper(dctx.stream_reader(f),
                                      encoding="utf-8")
            for line in reader:
                if line.strip():
                    yield json.loads(line)["text"]


def sample_source(manifest, corpus_dir, budget_bytes):
    """Stride-sample a source's docs to ~budget_bytes. Deterministic:
    keep every k-th doc, k = max(1, floor(source_bytes / budget)).
    Stops at budget. Returns (texts, docs_seen, bytes_kept)."""
    source_bytes = manifest["counts"]["text_bytes_kept"]
    k = max(1, source_bytes // max(1, budget_bytes))
    texts, kept_bytes, seen = [], 0, 0
    for text in iter_shard_docs(manifest, corpus_dir):
        if seen % k == 0:
            texts.append(text)
            kept_bytes += len(text.encode("utf-8"))
            if kept_bytes >= budget_bytes:
                seen += 1
                break
        seen += 1
    return texts, seen, kept_bytes


def load_manifests(repo):
    """Exactly one manifest mirror per source (assembly invariant)."""
    mirrors = sorted(glob.glob(
        os.path.join(repo, "corpus-manifests", "*-manifest-*.json")))
    if not mirrors:
        raise SystemExit("tokenizer_freeze: no corpus-manifests/ mirrors "
                         "found — eng-36 must be merged first "
                         "(launch order: corpus gate -> tokenizer freeze)")
    out = {}
    for p in mirrors:
        m = json.load(open(p, encoding="utf-8"))
        src = m["source"]
        if src in out:
            raise SystemExit(f"tokenizer_freeze: duplicate manifest mirror "
                             f"for {src}")
        out[src] = (m, p)
    return out


def pinned_assembly_receipt(repo):
    """eng #160 AC-1: the ONE merged assembly receipt, by name AND
    sha256. Absent or byte-drifted -> refuse (Kai 14560)."""
    path = os.path.join(repo, "receipts", ASSEMBLY_RECEIPT_BASENAME)
    if not os.path.exists(path):
        raise SystemExit(f"tokenizer_freeze: pinned assembly receipt "
                         f"absent: {ASSEMBLY_RECEIPT_BASENAME} — the "
                         f"merged eng-36 corpus is the only valid input")
    got = file_sha256(path)
    if got != ASSEMBLY_RECEIPT_SHA256:
        raise SystemExit(f"tokenizer_freeze: assembly receipt sha "
                         f"mismatch ({got[:12]} != pinned "
                         f"{ASSEMBLY_RECEIPT_SHA256[:12]}) — refusing "
                         f"to freeze against drifted corpus state")
    return path


def existing_freeze_receipts(repo):
    """Production freeze receipts ONLY (tokenizer-freeze-<ts>.json).
    Selftest receipts share the prefix and must NOT trip the re-freeze
    refusal — match the exact ts shape."""
    import re
    pat = re.compile(r"^tokenizer-freeze-\d{8}T\d{6}Z\.json$")
    return sorted(
        p for p in glob.glob(
            os.path.join(repo, "receipts", "tokenizer-freeze-*.json"))
        if pat.match(os.path.basename(p)))


def build_sample(repo, out_root, budget_total):
    """Stratified sample across all sources. Returns
    (sample_path, strata_rows, assembly_path)."""
    manifests = load_manifests(repo)
    assembly_path = pinned_assembly_receipt(repo)
    assembly = json.load(open(assembly_path, encoding="utf-8"))
    asm_sources = {r["source"] for r in assembly["sources"]}
    if set(manifests) != asm_sources:
        raise SystemExit(f"tokenizer_freeze: manifest mirrors "
                         f"{sorted(manifests)} != assembly sources "
                         f"{sorted(asm_sources)}")

    source_bytes = {s: m["counts"]["text_bytes_kept"]
                    for s, (m, _) in manifests.items()}
    budgets = stratified_budgets(source_bytes, budget_total)

    tok_dir = os.path.join(out_root, "tokenizer")
    os.makedirs(tok_dir, exist_ok=True)
    sample_path = os.path.join(tok_dir, "sample.txt")
    strata = []
    with open(sample_path, "w", encoding="utf-8", newline="\n") as sf:
        for src in sorted(manifests):  # fixed order: alphabetical
            m, mirror_path = manifests[src]
            corpus_dir = os.path.join(out_root, src)
            texts, seen, kept = sample_source(m, corpus_dir, budgets[src])
            for t in texts:
                sf.write(t)
                sf.write("\n<|endoftext|>\n")
            strata.append({
                "source": src,
                "budget_bytes": budgets[src],
                "docs_sampled": len(texts),
                "docs_seen": seen,
                "bytes_sampled": kept,
                "manifest_mirror_sha256": file_sha256(mirror_path),
            })
            print(f"[sample] {src}: {len(texts)} docs / {kept} bytes "
                  f"(budget {budgets[src]})", flush=True)
    return sample_path, strata, assembly_path, manifests


def train_tokenizer(sample_path, vocab_size, tok_dir):
    """ByteLevel BPE — deterministic for a fixed sample file."""
    from tokenizers import Tokenizer, models, pre_tokenizers, trainers
    tok = Tokenizer(models.BPE(unk_token=None))
    tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    trainer = trainers.BpeTrainer(vocab_size=vocab_size,
                                  special_tokens=SPECIAL_TOKENS,
                                  show_progress=False)
    tok.train([sample_path], trainer)
    out = os.path.join(tok_dir, "tokenizer.json")
    tok.save(out)
    return out


def verify_reserved_band(tok_path):
    """Post-train fail-closed check that the reserved multimodal band
    sits at its pre-assigned ids (NC2 v0 LOCK #1)."""
    from tokenizers import Tokenizer
    tok = Tokenizer.from_file(tok_path)
    got = {t: tok.token_to_id(t) for t in SPECIAL_TOKENS}
    if got != RESERVED_BAND:
        raise SystemExit(f"tokenizer_freeze: reserved band drifted: "
                         f"{got} != {RESERVED_BAND}")
    return got


def count_tokens(tok_path, manifests, out_root,
                 batch_docs=512, batch_bytes=32_000_000):
    """REAL token count per source with the frozen tokenizer (eng #160
    AC-2: resolves the bytes/chars heuristic; tokens_pending_tokenizer_
    freeze -> resolved). Batches are bounded by docs AND bytes so
    book-sized records cannot blow memory. Counts are content tokens
    (no specials injected)."""
    from tokenizers import Tokenizer
    tok = Tokenizer.from_file(tok_path)
    per_source = {}
    for src in sorted(manifests):
        m, _ = manifests[src]
        corpus_dir = os.path.join(out_root, src)
        n, batch, bbytes = 0, [], 0
        for text in iter_shard_docs(m, corpus_dir):
            batch.append(text)
            bbytes += len(text)
            if len(batch) >= batch_docs or bbytes >= batch_bytes:
                n += sum(len(e.ids) for e in tok.encode_batch(batch))
                batch, bbytes = [], 0
        if batch:
            n += sum(len(e.ids) for e in tok.encode_batch(batch))
        per_source[src] = n
        print(f"[count] {src}: {n} tokens", flush=True)
    return per_source


def recount_disabled_matching(census_receipt, out_root):
    """eng #195 deviation remedy (Leo 14628, decision frozen pre-census):
    re-derive real_token_counts under the PRODUCTION encode semantics —
    added-token literal matching DISABLED — and emit a superseding
    tokenizer-freeze receipt. Same assembly pin, same tokenizer bytes (the
    sha-pinned tokenizer.json is untouched on disk); only the counting
    instrument's semantics change, aligned to the TOKEN-SHARDS-V0 band
    contract (text never yields ids 0..7). The census receipt (matching
    ENABLED, diagnostic) rides along as the deviation's size evidence.

    NOT a re-freeze: no sampling, no training, no tokenizer bytes written.
    The --freeze one-shot refusal is untouched."""
    from token_shards_v0 import ENCODE_SEMANTICS, _production_tokenizer

    prior = existing_freeze_receipts(REPO)
    if not prior:
        raise SystemExit("recount: no production freeze receipt to "
                         "re-derive from")
    base_path = prior[-1]
    base_sha = file_sha256(base_path)
    base = json.load(open(base_path, encoding="utf-8"))
    pinned_assembly_receipt(REPO)
    if base.get("assembly_receipt_sha256") != ASSEMBLY_RECEIPT_SHA256:
        raise SystemExit("recount: base freeze pins a different assembly "
                         "receipt — refusing")
    census_path = os.path.join(REPO, census_receipt) \
        if not os.path.isabs(census_receipt) else census_receipt
    if not os.path.exists(census_path):
        raise SystemExit(f"recount: census receipt absent: {census_path} — "
                         f"the deviation must be sized before the "
                         f"re-derivation lands")
    census_sha = file_sha256(census_path)

    manifests = load_manifests(REPO)
    tok = _production_tokenizer(REPO, base, match_added_tokens=False)
    per_source = {}
    for src in sorted(manifests):
        m, _ = manifests[src]
        corpus_dir = os.path.join(out_root, src)
        n, batch, bbytes = 0, [], 0
        for text in iter_shard_docs(m, corpus_dir):
            batch.append(text)
            bbytes += len(text)
            if len(batch) >= 512 or bbytes >= 32_000_000:
                n += sum(len(e.ids) for e in tok.encode_batch(batch))
                batch, bbytes = [], 0
        if batch:
            n += sum(len(e.ids) for e in tok.encode_batch(batch))
        per_source[src] = n
        print(f"[recount] {src}: {n} tokens", flush=True)
    new_total = sum(per_source.values())
    old_counts = base.get("real_token_counts") or {}

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = dict(base)
    receipt.update({
        "ts": ts,
        "real_token_counts": {**per_source, "total": new_total},
        "encode_semantics": ENCODE_SEMANTICS,
        "derived_from": {"name": os.path.basename(base_path),
                         "sha256": base_sha},
        "deviation_note": {
            "reason": ("text-borne special-token literals: under "
                       "matching-ENABLED encoding, added-token literals in "
                       "raw corpus text matched to reserved ids 0..7 and "
                       "were absorbed into real_token_counts — ids the "
                       "TOKEN-SHARDS-V0 band contract refuses from text. "
                       "Counts re-derived with matching DISABLED "
                       "(contract-aligned; Leo 14628, decision frozen "
                       "pre-census)"),
            "old_real_token_counts": old_counts,
            "total_delta_vs_old": new_total - (old_counts.get("total") or 0),
            "census_receipt": {"name": os.path.basename(census_path),
                               "sha256": census_sha},
        },
    })
    rh = dict(base.get("resolves_heuristic") or {})
    rh["real_total"] = new_total
    receipt["resolves_heuristic"] = rh

    out = os.path.join(REPO, "receipts", f"tokenizer-freeze-{ts}.json")
    checked_write(out, receipt)
    print(f"[recount] TOTAL real tokens: {new_total} "
          f"(was {old_counts.get('total')}, "
          f"delta {new_total - (old_counts.get('total') or 0)})", flush=True)
    print(f"[recount] receipt: {out}")
    print("TOKENIZER_RECOUNT_DONE")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-root", default=OUT_ROOT_DEFAULT)
    ap.add_argument("--budget", type=int, default=SAMPLE_BUDGET_BYTES)
    ap.add_argument("--vocab", type=int, default=VOCAB_SIZE)
    ap.add_argument("--freeze", action="store_true",
                    help="required to run — this writes the ONE frozen "
                         "v0 tokenizer (no re-freeze path)")
    ap.add_argument("--recount", metavar="CENSUS_RECEIPT",
                    help="re-derive real_token_counts under the production "
                         "encode semantics (added-token matching disabled, "
                         "token_shards_v0.ENCODE_SEMANTICS) and emit a "
                         "superseding freeze receipt; takes the special-id "
                         "census receipt path as deviation-size evidence. "
                         "No sampling / no training / tokenizer bytes "
                         "untouched.")
    args, _unknown = ap.parse_known_args()

    if args.recount:
        recount_disabled_matching(args.recount, args.out_root)
        return

    if not args.freeze:
        raise SystemExit("tokenizer_freeze: pass --freeze explicitly "
                         "(this is the one-shot pre-step-0 freeze)")
    prior = existing_freeze_receipts(REPO)
    if prior:
        raise SystemExit(f"tokenizer_freeze: freeze receipt already exists "
                         f"({prior[-1]}) — frozen means frozen; no "
                         f"re-freeze path")

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sample_path, strata, assembly_path, manifests = build_sample(
        REPO, args.out_root, args.budget)
    sample_sha = file_sha256(sample_path)
    print(f"[sample] sha256 {sample_sha}", flush=True)

    tok_dir = os.path.dirname(sample_path)
    tok_path = train_tokenizer(sample_path, args.vocab, tok_dir)
    tok_sha = file_sha256(tok_path)
    print(f"[train] tokenizer.json sha256 {tok_sha}", flush=True)

    band = verify_reserved_band(tok_path)
    print(f"[band] reserved multimodal band verified: {band}", flush=True)

    per_source_tokens = count_tokens(tok_path, manifests, args.out_root)
    real_total = sum(per_source_tokens.values())
    assembly = json.load(open(assembly_path, encoding="utf-8"))
    heuristic_total = assembly["est_tokens_heuristic"]["total"]
    print(f"[count] TOTAL real tokens: {real_total} "
          f"(heuristic was {heuristic_total})", flush=True)

    # repo copy: the artifact every checkpoint receipt stamps
    repo_tok = os.path.join(REPO, "tokenizer", "tokenizer.json")
    os.makedirs(os.path.dirname(repo_tok), exist_ok=True)
    with open(tok_path, "rb") as fin, open(repo_tok, "wb") as fout:
        fout.write(fin.read())
    if file_sha256(repo_tok) != tok_sha:
        raise SystemExit("tokenizer_freeze: repo copy sha mismatch")

    receipt = {
        "ticket": "TOKENIZER-FREEZE-V0",
        "ts": ts,
        "spec": ("fp-22 §1: 32k vocab (fp-19 pin), trained on stratified "
                 "~1GB sample of the v0 corpus, frozen pre-step-0, "
                 "sha-stamped into every checkpoint receipt"),
        "vocab_size": args.vocab,
        "special_tokens": SPECIAL_TOKENS,
        "reserved_band": band,
        "reserved_band_basis": ("NC2 own-technique contract component 8, "
                                "v0 LOCK #1: reserved vocab band with "
                                "pre-assigned multimodal delimiter/"
                                "placeholder ids (gemma-4 pattern, "
                                "research/gemma4-unified-architecture.md); "
                                "v0 text-only — ids never produced by "
                                "training data, verified post-train"),
        "model": "ByteLevel BPE (HF tokenizers)",
        "sample_budget_bytes": args.budget,
        "sample_path": sample_path,
        "sample_sha256": sample_sha,
        "strata": strata,
        "assembly_receipt": os.path.relpath(assembly_path, REPO),
        "assembly_receipt_sha256": ASSEMBLY_RECEIPT_SHA256,
        "assembly_pin_basis": ("eng #160 AC-1 (Kai 14560): freeze runs "
                               "ONLY against the merged assembly receipt, "
                               "pinned by name + sha256, verified before "
                               "any sampling work"),
        "real_token_counts": {**per_source_tokens, "total": real_total},
        "tokens_pending_tokenizer_freeze": False,
        "resolves_heuristic": {
            "heuristic_total": heuristic_total,
            "real_total": real_total,
            "note": ("real counts from the frozen tokenizer over every "
                     "corpus doc (content tokens, no specials); the "
                     "assembly receipt's HEURISTIC-ONLY estimate is "
                     "superseded by this field"),
        },
        "tokenizer_json_sha256": tok_sha,
        "tokenizer_repo_path": os.path.relpath(repo_tok, REPO),
        "frozen_pre_step0": True,
        "determinism": ("stride sampling in frozen shard order, no RNG; "
                        "BPE train on the fixed sample — selftest pins "
                        "byte-identical double-train"),
        "sha_convention": SHA_CONVENTION,
        "no_gpu": True,
    }
    out = os.path.join(REPO, "receipts", f"tokenizer-freeze-{ts}.json")
    checked_write(out, receipt)
    print(json.dumps({"vocab_size": args.vocab, "sample_sha256": sample_sha,
                      "tokenizer_json_sha256": tok_sha,
                      "real_token_counts": receipt["real_token_counts"],
                      "reserved_band": band}, indent=2))
    print(f"[freeze] receipt: {out}")
    print("TOKENIZER_FREEZE_DONE")


if __name__ == "__main__":
    main()
