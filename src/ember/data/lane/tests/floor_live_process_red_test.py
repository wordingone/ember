# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red test (lead 82381): a floor change reaches lane processes that are ALREADY RUNNING. 2026-11-10: nine text_lane processes had imported the old 301 and kept writing below the press floor.
Starts a long-lived child that imports reserve_plan ONCE, then changes the floor file under it and asks the same process again. Throwaway files only."""
import os, sys, json, time, tempfile, subprocess
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d = tempfile.mkdtemp(); env = dict(os.environ, FLOOR_FILE=os.path.join(d, "floor.json"), RESERVE_FILE=os.path.join(d, "reserve.json"), RESERVE_STATE=os.path.join(d, "state.json"))
CHILD = "import sys; sys.path.insert(0, %r); import reserve_plan as R\nfor line in sys.stdin:\n    print(R.floor_gib(), flush=True)\n" % HERE.replace("\\", "/")
p = subprocess.Popen([sys.executable, "-c", CHILD], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)
ok = True
def chk(n, c):
    global ok
    print(("PASS " if c else "FAIL ") + n); ok = ok and bool(c)
def ask():
    p.stdin.write("?\n"); p.stdin.flush(); return float(p.stdout.readline())
def setfloor(v): json.dump({"standing_floor_gib": v}, open(env["FLOOR_FILE"], "w"))
try:
    chk("no file -> built-in 315 in the running process", ask() == 315.0)
    setfloor(330); chk("RED the floor file raised to 330 AFTER the process imported reserve_plan: the same process now reports 330", ask() == 330.0)
    setfloor(301); chk("RED a file value below 315 cannot lower the floor", ask() == 315.0)
    os.remove(env["FLOOR_FILE"]); chk("GREEN the file removed -> back to 315", ask() == 315.0)
    open(env["FLOOR_FILE"], "w").write("{not json"); chk("GREEN a corrupt floor file fails safe to 315 (never wedges, never lowers)", ask() == 315.0)
    setfloor(320); t = time.gmtime(time.time() + 3600)
    json.dump(dict(chain_start_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", t), chain_start_floor_gib=305, hour_writes_gib=0, publish_gib=18, declared_by="test"), open(env["RESERVE_FILE"], "w"))
    chk("GREEN a declaration above the standing floor (323) still raises it in the running process", ask() == 323.0)
    src = open(os.path.join(HERE, "reserve_plan.py"), encoding="utf-8").read()
    chk("GREEN reserve_plan has no import-time floor constant that floor_gib() returns", "def standing" in src and "return max(BUILTIN" in src)
finally:
    p.kill(); p.wait()
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
