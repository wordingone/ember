# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Read-only: what GREW on B: since a cutoff (default 2026-11-10 07:07 KST = 2026-11-09T22:07Z). Sums sizes of files whose creation time (st_ctime on Windows) or mtime is >= cutoff,
grouped by directory at depth N (default top 20 at depth 5 under B:/ and the 20 biggest leaf dirs). Writes logs/b-growth-census-<ts>.json. Nothing is modified.
Usage: b_growth_census.py [cutoff_epoch]"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, time, collections
CUT = float(sys.argv[1]) if len(sys.argv) > 1 else time.mktime(time.strptime("2026-11-10 07:07", "%Y-%m-%d %H:%M"))
leaf = collections.Counter(); anc = {d: collections.Counter() for d in (2, 3, 4, 5)}; nfiles = 0; tot = 0; seen = set(); skip = (r"B:\$RECYCLE.BIN", r"B:\System Volume Information")
def walk(p):
    global nfiles, tot
    try:
        with os.scandir(p) as it:
            for e in it:
                try:
                    if e.is_symlink(): continue
                    if e.is_dir(follow_symlinks=False):
                        if e.path.startswith(skip): continue
                        walk(e.path)
                    else:
                        st = e.stat(follow_symlinks=False)
                        if max(st.st_ctime, st.st_mtime) < CUT: continue
                        key = (st.st_dev, st.st_ino)
                        if st.st_nlink > 1:
                            if key in seen: continue
                            seen.add(key)
                        nfiles += 1; tot += st.st_size; parts = e.path.replace("\\", "/").split("/")
                        leaf["/".join(parts[:-1])] += st.st_size
                        for d in anc: anc[d]["/".join(parts[:d + 1])] += st.st_size
                except OSError: pass
    except OSError: pass
walk("B:\\")
g = lambda c, n=20: [(k, round(v / 2**30, 2)) for k, v in c.most_common(n)]
out = dict(cutoff=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(CUT)), files=nfiles, total_gib=round(tot / 2**30, 2), leaf_top=g(leaf), **{f"depth{d}_top": g(anc[d]) for d in anc})
fn = (LANE_ROOT + "/logs/b-growth-census-%s.json") % time.strftime("%Y%m%dT%H%M%S"); json.dump(out, open(fn, "w"), indent=1); print(fn, out["total_gib"], "GiB in", nfiles, "files")
