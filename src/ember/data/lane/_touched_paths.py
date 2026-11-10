# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""List every path under checkpoint/child dirs that data deleted (from the manifests) since 2026-11-08 18:00 KST; writes logs/touched-paths-20261109.txt and prints counts."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import json, os, collections
M = (LANE_ROOT + "/logs/manifests-20261108/")
rows = []
for f in ("ckpt-delete-manifest.jsonl", "ckpt-lineage-delete-manifest.jsonl"):
    if os.path.exists(M + f):
        for l in open(M + f):
            if l.strip():
                r = json.loads(l); r["_m"] = f; rows.append(r)
seen = {}
for r in rows:
    seen[r["path"].replace(chr(92), "/")] = r
with open((LANE_ROOT + "/logs/touched-paths-20261109.txt"), "w") as o:
    o.write("# DELETED by data (os.remove, manifest first). Created/renamed/re-linked/written under checkpoint dirs: NONE (hf upload reads only; round-trip wrote to tmp-roundtrip, not a child dir).\n")
    for p, r in sorted(seen.items()):
        o.write("%s\t%d\t%s\t%s\n" % (p, r["size"], r.get("sha256", ""), r["_m"]))
c = collections.Counter(r["_m"] for r in seen.values())
print(len(seen), dict(c), round(sum(r["size"] for r in seen.values()) / 2 ** 30, 1), "GiB")
