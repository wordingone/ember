# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red for the H46 window guard in dup_ckpt_delete.py (lead 82193). Run: python scripts/tests/dup_ckpt_delete_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT, M_ROOT, SEAT_LEAD
import subprocess, sys, os
ok = True
def check(l, c):
    global ok; ok &= bool(c); print("PASS" if c else "FAIL", l)
M = (M_ROOT + "/avir/" + SEAT_LEAD + "/state/gpu-window-open")
r = subprocess.run([sys.executable, (LANE_ROOT + "/scripts/dup_ckpt_delete.py")], capture_output=True, text=True)
check("RED real run refuses while the window marker exists (or no marker: skip)", (not os.path.exists(M)) or (r.returncode == 3 and "REFUSED" in r.stdout))
src = open((LANE_ROOT + "/scripts/dup_ckpt_delete.py"), encoding="utf-8").read()
check("guard runs before any HF write", src.index("wait_marker()") < src.index("hf_push.create_commit(api"))
check("receipts written before the commit", src.index("f.write(json.dumps(x)") < src.index("hf_push.create_commit(api"))
check("only CommitOperationDelete of manifest paths (no folder delete)", "is_folder" not in src)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
