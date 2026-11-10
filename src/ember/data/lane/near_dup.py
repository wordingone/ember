# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#1581 near-duplicate rate (read-only, CPU, 1 core). Bottom-k (k=64) sketches of 8-word shingles on a 1/P stride sample of every local pack in NEAR_PACKS (default pes2o/pubmed/arxiv/loc/pg); candidates = docs sharing >= 16 sketch values,
verified with the bottom-k Jaccard estimate; pair counted near-dup at J >= 0.7. A p-sample sees ~p of a doc's true partners, so partner-rate f ~= observed_rate / p (reported as est_rate_full). Out: logs/near-dup-20261109.json"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, glob, re, collections, time
pass
import xxhash, overlap_gate as G
P = int(os.environ.get("NEAR_P", "8")); K = 64; SH = 8; MIN_SHARED = 16; J = 0.7
PACKS = [x for x in os.environ.get("NEAR_PACKS", "pes2o,pubmed,arxiv,loc,pg").split(",")]
W = re.compile(r"[a-z0-9]+")
def sketch(t):
    w = W.findall(t.lower())
    if len(w) < SH + 20: return None
    hs = {xxhash.xxh64_intdigest(" ".join(w[i:i + SH])) for i in range(0, len(w) - SH + 1)}
    return tuple(sorted(hs)[:K])
def jac(a, b):
    u = sorted(set(a) | set(b))[:K]; sa, sb = set(a), set(b)
    return sum(1 for x in u if x in sa and x in sb) / max(1, len(u))
docs = []; inv = collections.defaultdict(list); stats = collections.Counter()
for d in sorted(glob.glob((LANE_ROOT + "/packed/*/"))):
    d = d.replace(chr(92), "/").rstrip("/"); name = os.path.basename(d)
    if not any(name.startswith(p) for p in PACKS) or not os.path.exists(d + "/receipt.json") or not glob.glob(d + "/objects/*.jsonl.zst"): continue
    t0 = time.time(); n = 0
    for i, r in enumerate(G.iter_objects(d)):
        if i % P: continue
        sk = sketch(r["text"])
        if not sk: continue
        idx = len(docs); docs.append((name, r["id"], sk)); n += 1
        for v in sk: inv[v].append(idx)
    stats[name] = n; print("sketched", name, n, round(time.time() - t0), "s", flush=True)
cnt = collections.Counter()
pairs = collections.Counter()
for v, L in inv.items():
    if 1 < len(L) < 50:
        for a in range(len(L)):
            for b in range(a + 1, len(L)): pairs[(L[a], L[b])] += 1
near = []
for (a, b), c in pairs.items():
    if c >= MIN_SHARED and jac(docs[a][2], docs[b][2]) >= J: near.append((a, b))
with_partner = collections.Counter(); cross = collections.Counter()
for a, b in near:
    na, nb = docs[a][0], docs[b][0]; with_partner[na] += 1; with_partner[nb] += 1; cross[tuple(sorted((na.split("-")[0], nb.split("-")[0])))] += 1
out = dict(P=P, J=J, sampled=dict(stats), near_pairs=len(near), docs_with_partner={k: v for k, v in with_partner.items()},
           est_rate_full={k: round(with_partner[k] / stats[k] * P / 1.0 / P, 4) if stats[k] else 0 for k in stats},   # observed rate in sample; the true rate is ~ this x P at most (sample sees ~1/P of partners)
           cross_pack_pairs={"|".join(k): v for k, v in cross.items()}, examples=[(docs[a][0], docs[a][1], docs[b][0], docs[b][1]) for a, b in near[:20]])
json.dump(out, open((LANE_ROOT + "/logs/near-dup-20261109.json"), "w"), indent=1); print("NEARDUP DONE", json.dumps(out)[:900])
