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

Fail-closed interlocks:
  - refuses to run without corpus-manifests/ + a green assembly receipt
    (eng-36 must be GATED/merged first — launch order);
  - refuses if a freeze receipt already exists (frozen = frozen; one
    tokenizer for v0, no re-freeze path);
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
SPECIAL_TOKENS = ["<|endoftext|>"]  # minimal; documented in the receipt

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


def latest_assembly_receipt(repo):
    cands = sorted(glob.glob(
        os.path.join(repo, "receipts", "eng36-assembly-*.json")))
    if not cands:
        raise SystemExit("tokenizer_freeze: no eng36-assembly receipt — "
                         "the corpus is not assembly-verified")
    return cands[-1]


def existing_freeze_receipts(repo):
    return sorted(glob.glob(
        os.path.join(repo, "receipts", "tokenizer-freeze-*.json")))


def build_sample(repo, out_root, budget_total):
    """Stratified sample across all sources. Returns
    (sample_path, strata_rows, assembly_path)."""
    manifests = load_manifests(repo)
    assembly_path = latest_assembly_receipt(repo)
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
    return sample_path, strata, assembly_path


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-root", default=OUT_ROOT_DEFAULT)
    ap.add_argument("--budget", type=int, default=SAMPLE_BUDGET_BYTES)
    ap.add_argument("--vocab", type=int, default=VOCAB_SIZE)
    ap.add_argument("--freeze", action="store_true",
                    help="required to run — this writes the ONE frozen "
                         "v0 tokenizer (no re-freeze path)")
    args, _unknown = ap.parse_known_args()

    if not args.freeze:
        raise SystemExit("tokenizer_freeze: pass --freeze explicitly "
                         "(this is the one-shot pre-step-0 freeze)")
    prior = existing_freeze_receipts(REPO)
    if prior:
        raise SystemExit(f"tokenizer_freeze: freeze receipt already exists "
                         f"({prior[-1]}) — frozen means frozen; no "
                         f"re-freeze path")

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sample_path, strata, assembly_path = build_sample(
        REPO, args.out_root, args.budget)
    sample_sha = file_sha256(sample_path)
    print(f"[sample] sha256 {sample_sha}", flush=True)

    tok_dir = os.path.dirname(sample_path)
    tok_path = train_tokenizer(sample_path, args.vocab, tok_dir)
    tok_sha = file_sha256(tok_path)
    print(f"[train] tokenizer.json sha256 {tok_sha}", flush=True)

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
        "model": "ByteLevel BPE (HF tokenizers)",
        "sample_budget_bytes": args.budget,
        "sample_path": sample_path,
        "sample_sha256": sample_sha,
        "strata": strata,
        "assembly_receipt": os.path.relpath(assembly_path, REPO),
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
                      "strata": [{s['source']: s['bytes_sampled']}
                                 for s in strata]}, indent=2))
    print(f"[freeze] receipt: {out}")
    print("TOKENIZER_FREEZE_DONE")


if __name__ == "__main__":
    main()
