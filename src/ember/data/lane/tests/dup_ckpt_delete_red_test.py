# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red for the H46 window guard in dup_ckpt_delete.py (lead 82193). Run: python scripts/tests/dup_ckpt_delete_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import subprocess, sys, os
ok = True
def check(l, c):
    global ok; ok &= bool(c); print("PASS" if c else "FAIL", l)
# PR 2452 review (lead 82448): this test never executes the deployed script at all (a non-dry run can issue a live remote commit, and a marker check followed by a run is racy). The window refusal is asserted on the source only.
_s0 = open((LANE_ROOT + "/scripts/dup_ckpt_delete.py"), encoding="utf-8").read()
check("a non-dry run without --wait-h46 exits 3 while the marker exists (source)", "if not dry:" in _s0 and "elif os.path.exists(MARKER)" in _s0 and "sys.exit(3)" in _s0)
src = open((LANE_ROOT + "/scripts/dup_ckpt_delete.py"), encoding="utf-8").read()
check("guard runs before any HF write", src.index("wait_marker()") < src.index("hf_push.create_commit(api"))
check("receipts written before the commit", src.index("f.write(json.dumps(x)") < src.index("hf_push.create_commit(api"))
check("only CommitOperationDelete of manifest paths (no folder delete)", "is_folder" not in src)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
