# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#1581 data-quality stats (read-only, CPU). Per local pack with receipt+objects: stride sample (default 3000 docs): chars p10/p50/p90, short-doc share (<200 chars), non-alpha ratio (mean), repeated-line ratio (mean share of duplicate lines inside a doc),
in-sample exact-dup rate (normalized text hash), flags vs thresholds. Output logs/pack-quality-20261109.json; prints a table."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, glob, time
pass
import numpy as np, overlap_gate as G
N = int(os.environ.get("QUAL_DOCS", "3000")); OUT = (LANE_ROOT + "/logs/pack-quality-20261109.json")
res = json.load(open(OUT)) if os.path.exists(OUT) else {}
for d in sorted(glob.glob((LANE_ROOT + "/packed/*/"))):
    d = d.replace(chr(92), "/").rstrip("/"); name = os.path.basename(d)
    if name in res or not os.path.exists(d + "/receipt.json") or not glob.glob(d + "/objects/*.jsonl.zst"): continue
    try:
        rc = json.load(open(d + "/receipt.json")); total = rc.get("docs") or 0
        stride = max(1, total // N) if total else 1
        L = []; sh = []; na = []; rep = []; seen = set(); dup = 0; n = 0
        for i, r in enumerate(G.iter_objects(d)):
            if i % stride: continue
            t = r["text"]; n += 1; L.append(len(t)); sh.append(len(t) < 200)
            head = t[:20000]; na.append(1 - sum(c.isalpha() or c.isspace() for c in head) / max(1, len(head)))
            ls = [x.strip() for x in t.split("\n") if len(x.strip()) > 20]; rep.append(1 - len(set(ls)) / len(ls) if ls else 0)
            h = G.norm_hash(t)
            if h in seen: dup += 1
            seen.add(h)
            if n >= N * 2: break
        if not n: continue
        a = np.array(L); row = dict(docs=total, sampled=n, chars_p10=int(np.percentile(a, 10)), chars_p50=int(np.percentile(a, 50)), chars_p90=int(np.percentile(a, 90)), short_share=round(float(np.mean(sh)), 4),
                                    nonalpha=round(float(np.mean(na)), 4), repeated_line=round(float(np.mean(rep)), 4), exact_dup_rate=round(dup / n, 4))
        row["flags"] = [f for f, c in (("short>10%", row["short_share"] > .10), ("nonalpha>40%", row["nonalpha"] > .40), ("repline>20%", row["repeated_line"] > .20), ("dup>1%", row["exact_dup_rate"] > .01)) if c]
        res[name] = row
    except Exception as e:
        res[name] = dict(error=type(e).__name__ + ": " + str(e)[:140])
    json.dump(res, open(OUT, "w"), indent=1); print(name, res[name], flush=True)
print("QUALITY DONE", len(res), "packs; flagged:", [k for k, v in res.items() if v.get("flags")])
