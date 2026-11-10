# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Restart running lanes onto new code at their NEXT SHARD BOUNDARY, not mid-file (lead 81769).
For each lane, watch its tick log; the first new boundary line (a finished item) after this script starts triggers scripts/kill_lane.ps1 -Only '<script> <lane>' (PID-verified lane stop), and the next tick restarts it
on the current code. Resumable lanes lose only seconds of the next item. Usage: python scripts/restart_at_boundary.py mls ccby pd12m loc pes2o pubmed"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import sys, os, time, subprocess, re
from lane_config import LANE_ROOT as ROOT
CFG = {"mls": ("bulk_lane.py mls", "backlog-bulk-mls.log", r"\bdone "), "ccby": ("bulk_lane.py ccby", "backlog-bulk-ccby.log", r"\bdone "), "pd12m": ("bulk_lane.py pd12m", "backlog-bulk-pd12m.log", r"pd12m .* chunk \d+:"),
       "loc": ("text_lane.py loc", "backlog-text-loc.log", r"\bdone "), "pes2o": ("text_lane.py pes2o", "backlog-text-pes2o.log", r"\bdone "), "pubmed": ("text_lane.py pubmed", "backlog-text-pubmed.log", r"\bdone ")}
def n_lines(path, pat):
    try: return sum(1 for l in open(path, encoding="utf-8", errors="ignore") if re.search(pat, l))
    except OSError: return 0
todo = {l: n_lines(f"{ROOT}/logs/{CFG[l][1]}", CFG[l][2]) for l in sys.argv[1:] if l in CFG}
print(time.strftime("%H:%M:%S"), "watching", todo, flush=True)
while todo:
    for l in list(todo):
        cmd, log, pat = CFG[l]
        if n_lines(f"{ROOT}/logs/{log}", pat) > todo[l]:
            r = subprocess.run(["powershell", "-NoProfile", "-File", ROOT + "/scripts/kill_lane.ps1", "-Reason", f"restart {l} at shard boundary onto the decoupled-uploader code (lead 81769)", "-Only", cmd], capture_output=True, text=True)
            print(time.strftime("%H:%M:%S"), l, "restarted at boundary:", [x for x in r.stdout.splitlines() if "STOPPED" in x or "REFUSED" in x], flush=True); del todo[l]
    time.sleep(3)
print("ALL RESTARTED", flush=True)

