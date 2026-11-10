# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Debug: which decompressed parts make TruffleHog exit rc=1 every time? Usage: th_bisect.py final.jsonl.zst [tries]. Prints part index, size, rc list. No values."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import sys, os, shutil, subprocess
pass; import th_gate
src = sys.argv[1]; tries = int(sys.argv[2]) if len(sys.argv) > 2 else 5
d = (LANE_ROOT + "/scratch/thbisect"); shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
for p in th_gate._expand(src, d, 0):
    rcs = []
    for _ in range(tries):
        r = subprocess.run([th_gate.TH, "filesystem", p, "--json", "--no-update", "--no-verification", "--results=" + th_gate.RESULTS, "--concurrency=1"], capture_output=True, stdin=subprocess.DEVNULL)
        rcs.append(r.returncode)
        if r.returncode == 0: break
    print(os.path.basename(p), os.path.getsize(p) >> 20, "MB", rcs, flush=True)
shutil.rmtree(d, ignore_errors=True)
