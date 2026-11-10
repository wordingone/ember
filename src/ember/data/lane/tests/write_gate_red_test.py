# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red test (lead 82324): lane write paths wait on the B: floor instead of writing. Run: python scripts/tests/write_gate_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import os, sys, types
pass
import reserve_plan as R, th_gate as T
ok = True
def check(l, c):
    global ok; ok &= bool(c); print("PASS" if c else "FAIL", l)
fl = R.floor_gib()
check("gate allows a write when free - need >= floor", R.write_gate("t", 1 << 30, cap_s=0, free_gib=lambda: fl + 5, log=lambda *a: None) is True)
check("gate refuses (returns False, cap hit) when free - need < floor", R.write_gate("t", 10 << 30, cap_s=0, free_gib=lambda: fl + 5, log=lambda *a: None) is False)
# th_gate: below the floor the scratch expansion must NOT happen and the scan must fail closed
orig_gate = R.write_gate; orig_du = R.shutil.disk_usage; called = []
R.shutil.disk_usage = lambda p: types.SimpleNamespace(free=int((fl - 20) * 2**30), total=0, used=0)
R.write_gate = lambda who, need, **k: orig_gate(who, need, cap_s=0, poll_s=0, log=lambda *a: None)
T._expand = lambda *a, **k: called.append(1) or []
import tempfile; f = tempfile.NamedTemporaryFile(suffix=".jsonl.zst", delete=False); f.write(b"x" * 1000); f.close()
try:
    try: T.scan_files([f.name]); raised = False
    except T.ThError: raised = True
finally:
    R.write_gate = orig_gate; R.shutil.disk_usage = orig_du; os.remove(f.name)
check("th_gate below the floor: ThError (fail-closed) and _expand never called (nothing written)", raised and not called)
src = lambda n: open((LANE_ROOT + "/scripts/") + n, encoding="utf-8").read()
s = src("pack.py"); check("pack.py: write_gate precedes the shard tmp write", 0 <= s.find("write_gate") < s.find('open(tmp, "wb")'))
s = src("redact_pack_hits.py"); check("redact_pack_hits.py: write_gate precedes the redacted-copy write", 0 <= s.find("write_gate") < s.find('open(o, "wb")'))
s = src("text_lane.py"); r = s[s.find("def run(cmd, log):"):s.find("def run(cmd, log):") + 700]; check("text_lane.py run(): write_gate (floor wait for new pack/dedup/scrub STARTS, lead 82509) precedes harm_wait and the subprocess", 0 <= r.find("write_gate") < r.find("harm_wait") < r.find("subprocess.run"))
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
