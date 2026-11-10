# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red test for stale_drivers (lead 82534): a process started BEFORE an edit of its script or of a module it imports (transitively) is listed; a process started after is not; foreign scripts and non-python are ignored."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import os, sys, tempfile, time
T = tempfile.mkdtemp().replace("\\", "/"); S = T + "/scripts"; os.makedirs(S)
os.environ["STALE_SCRIPTS"] = S
pass; import stale_drivers as D
D.SCRIPTS = S
def w(name, body, mt):
    p = "%s/%s.py" % (S, name); open(p, "w").write(body); os.utime(p, (mt, mt)); return p
now = time.time()
w("gate", "X = 1\n", now - 100)                       # edited 100 s ago
w("lane", "import gate\nimport os\n", now - 5000)      # the driver imports gate
w("solo", "import os\n", now - 5000)                   # imports nothing local
w("deep", "import lane\n", now - 5000)                 # imports lane which imports gate (transitive)
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print("PASS" if cond else "FAIL", name)
py = "C:/Python/python.exe"
procs = [(1, now - 3600, [py, S + "/lane.py", "text"]),    # started 1 h ago, gate edited 100 s ago -> stale
         (2, now - 50, [py, S + "/lane.py", "text"]),      # started after the edit -> fresh
         (3, now - 3600, [py, S + "/solo.py"]),            # own file older than start -> fresh
         (4, now - 3600, [py, "scripts/deep.py"]),         # relative path, transitive import -> stale
         (5, now - 3600, ["C:/x/node.exe", S + "/lane.py"]),   # not python
         (6, now - 3600, [py, "D:/elsewhere/other.py"]),   # foreign script
         (7, now - 3600, [py, S + "/lane.py", "--flag"])]
r = {x[0] for x in D.stale(procs)}
check("old driver importing an edited module is stale", 1 in r)
check("driver started after the edit is fresh", 2 not in r)
check("driver whose files are all older than its start is fresh", 3 not in r)
check("transitive import edited after start -> stale (relative script path)", 4 in r)
check("non-python process ignored", 5 not in r)
check("foreign script ignored", 6 not in r)
l = D.line(procs)
check("line names the module and says STALE_DRIVERS", l.startswith("STALE_DRIVERS") and "gate edited" in l)
check("zero case reports what it checked (1 lane process, 0 unreadable, 0 outside)", D.line([(2, now - 50, [py, S + "/lane.py"])]) == "stale_drivers 0 (checked 1 lane processes; 0 modules unreadable; 0 python processes outside scripts/)")
check("zero case counts a python process outside scripts/ as unresolved, not as clean", "1 python processes outside" in D.line([(6, now - 3600, [py, "D:/elsewhere/other.py"])]))
check("zero case with nothing running says checked 0, never a bare 'stale_drivers 0'", D.line([]).startswith("stale_drivers 0 (checked 0 "))
_gone = lambda m: (_ for _ in ()).throw(FileNotFoundError(m))
check("an unreadable module is counted, not treated as fresh", "1 modules unreadable" in D.line([(2, now - 50, [py, S + "/solo.py"])], mtime=_gone))
w("solo", "import os\n", now + 1)                       # own script edited after start
check("own script edited after start -> stale", 3 in {x[0] for x in D.stale(procs)})
import shutil; shutil.rmtree(T, ignore_errors=True)      # the sandbox of scripts is removed (it used to leak a temp dir per run)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
