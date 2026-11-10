# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Reds/greens for upload_refuse (lead 82100): pre-redaction originals never upload. Run: python scripts/tests/upload_refuse_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import os, sys, glob
pass
import upload_refuse as U
ok = True
def check(label, cond):
    global ok
    ok &= bool(cond); print("PASS" if cond else "FAIL", label)
dirs = glob.glob((LANE_ROOT + "/scratch/*pre-redaction*")); check("pre-redaction dirs exist to test against", len(dirs) >= 1)
for d in dirs:
    check("RED dir refused: " + os.path.basename(d), U.refused(d))
    fs = [os.path.join(a, f) for a, _, c in os.walk(d) for f in c][:1]
    for f in fs: check("RED file inside refused", U.refused(f))
check("RED parent scratch/ refused (would contain them)", U.refused((LANE_ROOT + "/scratch")))
check("RED data-staging root refused", U.refused(LANE_ROOT))
check("RED any path with the marker refused", U.refused("X:/tmp/foo-pre-redaction-1/a.bin"))
check("GREEN packed pack dir allowed", not U.refused((LANE_ROOT + "/packed/pg-00004-00008")))
check("GREEN redacted pack dir allowed", not U.refused((LANE_ROOT + "/scratch/pes2o-00000-00002-redacted")))
check("GREEN restore scratch allowed", not U.refused((LANE_ROOT + "/scratch/restore/dl-x")))
try: U.check(dirs[0]); check("RED check() raises", False)
except U.UploadRefused: check("RED check() raises UploadRefused", True)
import raw_roll
f = next(os.path.join(a, x) for a, _, c in os.walk(dirs[0]) for x in c)
try: raw_roll.roll([(f, "x/y")]); check("RED raw_roll.roll refuses before any network call", False)
except U.UploadRefused: check("RED raw_roll.roll refuses before any network call", True)
for fn in ("upload_worker.py", "bulk_lane.py", "raw_roll.py", "loops/tick.py"):
    check("funnel wired: " + fn, "upload_refuse" in open((LANE_ROOT + "/scripts/") + fn, encoding="utf-8").read())

import tempfile, shutil
_h = tempfile.mkdtemp(prefix="hold-red-")
try:
    check("GREEN a pack dir without the marker is not held", not U.refused(_h))
    open(os.path.join(_h, "HOLD-UPLOAD"), "w").write("doc-level overlap with another pack, repack pending")
    check("RED a pack dir with HOLD-UPLOAD is refused and the reason is reported", "overlap" in U.refused(_h))
    os.remove(os.path.join(_h, "HOLD-UPLOAD")); check("GREEN removing the marker releases the pack", not U.refused(_h))
finally: shutil.rmtree(_h, ignore_errors=True)

# LINT (lead 82104, one funnel, no exceptions): no raw HF write call outside hf_push.py; every spawner of the hf CLI goes through the guard
import re, glob as _g
raw = re.compile(r"\.(upload_file|create_commit|upload_folder|upload_large_folder)\(")
bad = []
for ff in _g.glob((LANE_ROOT + "/scripts/*.py")) + _g.glob((LANE_ROOT + "/scripts/loops/*.py")):
    b = os.path.basename(ff)
    if b in ("hf_push.py", "upload_refuse_red_test.py", "_alarm_redtest.py"): continue
    for i, l in enumerate(open(ff, encoding="utf-8", errors="ignore"), 1):
        if raw.search(l) and "hf_push." not in l and "HfApi().upload_file" not in l and not l.lstrip().startswith(("#", '"""')): bad.append(f"{b}:{i}")
check("LINT no raw .upload_file/.create_commit/.upload_folder outside hf_push (offenders: %s)" % bad[:5], not bad)
for fn in ("ckpt_backup.py", "loops/tick.py", "upload_worker.py"):
    t = open((LANE_ROOT + "/scripts/") + fn, encoding="utf-8").read(); check("CLI/push spawner guarded: " + fn, "hf_push" in t or "upload_refuse" in t)
try: import hf_push; hf_push.upload_file(object(), path_or_fileobj=f, path_in_repo="x", repo_id="x/y"); check("RED hf_push.upload_file refuses before api call", False)
except U.UploadRefused: check("RED hf_push.upload_file refuses before api call", True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
