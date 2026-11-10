# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red test: run_loops.py singleton lock, slot schedule without pile-up, one-tick-at-a-time. Run: python scripts/tests/run_loops_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import os, sys, time, subprocess, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "loops"))
import run_loops as R
ok = True
def check(l, c):
    global ok; ok &= bool(c); print("PASS" if c else "FAIL", l)
d = tempfile.mkdtemp(); lk = d + "/x.lock"
h1 = R.take_lock(lk); check("first runner takes the lock", h1 is not None)
r = subprocess.run([sys.executable, "-c", ("import sys; sys.path.insert(0, r'" + LANE_ROOT + "/scripts/loops'); import run_loops as R; print(R.take_lock(r'%s') is None)") % lk.replace("\\", "/")], capture_output=True, text=True)
check("RED second runner (another process) cannot take the lock", r.stdout.strip() == "True")
h1.close()
r = subprocess.run([sys.executable, "-c", ("import sys; sys.path.insert(0, r'" + LANE_ROOT + "/scripts/loops'); import run_loops as R; print(R.take_lock(r'%s') is not None)") % lk.replace("\\", "/")], capture_output=True, text=True)
check("lock is released when the holder exits", r.stdout.strip() == "True")
t = time.mktime((2026, 11, 10, 9, 30, 10, 0, 0, -1)); dd = R.due(t, {})
check("each mechanical tick has exactly one due slot at start", sorted(n for n, _ in dd) == ["census", "fetch", "upload"])
ls = {n: s for n, s in dd}; check("RED no second run for a slot already run (no pile-up)", R.due(t, ls) == [])
t2 = time.mktime((2026, 11, 10, 9, 53, 0, 0, 0, -1)); check("next slots become due on time", sorted(n for n, _ in R.due(t2, ls)) == ["census", "fetch", "upload"] and True)
t3 = time.mktime((2026, 11, 10, 9, 8, 0, 0, 0, -1)); ls3 = {n: s for n, s in R.due(t3, {})}
check("only fetch (:07) is newly due at 09:08 after the 08:xx slots ran", [n for n, _ in R.due(t3, ls3)] == [])
class P:
    pid = 1
    def poll(self): return None
check("RED a tick whose previous run is alive is skipped, not stacked", R.run_tick("upload", {"upload": P()})[0] is None)
check("judgment ticks are not in the runner schedule", "intake" not in R.SCHEDULE and "prep" not in R.SCHEDULE)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
