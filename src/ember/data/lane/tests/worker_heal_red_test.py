# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green for stall_alarm.heal_worker (lead 82167): alive-but-failing uploader is restarted; healthy/empty-queue/cooldown are not. Run: python scripts/tests/worker_heal_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import os, sys, tempfile, time
pass
import stall_alarm as S
ok = True
def check(l, c):
    global ok; ok &= bool(c); print("PASS" if c else "FAIL", l)
T = tempfile.mkdtemp(dir=(LANE_ROOT + "/scratch")); lg = T + "/w.log"; st = T + "/s.json"
def w(lines): open(lg, "w").write("\n".join(lines) + "\n")
F = "22:27:42 FAILED x.job.json try 1: AttributeError module"
w(["22:00:00 uploaded a 0 MiB", F, F, F])
check("RED 3 trailing FAILED + queue>0 -> restart", S.heal_worker(2, time.time(), lg, st, kill=False).startswith("worker-heal"))
check("cooldown suppresses an immediate repeat", S.heal_worker(2, time.time(), lg, st, kill=False) == "")
os.remove(st); check("GREEN empty queue -> no action", S.heal_worker(0, time.time(), lg, st, kill=False) == "")
w([F, F, "22:30:00 uploaded b 1 MiB"]); check("GREEN last line uploaded -> no action", S.heal_worker(2, time.time(), lg, st, kill=False) == "")
w([F, F]); check("GREEN fewer than 3 lines -> no action", S.heal_worker(2, time.time(), lg, st, kill=False) == "")
w([F, F, F]); os.utime(lg, (time.time() - 7200,) * 2); check("GREEN stale log (>15 min) -> no action", S.heal_worker(2, time.time(), lg, st, kill=False) == "")
class _P:
    def __init__(s, pid, cmd): s.info = {"pid": pid, "cmdline": cmd}
LG = T + "/d.log"; open(LG, "w").write("02:30:00 stalled 240s with no I/O progress" + chr(10) + "02:30:00 FAILED x try 5" + chr(10))
v, _ = S.worker_diag(ps_all=[], log=LG); check("RED no worker process -> verdict dead", v == "dead")
v, txt = S.worker_diag(ps_all=[_P(7, ["C:/Python310/python.exe", "scripts/upload_worker.py"])], log=LG); check("RED alive worker + stalled/FAILED lines -> alive-retrying (not 'dead')", v == "alive-retrying" and "ALIVE" in txt)
open(LG, "w").write("02:31:00 uploaded a 1 MiB" + chr(10)); v, _ = S.worker_diag(ps_all=[_P(7, ["C:/Python310/python.exe", "scripts/upload_worker.py"])], log=LG); check("GREEN alive worker, recent upload -> alive-moving-or-idle", v == "alive-moving-or-idle")
import shutil; shutil.rmtree(T, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
