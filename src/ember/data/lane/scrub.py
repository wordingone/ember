# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Scrub a docs jsonl.zst against the FULL heldout sentence index.
Rule (lead 81151): drop docs with >DROP_FRAC of eligible sentences in heldout; in kept docs remove every hit sentence.
Usage: scrub.py IN.jsonl.zst OUT.jsonl.zst [LIMIT]
Eligible sentence = >=8 words after lowercase+whitespace-normalize (same segmenter as common.py). Unsampled index.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, M_ROOT
import sys, os, io, re, json, time
import numpy as np, xxhash, zstandard
from tokenizers import Tokenizer
SRC, OUT = sys.argv[1], sys.argv[2]
LIMIT = int(sys.argv[3]) if len(sys.argv) > 3 else 10**12
IDXP = os.environ.get("HELDOUT_IDX", (LANE_ROOT + "/heldout-index-full/heldout-sent-xxh64-full.npy"))
DROP_FRAC = 0.25
MINW = 8
IDX = np.load(IDXP, mmap_mode="r")
tk = Tokenizer.from_file((M_ROOT + "/custody-tokenizer-2c557/tokenizer-2c557.json"))
SPLIT = re.compile(r"((?<=[.!?])\s+|\n+)")
WS = re.compile(r"\s+")

def seg_hash(seg):
    n = WS.sub(" ", seg.lower()).strip()
    if n.count(" ") < MINW - 1:
        return None
    return xxhash.xxh64_intdigest(n)

EXTRA = [np.load(p, mmap_mode="r") for p in os.environ.get("HELDOUT_EXTRA", "").split(",") if p]  # extra heldout hash arrays (sorted uint64 .npy)

def hit_flags(hs):
    a = np.array(hs, dtype=np.uint64)
    pos = np.searchsorted(IDX, a)
    pos[pos >= IDX.size] = IDX.size - 1
    fl = (IDX[pos] == a)
    for X in EXTRA:
        p2 = np.searchsorted(X, a); p2[p2 >= X.size] = X.size - 1
        fl |= (X[p2] == a)
    return fl

def scrub_doc(text):
    parts = SPLIT.split(text)  # even idx = segments, odd = separators
    segs = parts[0::2]; seps = parts[1::2] + [""]
    hs = [seg_hash(s) for s in segs]
    elig = [i for i, h in enumerate(hs) if h is not None]
    if not elig:
        return text, 0, 0, []
    fl = hit_flags([hs[i] for i in elig])
    hit_idx = {elig[j] for j in range(len(elig)) if fl[j]}
    frac = len(hit_idx) / len(elig)
    removed = [segs[i] for i in sorted(hit_idx)]
    if frac > DROP_FRAC:
        return None, len(elig), len(hit_idx), removed
    if not hit_idx:
        return text, len(elig), 0, []
    out = []
    for i, (s, sp) in enumerate(zip(segs, seps)):
        if i in hit_idx:
            continue
        out.append(s + sp)
    t = "".join(out).strip()
    return t, len(elig), len(hit_idx), removed

def main():
    t0 = time.time()
    st = dict(docs_in=0, docs_dropped=0, docs_kept=0, docs_scrubbed=0, sent_elig=0, sent_hit=0, sent_removed_in_kept=0,
              tok_in_dropped=0, tok_removed_scrub=0, tok_out=0, bytes_out=0, docs_too_short_after=0)
    cctx = zstandard.ZstdCompressor(level=6)
    with open(SRC, "rb") as f, open(OUT, "wb") as fo, cctx.stream_writer(fo) as w:
        r = io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(f), encoding="utf-8")
        for line in r:
            if st["docs_in"] >= LIMIT:
                break
            d = json.loads(line); st["docs_in"] += 1
            t, ne, nh, removed = scrub_doc(d["text"])
            st["sent_elig"] += ne; st["sent_hit"] += nh
            if t is None:
                st["docs_dropped"] += 1
                st["tok_in_dropped"] += len(tk.encode(d["text"]).ids)
                continue
            if nh:
                st["docs_scrubbed"] += 1; st["sent_removed_in_kept"] += nh
                st["tok_removed_scrub"] += sum(len(tk.encode(x).ids) for x in removed)
            if len(t.split()) < 120:
                st["docs_too_short_after"] += 1
                continue
            d["text"] = t
            n = len(tk.encode(t).ids)
            d["tokens"] = n; d["scrubbed_sents"] = nh
            st["docs_kept"] += 1; st["tok_out"] += n; st["bytes_out"] += len(t.encode())
            w.write((json.dumps(d, ensure_ascii=False) + "\n").encode())
    st["secs"] = round(time.time() - t0)
    print(json.dumps(st))

main()
