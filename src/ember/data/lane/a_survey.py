# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Read-only survey of A: (lead 82016): per top-level dir: bytes, files, newest/oldest mtime, hardlinked files (st_nlink>1), largest 3 files. Out logs/a-survey-20261109.json. No writes under A:."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, time
out = {}
for d in sorted(os.listdir("A:/")):
    p = "A:/" + d
    if d in ("$RECYCLE.BIN", "System Volume Information"): continue
    if not os.path.isdir(p):
        try: out[d] = dict(bytes=os.path.getsize(p), files=1, kind="file")
        except OSError: pass
        continue
    tot = n = nl = 0; newest = 0; oldest = 1e18; big = []
    for dp, dn, fs in os.walk(p):
        for f in fs:
            fp = os.path.join(dp, f)
            try: st = os.lstat(fp)
            except OSError: continue
            tot += st.st_size; n += 1; nl += st.st_nlink > 1; newest = max(newest, st.st_mtime); oldest = min(oldest, st.st_mtime)
            if len(big) < 3 or st.st_size > big[-1][0]: big.append((st.st_size, fp)); big.sort(reverse=True); big = big[:3]
    out[d] = dict(gib=round(tot / 2**30, 2), files=n, hardlinked=nl, newest=time.strftime("%Y-%m-%d", time.gmtime(newest)) if n else None, oldest=time.strftime("%Y-%m-%d", time.gmtime(oldest)) if n else None, big=[(round(s / 2**30, 2), f) for s, f in big])
    print(d, out[d]["gib"], "GiB", n, "files", flush=True)
    json.dump(out, open((LANE_ROOT + "/logs/a-survey-20261109.json"), "w"), indent=1)
print("SURVEY DONE")
