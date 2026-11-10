# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import sys, json, hashlib, csv
from concurrent.futures import ThreadPoolExecutor
f = sys.argv[1]
rows = [l.rstrip("\n").split("\t") for l in open(f)][1:]
rows = [r for r in rows if r[0] == "NO-HF-COPY"]
def h(r):
    p = r[4]; s = hashlib.sha256()
    with open(p, "rb") as fh:
        for c in iter(lambda: fh.read(16 << 20), b""): s.update(c)
    return dict(path=p, gib=float(r[1]), sha=s.hexdigest())
with ThreadPoolExecutor(4) as ex: out = list(ex.map(h, rows))
json.dump(out, open((LANE_ROOT + "/logs/nohf-hashes.json"), "w"), indent=1); print("done", len(out))
