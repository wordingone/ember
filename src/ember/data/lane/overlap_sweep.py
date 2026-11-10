# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#1947 overlap sweep (CPU-only, read-only): every packed/<name> vs (a) the union docs index (other packs' ids + normalized-text hash) and (b) the sampled heldout sentence index (+ extras).
Deterministic stride sample of up to SWEEP_DOCS docs per pack (default 30000); counts per pack, any hit named (first 20). Receipt: logs/overlap-sweep-20261109.json (resumable per pack)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, glob, time, sqlite3
pass
import numpy as np, overlap_gate as G
from common import gram_hashes, overlap
OUT = (LANE_ROOT + "/logs/overlap-sweep-20261109.json"); CAP = int(os.environ.get("SWEEP_DOCS", "30000"))
IDX = np.load((LANE_ROOT + "/heldout-index/heldout-sent-xxh64-s4.npy"), mmap_mode="r")
EX = [np.load(p, mmap_mode="r") for p in G_EX] if (G_EX := [(LANE_ROOT + "/heldout-index/wiki-heldout-2M.npy"), (LANE_ROOT + "/arxiv/heldout-pdf-sent-hashes.npy")]) else []
res = json.load(open(OUT)) if os.path.exists(OUT) else {}
def count_docs(d):
    n = 0
    try:
        for l in open(d + "/docs-index.jsonl", "rb"): n += 1
    except Exception: pass
    return n
for d in sorted(glob.glob((LANE_ROOT + "/packed/*/"))):
    d = d.replace(chr(92), "/").rstrip("/"); name = os.path.basename(d)
    if name in res or not glob.glob(d + "/objects/*.jsonl.zst") or not os.path.exists(d + "/receipt.json"): continue
    try:
        t0 = time.time(); c = G._db(); n = dd = hh = 0; hits = []; total = 0
        objs = list(glob.glob(d + "/objects/*.jsonl.zst")); 
        for r in G.iter_objects(d):
            total += 1
        stride = max(1, total // CAP)
        for i, r in enumerate(G.iter_objects(d)):
            if i % stride: continue
            n += 1; k = G.ns_key(name, r["id"])
            row = c.execute("select src from docs where id_key=? and src<>? limit 1", (k, name)).fetchone() or c.execute("select src from docs where nh=? and src<>? limit 1", (G.norm_hash(r["text"]), name)).fetchone()
            if row: dd += 1; hits.append(("doc", k, row[0]))
            hs = gram_hashes(r["text"]); o = overlap(IDX, hs) + sum(overlap(e, hs) for e in EX)
            if o: hh += 1; hits.append(("heldout", k, o))
        c.close()
    except Exception as e:
        res[name] = dict(error=type(e).__name__+': '+str(e)[:160]); json.dump(res, open(OUT, 'w'), indent=1); print(name, 'ERROR', res[name]['error'], flush=True); continue
    res[name] = dict(docs_total=total, docs_checked=n, stride=stride, docs_cross_pack_dup=dd, docs_heldout_hit=hh, hits=hits[:20], secs=round(time.time() - t0))
    json.dump(res, open(OUT, "w"), indent=1); print(name, res[name]["docs_total"], n, dd, hh, flush=True)
print("SWEEP DONE", len(res), "packs; cross-pack dups", sum(v["docs_cross_pack_dup"] for v in res.values()), "heldout-hit docs", sum(v["docs_heldout_hit"] for v in res.values()))
