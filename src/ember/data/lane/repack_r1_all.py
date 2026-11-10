# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Driver (training 81727): rebuild each wikipedia pack with the -r1 objects, one pack at a time, smallest first. Waits until B: free >= 304 GiB before starting a pack
(new shards stay local until the normal intake -> training C1/C2 -> private upload flow clears them). Skips packs whose packed/<pack>-r1/receipt.json exists."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, time, subprocess, shutil
from lane_config import LANE_ROOT as ROOT
PACKS = ["wikipedia-20220501-p41243p151573", "wikipedia-20220501-g06", "wikipedia-20220501-g07", "wikipedia-20220501-g02", "wikipedia-20220501-g05", "wikipedia-20220501-g03", "wikipedia-20220501-g04", "wikipedia-20220501-g08", "wikipedia-20220501-g01", "wikipedia-20220501-g00"]
def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)
for p in PACKS:
    if os.path.exists(f"{ROOT}/packed/{p}-r1/receipt.json") and os.path.exists(f"{ROOT}/packed/{p}-r1/intake.json"): log("skip", p); continue
    sys.path.insert(0, ROOT + "/scripts"); import reserve_plan; need = reserve_plan.floor_gib() + json.load(open(f"{ROOT}/packed/{p}/receipt.json"))["total_tokens"] * 2 / 2**30 + 0.5   # lane floor 301 + this pack's shards (uint16) + margin
    while shutil.disk_usage("B:/").free / 2**30 < need: log("waiting for B: free >= %.1f GiB (now %.1f)" % (need, shutil.disk_usage("B:/").free / 2**30)); time.sleep(300)
    log("repack", p); shutil.rmtree(f"{ROOT}/packed/{p}-r1", ignore_errors=True)
    r = subprocess.run([sys.executable, f"{ROOT}/scripts/repack_r1.py", p]); log("repack", p, "exit", r.returncode)
    if r.returncode != 0: sys.exit(r.returncode)
open(f"{ROOT}/redact-r1/REPACK.done", "w").write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())); log("ALL REPACKS DONE")
