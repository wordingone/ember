# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Read-only report (lead 81875 rule 2): packed sets that are HF-verified, NOT in the chain's bound-sets list (<m-root>/avir/<training>/state/bound-sets.json), with real reclaimable bytes (st_nlink == 1 only;
training: never delete a file with st_nlink > 1). Deletes nothing: lead's yes + manifest first (81705)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, M_ROOT, SEAT_TRAIN
import json, os, glob
b = json.load(open((M_ROOT + "/avir/" + SEAT_TRAIN + "/state/bound-sets.json"))); bound = set(b["bound"] if isinstance(b, dict) and "bound" in b else (b.get("sets", []) if isinstance(b, dict) else b))
ap = json.load(open((LANE_ROOT + "/loops/approved-uploads.json"))); ver = {i["name"][6:] if i["name"].startswith("train-") else i["name"] for i in ap if i.get("verified")}
rows = []
for d in sorted(glob.glob((LANE_ROOT + "/packed/*/"))):
    n = os.path.basename(os.path.normpath(d)); t = t1 = 0
    for dp, _, fs in os.walk(d):
        for f in fs:
            s = os.stat(os.path.join(dp, f)); t += s.st_size; t1 += s.st_size if s.st_nlink == 1 else 0
    rows.append((n, n in bound, n in ver, t / 2**30, t1 / 2**30))
free = [r for r in rows if not r[1] and r[2]]
print("bound sets:", len(bound), "| local dirs:", len(rows), "| bound GiB", round(sum(r[3] for r in rows if r[1]), 1))
print("DROPPABLE (unbound + HF-verified):", len(free), "sets, dir", round(sum(r[3] for r in free), 2), "GiB, reclaimable (nlink==1)", round(sum(r[4] for r in free), 2), "GiB")
for r in free: print(f"  {r[0]}  dir {r[3]:.2f}  reclaim {r[4]:.2f}")
print("unbound NOT yet HF-verified (kept):", [r[0] for r in rows if not r[1] and not r[2]])
