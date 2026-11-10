# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green for the declared-hold rule of stall_alarm.py (lead 82475): a worker whose newest log line is 'push HELD: <flag>' produces no STALL ALARM; a silent worker with no hold still does.
Run: python scripts/tests/stall_alarm_held_red_test.py   (no mail is sent, no queue state is read: pure functions + source checks)"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import os, sys, tempfile, time, shutil
pass
import stall_alarm as S
ok = True
def check(l, c):
    global ok; ok &= bool(c); print("PASS" if c else "FAIL", l)
T = tempfile.mkdtemp(dir=(LANE_ROOT + "/scratch")); lg = T + "/w.log"
def w(lines, age=0):
    open(lg, "w").write("\n".join(lines) + "\n")
    if age: os.utime(lg, (time.time() - age,) * 2)
H = "push HELD: RESTORE-PRIORITY.flag"
w(["14:31:00 uploaded a 1 MiB", "14:33:26 " + H, "14:35:26 " + H, "14:37:26 " + H])
h = S.held_state(lg)
check("GREEN newest line is a declared hold -> (flag, first time of the unbroken run)", h == ("RESTORE-PRIORITY.flag", "14:33:26"))
check("RED a held worker produces no alarm even when flat for 3 h and never alerted", S.decide(3 * 3600, 600, 1e9, 3600, h) == "hold")
check("RED a silent worker with no hold still alarms (flat 20 min, never alerted)", S.decide(1200, 600, 1e9, 3600, None) == "alarm")
check("GREEN flat under the threshold waits", S.decide(300, 600, 1e9, 3600, None) == "wait")
check("GREEN already alerted within the repeat window waits", S.decide(1200, 600, 60, 3600, None) == "wait")
w(["14:33:26 " + H, "14:35:26 " + H, "14:36:00 uploaded b 1 MiB"])
check("RED a hold followed by a real line is not a hold any more (the alarm clock applies)", S.held_state(lg) is None)
w(["14:33:26 " + H], age=7200)
check("RED a stale log (2 h old) is not a declared hold: a dead worker must still alarm", S.held_state(lg) is None)
check("GREEN a missing log is not a hold", S.held_state(T + "/nope.log") is None)
w(["14:30:00 push HELD: OTHER.flag", "14:33:26 " + H, "14:35:26 " + H])
check("GREEN the run start resets when the named flag changes", S.held_state(lg) == ("RESTORE-PRIORITY.flag", "14:33:26"))
w(["14:33:26 push HELD:"])
check("RED a HELD line without a named flag is not a declared hold", S.held_state(lg) is None)
src = open((LANE_ROOT + "/scripts/stall_alarm.py"), encoding="utf-8").read()
i = src.index("def _run_stall"); body = src[i:]
check("source: _run_stall asks held_state() before the alarm decision and returns without mailing", body.index("hold = held_state()") < body.index('decide(flat, THRESH') and "declared hold, no alarm" in body)
shutil.rmtree(T, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
