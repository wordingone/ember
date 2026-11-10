# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#2449 / #1947: every packed/<name> vs the ADD-ON held-out index (A-heldout-2, B-heldout-1, F-heldout-1, H-heldout-1; build_heldout_index_addon.py), unsampled (HS_SAMP=1, the same signature as the full index).
Code/GitHub packs (name contains github or stack) are read exhaustively; every other pack by a deterministic stride sample of up to SWEEP_DOCS docs (default 200000). A doc is a hit when at least one of its sentence hashes is in the index; hits are named (first 20).
CPU-only, read-only, 4 worker processes (one pack each). Receipt (resumable per pack): logs/overlap-addon-sweep-20261110.json.
Usage: python scripts/overlap_addon_sweep.py [--only NAME ...]"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, glob, time
os.environ["HS_SAMP"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, overlap_gate as G
from common import gram_hashes, overlap
from multiprocessing import Pool
OUT = (LANE_ROOT + "/logs/overlap-addon-sweep-20261110.json"); CAP = int(os.environ.get("SWEEP_DOCS", "200000"))
IDXF = (LANE_ROOT + "/heldout-index-full/addon/heldout-sent-xxh64-full-addon-ABFH.npy")
def one(d):
    name = os.path.basename(d); t0 = time.time(); idx = np.load(IDXF, mmap_mode="r")
    exhaustive = any(k in name for k in ("github", "stack")); total = sum(1 for _ in G.iter_objects(d)); stride = 1 if exhaustive else max(1, total // CAP)
    n = hh = 0; hits = []
    for i, r in enumerate(G.iter_objects(d)):
        if i % stride: continue
        n += 1; o = overlap(idx, gram_hashes(r["text"]))
        if o: hh += 1; hits.append((G.ns_key(name, r["id"]), int(o)))
    return name, dict(docs_total=total, docs_checked=n, stride=stride, exhaustive=exhaustive, docs_heldout_hit=hh, hits=sorted(hits, key=lambda x: -x[1])[:20], secs=round(time.time() - t0))
if __name__ == "__main__":
    only = sys.argv[sys.argv.index("--only") + 1:] if "--only" in sys.argv else None
    res = json.load(open(OUT)) if os.path.exists(OUT) else {}
    packs = [d.replace(chr(92), "/").rstrip("/") for d in sorted(glob.glob((LANE_ROOT + "/packed/*/")))]
    packs = [d for d in packs if glob.glob(d + "/objects/*.jsonl.zst") and os.path.exists(d + "/receipt.json") and os.path.basename(d) not in res and (not only or os.path.basename(d) in only)]
    print(len(packs), "packs to sweep", flush=True)
    with Pool(4) as pool:
        for name, r in pool.imap_unordered(one, packs):
            res[name] = r; json.dump(res, open(OUT, "w"), indent=1); print(name, r["docs_total"], r["docs_checked"], r["docs_heldout_hit"], r["secs"], "s", flush=True)
    print("SWEEP DONE", len(res), "packs; heldout-hit docs", sum(v["docs_heldout_hit"] for v in res.values()), flush=True)
