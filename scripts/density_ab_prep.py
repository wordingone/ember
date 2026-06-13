"""density_ab_prep.py — create 100M-token uint16 shards for density A/B bench.

Arm A (v1.1): proportional interleave of all 5 v0 sources at their actual
              corpus-v0 ratios (code=58.12%, fineweb=23.90%, wiki=10.71%,
              guten=7.26%, ledger=0.003%), packed doc-by-doc with separator.
              Replaces the incorrect v1.0 design (contiguous-window slice of
              v0-00000.bin) which was pure code_github_clean due to source-
              sequential shard ordering — both arms yielded sha-identical output.
              [SPEC AMENDMENT v1.1: contiguous-window assumption falsified;
               interleave by corpus proportion is the correct null-arm design.]

Arm B: tokenize code_github_clean/*.jsonl.zst + ledger_mit/*.jsonl.zst
       → exactly 100_000_000 content+separator tokens packed as uint16
       (curated code-only, ~100% code fraction)

Outputs (200 MiB each):
  OUT_DIR/density-ab-arm-a-100M.bin
  OUT_DIR/density-ab-arm-b-100M.bin

Prints final JSON with sha256 of each output file + manifest data.
sha(armA) == sha(armB) is an ASSERTION FAILURE — the contrast must exist.
"""

import hashlib
import json
import os
import subprocess
import sys

try:
    import zstandard  # noqa: F401
except ImportError:
    print("[prep] installing zstandard ...", flush=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "zstandard"],
                   check=True)
    import zstandard  # noqa: F401

import io
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
CORPUS_V0 = "/mnt/b/M/avir/eli/state/ember-eng/corpus-v0"
OUT_DIR    = "/mnt/b/M/avir/eli/state/ember-eng/density-ab-shards"
TOK_JSON   = f"{NC}/tokenizer/tokenizer.json"
TOKFREEZE_RECEIPT = f"{NC}/receipts/tokenizer-freeze-20260611T154111Z.json"

TARGET_TOKENS = 100_000_000
PACK_DTYPE    = "<u2"
SEPARATOR_ID  = 0
VOCAB_SIZE    = 32000
RESERVED_IDS  = set(range(1, 8))

INTERLEAVE_SEED = 42   # for manifest record; Bresenham interleave is deterministic

# Arm A proportions — from TOKEN-SHARDS-V0 receipt per_source content_tokens
# (6,973,632,300 total content tokens)
_TOTAL_CONTENT = 6_973_632_300
_SOURCE_CONTENT = {
    "code_github_clean": 4_053_253_615,
    "fineweb_edu":       1_666_837_789,
    "wikipedia_en":        747_194_257,
    "gutenberg_en":        506_114_061,
    "ledger_mit":              232_578,
}

# Compute per-source token budgets for 100M arm-a shard
_fracs = {k: v / _TOTAL_CONTENT for k, v in _SOURCE_CONTENT.items()}
_SOURCE_ORDER_A = ["code_github_clean", "fineweb_edu", "wikipedia_en",
                   "gutenberg_en", "ledger_mit"]
_raw_budgets = {k: int(TARGET_TOKENS * _fracs[k]) for k in _SOURCE_ORDER_A}
_deficit = TARGET_TOKENS - sum(_raw_budgets.values())
_raw_budgets["code_github_clean"] += _deficit   # adjust largest source
SOURCE_BUDGETS_A = _raw_budgets  # {source: token_budget}

# Source dirs for Arm B
CODE_SOURCE_DIR   = f"{CORPUS_V0}/code_github_clean"
LEDGER_SOURCE_DIR = f"{CORPUS_V0}/ledger_mit"


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _iter_docs(path):
    """Yield each document's text from a .jsonl.zst or plain .jsonl file."""
    with open(path, "rb") as fh:
        if str(path).endswith(".zst"):
            reader = zstandard.ZstdDecompressor().stream_reader(fh)
            stream = io.TextIOWrapper(reader, encoding="utf-8")
        else:
            stream = io.TextIOWrapper(fh, encoding="utf-8")
        for line in stream:
            line = line.strip()
            if not line:
                continue
            doc = json.loads(line)
            t = doc.get("text")
            if t is None:
                raise ValueError(f"{path}: doc missing 'text' field")
            yield t


def _load_tokenizer():
    """Load frozen v0 tokenizer with added-token matching DISABLED."""
    tok_sha_expected = json.load(open(TOKFREEZE_RECEIPT))["tokenizer_json_sha256"]
    if _sha256(TOK_JSON) != tok_sha_expected:
        raise ValueError("tokenizer.json sha drift vs freeze receipt")
    from tokenizers import Tokenizer
    d = json.load(open(TOK_JSON, encoding="utf-8"))
    literals = [a["content"] for a in d.get("added_tokens", [])]
    d["added_tokens"] = []
    tk = Tokenizer.from_str(json.dumps(d))
    for lit in literals:
        bad = [i for i in tk.encode(lit, add_special_tokens=False).ids if i < 8]
        if bad:
            raise ValueError(f"added-token strip failed: {lit!r} → ids {bad}")
    return tk


def _source_files(source_dir):
    return sorted(
        f"{source_dir}/{f}"
        for f in os.listdir(source_dir)
        if f.endswith(".jsonl.zst") or f.endswith(".jsonl")
    )


def _source_doc_gen(source_dir):
    """Yield (text, filepath) from all files in source_dir in sorted order."""
    for fpath in _source_files(source_dir):
        for text in _iter_docs(fpath):
            yield text, fpath


# ---------------------------------------------------------------------------
# Arm A: proportional interleave of all 5 v0 sources
# ---------------------------------------------------------------------------
def prep_arm_a(out_path):
    tk = _load_tokenizer()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    source_dirs = {
        "code_github_clean": f"{CORPUS_V0}/code_github_clean",
        "fineweb_edu":        f"{CORPUS_V0}/fineweb_edu",
        "wikipedia_en":       f"{CORPUS_V0}/wikipedia_en",
        "gutenberg_en":       f"{CORPUS_V0}/gutenberg_en",
        "ledger_mit":         f"{CORPUS_V0}/ledger_mit",
    }

    budgets   = dict(SOURCE_BUDGETS_A)   # tokens remaining per source
    written   = {k: 0 for k in _SOURCE_ORDER_A}
    gens      = {k: _source_doc_gen(source_dirs[k]) for k in _SOURCE_ORDER_A}
    done      = {k: False for k in _SOURCE_ORDER_A}
    files_seen = {k: set() for k in _SOURCE_ORDER_A}  # for manifest shas

    # Bresenham accumulator: proportional weights determine interleave order
    acc = {k: 0.0 for k in _SOURCE_ORDER_A}
    weights = {k: budgets[k] / TARGET_TOKENS for k in _SOURCE_ORDER_A}

    total_written = 0
    n_docs = 0
    fh_out = open(out_path, "wb")

    try:
        while total_written < TARGET_TOKENS:
            # Advance accumulators
            for k in _SOURCE_ORDER_A:
                if not done[k]:
                    acc[k] += weights[k]

            # Pick source with highest acc that still has budget
            active = [k for k in _SOURCE_ORDER_A if not done[k] and budgets[k] > 0]
            if not active:
                break
            pick = max(active, key=lambda k: acc[k])
            acc[pick] -= 1.0

            # Pull next doc from picked source
            try:
                text, fpath = next(gens[pick])
                files_seen[pick].add(fpath)
            except StopIteration:
                done[pick] = True
                continue

            ids_list = tk.encode(text, add_special_tokens=False).ids
            bad = [i for i in ids_list if i in RESERVED_IDS]
            if bad:
                raise ValueError(f"reserved id(s) {bad[:3]} in source text ({pick})")

            tok_arr = np.array(ids_list + [SEPARATOR_ID], dtype=PACK_DTYPE)
            remaining_src = budgets[pick]
            remaining_total = TARGET_TOKENS - total_written

            # Trim to min(source budget, total budget)
            trim = min(len(tok_arr), remaining_src, remaining_total)
            tok_arr = tok_arr[:trim]

            fh_out.write(tok_arr.tobytes())
            total_written += len(tok_arr)
            written[pick] += len(tok_arr)
            budgets[pick] -= len(tok_arr)
            n_docs += 1

            if budgets[pick] <= 0:
                done[pick] = True

            if n_docs % 10000 == 0:
                pct = 100.0 * total_written / TARGET_TOKENS
                print(f"[prep] Arm A: {total_written:,}/{TARGET_TOKENS:,} ({pct:.1f}%) docs={n_docs}", flush=True)
    finally:
        fh_out.close()

    actual_tokens = os.path.getsize(out_path) // 2
    if actual_tokens != TARGET_TOKENS:
        raise ValueError(f"Arm A shard has {actual_tokens} tokens, expected {TARGET_TOKENS}")

    sha = _sha256(out_path)
    print(f"[prep] Arm A written: {out_path} ({actual_tokens:,} tokens, {n_docs} docs) sha={sha[:16]}", flush=True)

    # Build source manifest info: shas of files actually read
    sources_manifest = {}
    for src in _SOURCE_ORDER_A:
        file_list = sorted(files_seen[src])
        sources_manifest[src] = {
            "token_budget": SOURCE_BUDGETS_A[src],
            "tokens_written": written[src],
            "files": [{"path": fp, "sha256": _sha256(fp)} for fp in file_list],
        }

    return sha, sources_manifest


# ---------------------------------------------------------------------------
# Arm B: tokenize code_github_clean + ledger_mit → 100M tokens
# ---------------------------------------------------------------------------
def prep_arm_b(out_path):
    tk = _load_tokenizer()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    code_shards = sorted(
        f"{CODE_SOURCE_DIR}/{f}"
        for f in os.listdir(CODE_SOURCE_DIR)
        if f.endswith(".jsonl.zst") or f.endswith(".jsonl")
    )
    ledger_shards = sorted(
        f"{LEDGER_SOURCE_DIR}/{f}"
        for f in os.listdir(LEDGER_SOURCE_DIR)
        if f.endswith(".jsonl.zst") or f.endswith(".jsonl")
    )
    all_shards = code_shards + ledger_shards

    total_written = 0
    BATCH = 512

    fh_out = open(out_path, "wb")
    n_docs = 0
    files_used = []

    try:
        done = False
        for shard_path in all_shards:
            if done:
                break
            files_used.append(shard_path)
            print(f"[prep] Arm B: {shard_path}", flush=True)
            doc_batch = []
            for text in _iter_docs(shard_path):
                doc_batch.append(text)
                if len(doc_batch) >= BATCH:
                    enc = tk.encode_batch(doc_batch)
                    for ids in enc:
                        ids_arr = ids.ids
                        bad = [i for i in ids_arr if i in RESERVED_IDS]
                        if bad:
                            raise ValueError(f"reserved id(s) {bad[:3]} in source text")
                        tok_arr = np.array(ids_arr + [SEPARATOR_ID], dtype=PACK_DTYPE)
                        remaining = TARGET_TOKENS - total_written
                        if tok_arr.size >= remaining:
                            fh_out.write(tok_arr[:remaining].tobytes())
                            total_written += remaining
                            done = True
                            break
                        fh_out.write(tok_arr.tobytes())
                        total_written += tok_arr.size
                        n_docs += 1
                    doc_batch = []
                    if done:
                        break
                    if total_written % 10_000_000 < BATCH * 200:
                        print(f"[prep] Arm B: {total_written:,}/{TARGET_TOKENS:,} tokens", flush=True)
            if doc_batch and not done:
                enc = tk.encode_batch(doc_batch)
                for ids in enc:
                    ids_arr = ids.ids
                    bad = [i for i in ids_arr if i in RESERVED_IDS]
                    if bad:
                        raise ValueError(f"reserved id(s) {bad[:3]} in source text")
                    tok_arr = np.array(ids_arr + [SEPARATOR_ID], dtype=PACK_DTYPE)
                    remaining = TARGET_TOKENS - total_written
                    if tok_arr.size >= remaining:
                        fh_out.write(tok_arr[:remaining].tobytes())
                        total_written += remaining
                        done = True
                        break
                    fh_out.write(tok_arr.tobytes())
                    total_written += tok_arr.size
                    n_docs += 1
    finally:
        fh_out.close()

    actual_tokens = os.path.getsize(out_path) // 2
    if actual_tokens != TARGET_TOKENS:
        raise ValueError(f"Arm B shard has {actual_tokens} tokens, expected {TARGET_TOKENS}")
    sha = _sha256(out_path)
    print(f"[prep] Arm B written: {out_path} ({actual_tokens:,} tokens, {n_docs} docs) sha={sha[:16]}", flush=True)

    # Build file sha manifest
    files_manifest = [{"path": fp, "sha256": _sha256(fp)} for fp in files_used]
    return sha, files_manifest


def main():
    arm_a_path = f"{OUT_DIR}/density-ab-arm-a-100M.bin"
    arm_b_path = f"{OUT_DIR}/density-ab-arm-b-100M.bin"

    print("[prep] === Arm A (proportional interleave v1.1) ===", flush=True)
    arm_a_sha, arm_a_sources = prep_arm_a(arm_a_path)

    print("[prep] === Arm B (code-only) ===", flush=True)
    arm_b_sha, arm_b_files = prep_arm_b(arm_b_path)

    # MANDATORY: the arms must differ — identical shas = design collapse
    if arm_a_sha == arm_b_sha:
        raise AssertionError(
            f"DENSITY-AB PREP FAILED: sha(armA) == sha(armB) = {arm_a_sha[:16]}. "
            "Arm A and Arm B are identical — the contrast does not exist. "
            "Inspect source-sequential shard layout vs proportional mix design."
        )

    result = {
        "arm_a": {
            "path": arm_a_path,
            "sha256": arm_a_sha,
            "tokens": TARGET_TOKENS,
            "design": "proportional_interleave_v1.1",
            "interleave_method": "bresenham_weighted_round_robin",
            "interleave_seed": INTERLEAVE_SEED,
            "interleave_granularity": "doc",
            "ratios": {k: round(_fracs[k], 6) for k in _SOURCE_ORDER_A},
            "sources": arm_a_sources,
        },
        "arm_b": {
            "path": arm_b_path,
            "sha256": arm_b_sha,
            "tokens": TARGET_TOKENS,
            "design": "code_only",
            "files_used": arm_b_files,
        },
        "spec_amendment": (
            "v1.1: contiguous-window-of-v0-00000.bin assumption falsified. "
            "v0 shard stream is source-sequential by fp22_row; shards 0-15 are pure "
            "code_github_clean. Proportional interleave required for valid null arm."
        ),
    }
    print(json.dumps(result, indent=2))
    print("DENSITY_AB_PREP_DONE")


if __name__ == "__main__":
    main()
