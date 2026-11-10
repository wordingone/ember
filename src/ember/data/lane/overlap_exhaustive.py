# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#1947 exhaustive (non-sampled) overlap count for ONE packed set (CPU-only, read-only).
Usage: python scripts/overlap_exhaustive.py <pack name>
Every doc of packed/<name> is checked (no stride): (a) cross-pack duplicate against the union docs index by namespaced id key or normalized-text hash, counted by matching source pack and by match kind; (b) heldout sentence-gram overlap against the heldout indexes.
Receipt: logs/overlap-exhaustive-<name>.json (counts, the first 20 hits; no text). Same checks as overlap_sweep.py, minus the sampling cap."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, glob, time, collections
pass
import numpy as np, overlap_gate as G
from common import gram_hashes, overlap
name = sys.argv[1]
d = (LANE_ROOT + "/packed/") + name
assert glob.glob(d + "/objects/*.jsonl.zst") and os.path.exists(d + "/receipt.json"), "no local objects or receipt for " + name
OUT = (LANE_ROOT + "/logs/overlap-exhaustive-") + name + ".json"
IDX = np.load((LANE_ROOT + "/heldout-index/heldout-sent-xxh64-s4.npy"), mmap_mode="r")
EX = [np.load(p, mmap_mode="r") for p in [(LANE_ROOT + "/heldout-index/wiki-heldout-2M.npy"), (LANE_ROOT + "/arxiv/heldout-pdf-sent-hashes.npy")]]
t0 = time.time(); c = G._db(); total = dd_id = dd_nh = dd_any = hh = 0; by_src = collections.Counter(); hits = []
for r in G.iter_objects(d):
    total += 1; k = G.ns_key(name, r["id"])
    a = c.execute("select src from docs where id_key=? and src<>? limit 1", (k, name)).fetchone()
    b = c.execute("select src from docs where nh=? and src<>? limit 1", (G.norm_hash(r["text"]), name)).fetchone()
    if a: dd_id += 1
    if b: dd_nh += 1
    if a or b:
        dd_any += 1; by_src[(a or b)[0]] += 1
        if len(hits) < 20: hits.append(("doc", k, (a or b)[0], "id" if a else "nh"))
    hs = gram_hashes(r["text"]); o = overlap(IDX, hs) + sum(overlap(e, hs) for e in EX)
    if o:
        hh += 1
        if len(hits) < 20: hits.append(("heldout", k, o))
c.close()
res = dict(pack=name, docs_total=total, docs_checked=total, sampled=False, docs_cross_pack_dup=dd_any, dup_by_id_key=dd_id, dup_by_text_hash=dd_nh, dup_pct=round(100.0 * dd_any / max(1, total), 3), dup_by_source_pack=dict(by_src.most_common(20)), docs_heldout_hit=hh, hits=hits, secs=round(time.time() - t0))
json.dump(res, open(OUT, "w"), indent=1)
print(json.dumps({k: v for k, v in res.items() if k != "hits"}))
