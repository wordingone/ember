# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red test (lead 82357): the write floor on B: is never below the standing 315 GiB. A declaration can raise it, never lower it; no/stale declaration -> 315; a lease floor cannot lower it."""
import os, sys, json, time, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
d = tempfile.mkdtemp()
os.environ["RESERVE_FILE"] = os.path.join(d, "reserve.json"); os.environ["RESERVE_STATE"] = os.path.join(d, "state.json")
import reserve_plan as R
ok = True
def chk(n, c):
    global ok
    print(("PASS " if c else "FAIL ") + n); ok = ok and bool(c)
def declare(floor, writes=0, publish=0, start_in=3600):
    t = time.gmtime(time.time() + start_in)
    json.dump(dict(chain_start_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", t), chain_start_floor_gib=floor, hour_writes_gib=writes, publish_gib=publish, declared_by="test"), open(os.environ["RESERVE_FILE"], "w"))
chk("no declaration -> 315", R.floor_gib() == 315.0)
declare(280, 0, 0); chk("a LOWER declaration (280) cannot lower the floor below 315", R.floor_gib() == 315.0)
declare(292, 0, 9); chk("declaration 301 is raised to 315", R.floor_gib() == 315.0)
declare(305, 8, 6.5); chk("a HIGHER declaration (319.5) raises the floor", abs(R.floor_gib() - 319.5) < 1e-9)
declare(292, 0, 0, start_in=-5 * 3600); chk("stale declaration -> 315", R.floor_gib() == 315.0)
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "loops", "tick.py"), encoding="utf-8").read()
chk("tick.py clamps a lease floor to reserve_plan.floor_gib()", 'max(lease["floor"], reserve_plan.floor_gib())' in src)
src2 = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bulk_lane.py"), encoding="utf-8").read()
chk("bulk_lane.py clamps a lease floor to reserve_plan.floor_gib()", 'max(L["floor"], reserve_plan.floor_gib())' in src2)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
