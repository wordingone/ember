# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, M_ROOT
import os, sys, json, time
def size(p):
    t = 0; seen = set()
    for dp, dn, fn in os.walk(p):
        for f in fn:
            try:
                st = os.stat(os.path.join(dp, f))
                k = (st.st_dev, st.st_ino)
                if k in seen: continue
                seen.add(k); t += st.st_size
            except OSError: pass
    return t
out = {}
bases = sys.argv[1:] or [M_ROOT]
for r in bases:
    for e in sorted(os.scandir(r), key=lambda e: e.name):
        if e.is_dir(follow_symlinks=False):
            out[e.path] = size(e.path) / 2**30; print(f"{out[e.path]:8.1f} GiB {e.path}", flush=True)
json.dump(out, open((LANE_ROOT + "/logs/b-usage.json"), "w"), indent=1)
