# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#1947: unsampled (HS_SAMP=1) heldout re-check of every packed pack that still has LOCAL objects (stride-free: first MAXDOCS docs), against full index + wiki-heldout-2M + arxiv heldout. Sequential, 1 process, no network.
Out: logs/heldout-unsampled-20261109.json {pack: {docs, hit_docs, hit_sentences}}; resumable (skips done packs). Packs without local objects are listed as 'no-local-objects' (their scrub is evidenced by the lane scrub logs: scrub.py = unsampled FULL index)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, subprocess, glob
OUT = (LANE_ROOT + "/logs/heldout-unsampled-20261109.json"); MAX = sys.argv[1] if len(sys.argv) > 1 else "60000"
res = json.load(open(OUT)) if os.path.exists(OUT) else {}
for d in sorted(glob.glob((LANE_ROOT + "/packed/*/"))):
    n = os.path.basename(d.replace(chr(92), "/").rstrip("/"))
    if n in res: continue
    if not os.path.isdir(d + "/objects") or not os.listdir(d + "/objects") or not os.path.exists(d + "/receipt.json"):
        res[n] = "no-local-objects"; continue
    r = subprocess.run([sys.executable, (LANE_ROOT + "/scripts/heldout_check_pack.py"), n, MAX], capture_output=True, text=True)
    res[n] = dict(rc=r.returncode, out=r.stdout.strip()[-300:], err=r.stderr.strip()[-200:])
    json.dump(res, open(OUT, "w"), indent=1); print(n, res[n]["rc"], res[n]["out"][-120:], flush=True)
json.dump(res, open(OUT, "w"), indent=1); print("DONE", sum(1 for v in res.values() if isinstance(v, dict) and v["rc"] == 0), "clean;", [k for k, v in res.items() if isinstance(v, dict) and v["rc"] != 0], "FLAGGED")
