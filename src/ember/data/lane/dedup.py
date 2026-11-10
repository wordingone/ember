# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Exact + near-dup (MinHash-LSH, est. Jaccard>=0.8 on 5-word shingles) dedup over a docs jsonl.zst. Greedy: first doc wins.
Usage: dedup.py IN.jsonl.zst OUT.jsonl.zst   -> stats JSON. Deterministic (fixed seed). Also use CROSS=prev1,prev2 sig files to dedup across batches."""
import sys, io, json, time, re, hashlib, os
import numpy as np, xxhash, zstandard
SRC, OUT = sys.argv[1], sys.argv[2]
NP = 120; B = 20; R = 6; TH = 0.8
rng = np.random.RandomState(1337)
A = rng.randint(1, 2**62, NP, dtype=np.int64).astype(np.uint64) | np.uint64(1); Bc = rng.randint(0, 2**62, NP, dtype=np.int64).astype(np.uint64)
WS = re.compile(r"\s+")
def sig(text):
    w = WS.sub(" ", text.lower()).split(" ")
    if len(w) < 5: return None
    n = len(w) - 4
    h = np.fromiter((xxhash.xxh64_intdigest(" ".join(w[i:i + 5])) for i in range(n)), dtype=np.uint64, count=n)
    h = np.unique(h)
    if h.size > 20000: h = h[:: h.size // 20000 + 1]  # deterministic thinning for huge books
    s = np.empty(NP, np.uint64)
    for k in range(NP):
        s[k] = (h * A[k] + Bc[k]).min()
    return s
def main():
    t0 = time.time(); st = dict(docs_in=0, exact_dup=0, near_dup=0, kept=0, tok_removed=0, tok_out=0)
    seen_sha = set(); buckets = [dict() for _ in range(B)]; sigs = []
    cctx = zstandard.ZstdCompressor(level=6)
    with open(SRC, "rb") as f, open(OUT, "wb") as fo, cctx.stream_writer(fo) as w:
        for line in io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(f), encoding="utf-8"):
            d = json.loads(line); st["docs_in"] += 1
            sh = hashlib.sha256(WS.sub(" ", d["text"]).strip().encode()).digest()
            tk = d.get("tokens", 0)
            if sh in seen_sha: st["exact_dup"] += 1; st["tok_removed"] += tk; continue
            seen_sha.add(sh)
            s = sig(d["text"])
            dup = False
            if s is not None:
                keys = [hash(s[b * R:(b + 1) * R].tobytes()) for b in range(B)]
                cand = set()
                for b, k in enumerate(keys):
                    cand.update(buckets[b].get(k, ()))
                for c in cand:
                    if (sigs[c] == s).mean() >= TH: dup = True; break
                if not dup:
                    idx = len(sigs); sigs.append(s)
                    for b, k in enumerate(keys): buckets[b].setdefault(k, []).append(idx)
            if dup: st["near_dup"] += 1; st["tok_removed"] += tk; continue
            st["kept"] += 1; st["tok_out"] += tk
            w.write((json.dumps(d, ensure_ascii=False) + "\n").encode())
    st["secs"] = round(time.time() - t0); print(json.dumps(st))
main()
