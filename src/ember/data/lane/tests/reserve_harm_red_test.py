# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Reds/greens for reserve_plan.harm_wait (lead 82070, run-unaffected rule cl. 2): a lane waits ONLY on measured harm (restore flag = link priority; B: below floor_gib() = disk). A quiet-window / presence pair in reserve.json must NOT make anything wait.
Run: python scripts/tests/reserve_harm_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import os, sys, json, time, shutil
T = (LANE_ROOT + "/scratch/harm_test"); shutil.rmtree(T, ignore_errors=True); os.makedirs(T)
fut = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 7200)); past = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 600))
json.dump({"chain_start_utc": fut, "chain_start_floor_gib": 300, "hour_writes_gib": 0, "publish_gib": 0, "declared_by": "test", "quiet_from": past, "quiet_until": fut}, open(T + "/reserve.json", "w"))
os.environ["RESERVE_FILE"] = T + "/reserve.json"; os.environ["RESTORE_FLAG"] = T + "/RESTORE-PRIORITY.flag"
pass
import reserve_plan as R
ok = True


def check(label, cond):
    global ok
    ok &= bool(cond); print("PASS" if cond else "FAIL", label)


def timed(**kw):
    t = time.time(); R.harm_wait("test", lambda m: None, poll_s=0.2, **kw); return time.time() - t


check("quiet()/quiet_wait() presence guard no longer exists", not hasattr(R, "quiet") and not hasattr(R, "quiet_wait"))
check("RED quiet window active in reserve.json + no harm -> harm_wait returns at once (no presence wait)", timed(cap_s=5, free_gib=lambda: 500.0) < 1.0)
open(R.RESTORE_FLAG, "w").write("x")
check("RED restore flag up -> link harm reported", "link priority" in R.harm())
check("RED restore flag up -> harm_wait waits (capped)", timed(cap_s=1.0, free_gib=lambda: 500.0) >= 1.0)
check("GREEN push (kinds=link) does not wait on the disk floor when the flag is down", (os.remove(R.RESTORE_FLAG), timed(cap_s=5, kinds=("link",), free_gib=lambda: 10.0))[1] < 1.0)
check("RED disk below floor_gib() -> harm_wait waits (capped)", timed(cap_s=1.0, kinds=("disk",), free_gib=lambda: 10.0) >= 1.0)
check("GREEN disk above floor -> no wait", timed(cap_s=5, kinds=("disk",), free_gib=lambda: 400.0) < 1.0)
src = open((LANE_ROOT + "/scripts/loops/tick.py"), encoding="utf-8").read().lower().split("def ")[0]
check("tick.py header has no quiet-window guard", "quiet window until" not in src and "_quiet" not in src)
check("restart_at_boundary.py has no _quiet", "_quiet" not in open((LANE_ROOT + "/scripts/restart_at_boundary.py"), encoding="utf-8").read())
shutil.rmtree(T, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
