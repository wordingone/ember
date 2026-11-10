# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, M_ROOT
import os, re, glob, json, sys
from multiprocessing import Pool
R = re.compile(r"<id>([^<]+)</id>\s*<created>([^<]+)</created>(?:\s*<updated>([^<]+)</updated>)?")
def work(p):
    out = {}
    with open(p, encoding="utf-8", errors="ignore") as f:
        t = f.read()
    for m in R.finditer(t):
        out[m.group(1)] = (m.group(2), m.group(3) or m.group(2))
    return out
if __name__ == "__main__":
    fl = sorted(glob.glob((M_ROOT + "/data/corpus/_arxiv-metadata/pages/*/*.xml")))
    print(len(fl), "files", flush=True)
    res = {}
    with Pool(3) as p:
        for i, o in enumerate(p.imap_unordered(work, fl, chunksize=8)):
            res.update(o)
            if i % 500 == 0: print(i, len(res), flush=True)
    json.dump(res, open((LANE_ROOT + "/audit/arxiv-dates.json"), "w"))
    print("DONE", len(res), flush=True)
