# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Finish the H39 restore mechanically (lead 82038 / queue 'restore tail'): wait for STAGE2-EXIT in logs/ckpt-restore2.log, run training's lineage_closure_check_v1.py on the H39 child,
write logs/restore-finish.json {rc, closure output tail, restored rows, sha-verified count}. rc 0 -> remove loops/RESTORE-PRIORITY.flag (releases the held download/upload lanes). The delete-freeze flag stays until training says otherwise. Idempotent.
Run detached: python scripts/restore_finish.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, M_ROOT, SEAT_TRAIN
import os, sys, json, time, subprocess
pass
import ckpt_children as C
L = (LANE_ROOT + "/logs/"); FLAG = (LANE_ROOT + "/loops/RESTORE-PRIORITY.flag")
while not (os.path.exists(L + "ckpt-restore2.log") and "STAGE2-EXIT 0" in open(L + "ckpt-restore2.log", errors="ignore").read()):   # only a clean exit (a killed wrapper once wrote STAGE2-EXIT 127)
    time.sleep(60)
child = C.CH["H39"][1]
r = subprocess.run([sys.executable, "-I", "-B", (M_ROOT + "/avir/" + SEAT_TRAIN + "/scripts/lineage_closure_check_v1.py"), child, "--json", L + "lineage-closure-H39.json"], capture_output=True, text=True)
rows = [json.loads(l) for l in open(L + "ckpt-restore.jsonl") if l.strip()]
out = dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), child=child, rc=r.returncode, tail=r.stdout[-1500:], restore_rows=len(rows), unique_sha=len({x["sha256"] for x in rows}), gib=round(sum(x["size"] for x in rows) / 2 ** 30, 1))
if r.returncode == 0 and os.path.exists(FLAG):
    os.remove(FLAG); out["flag_removed"] = True
json.dump(out, open(L + "restore-finish.json", "w"), indent=1)
print(json.dumps(out)[:600])
