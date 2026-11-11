# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red test (2026-11-10 deadlock): the pre-upload scan's scratch gate leaves headroom so scan -> upload -> verified drop can run while lanes pin B at the lane floor, and never goes under the press minimum."""
import os, sys, json, time, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
d = tempfile.mkdtemp()
os.environ["RESERVE_FILE"] = os.path.join(d, "reserve.json"); os.environ["RESERVE_STATE"] = os.path.join(d, "state.json"); os.environ["FLOOR_FILE"] = os.path.join(d, "floor.json")
import reserve_plan as R
ok = True


def chk(n, c):
    global ok
    ok = ok and bool(c); print(("PASS " if c else "FAIL ") + n)


need = int(0.4 * 2**30)
chk("GREEN no declaration: scan floor is 313.5 (lane floor 315 minus the 1.5 band)", R.scan_floor_gib() == 313.5)
chk("RED lanes at B=314.0 with a 0.4 GiB write: the lane gate refuses", R.write_gate("lane", need, free_gib=lambda: 314.0, cap_s=0, log=lambda *_: None) is False)
chk("GREEN same state: the scan gate admits the transient scratch (313.6 >= 313.5)", R.write_gate("scan", need, free_gib=lambda: 314.0, cap_s=0, log=lambda *_: None, floor_fn=R.scan_floor_gib) is True)
chk("RED B=313.8 with 0.4 GiB (would leave 313.4): even the scan gate refuses", R.write_gate("scan", need, free_gib=lambda: 313.8, cap_s=0, log=lambda *_: None, floor_fn=R.scan_floor_gib) is False)
chk("RED the press minimum is never crossed: floor 315 -> scan floor never below 313", R.scan_floor_gib() >= R.PRESS_MIN)
t = time.gmtime(time.time() + 3600)
json.dump(dict(chain_start_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", t), chain_start_floor_gib=330, hour_writes_gib=0, publish_gib=0, declared_by="test"), open(os.environ["RESERVE_FILE"], "w"))
chk("GREEN a higher declaration (330) raises the scan floor with it (328.5), not pinned at 313", R.scan_floor_gib() == 328.5)
src = open(os.path.join(HERE, "th_gate.py"), encoding="utf-8").read()
chk("GREEN th_gate's scratch write is gated on the SCRATCH drive (A:), not B: (batched scanner, lead 82972/82974): the gate reads A: free against a 20 GiB floor, and the old B: scan floor is not used", "free_gib=lambda: _free_gib(d)" in src and "floor_fn=lambda: A_FLOOR_GIB" in src and "floor_fn=reserve_plan.scan_floor_gib" not in src)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
