# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red for --only-probes in ckpt_lineage_delete.py (lead ruling 82451: only branch (c), the guarded terminal probes, may run; branches (a)/(b) stay stopped).
Runs the script as a DRY RUN only (never --apply). Run: python scripts/tests/ckpt_lineage_only_probes_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import os, sys, json, subprocess, re
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import probe_terminal_guard as PG, evict_ckpt_list as EK
ok = True
def check(l, c):
    global ok; ok &= bool(c); print("PASS" if c else "FAIL", l)
src = open(os.path.join(HERE, "ckpt_lineage_delete.py"), encoding="utf-8").read()
check("source: ONLY_PROBES empties branch (a) and the (b) log list", "({} if ONLY_PROBES else chk)" in src and "() if ONLY_PROBES else BK_LOGS" in src)
check("source: the flags are parsed before --keep consumes the rest of argv (documented in the usage line)", "[--apply] [--only-probes] [--expect-dirs FILE.json] [--ruling ID] [--plan-sha256 SHA] [--keep NAME ...]" in src)
check("source: --expect-dirs refuses (exit 4) before any hashing, manifest row or remove when the selected dirs differ", 'if _exp != _got:' in src and "sys.exit(4)" in src and src.index("sys.exit(4)") < src.index("rows = []; keep_shared") < src.index("VR.remove_ruled("))
def dry(*flags):
    assert "--apply" not in flags
    r = subprocess.run([sys.executable, os.path.join(HERE, "ckpt_lineage_delete.py"), *flags], capture_output=True, text=True, cwd=LANE_ROOT)
    m = re.search(r"children selected (\d+)", r.stdout)
    return r, (int(m.group(1)) if m else None)
r1, n1 = dry("--only-probes")
expect = sum(1 for p in json.load(open((LANE_ROOT + "/logs/ckpt-probes.json"))) if PG.probe_eligibility(p["dir"], kept=EK.kept)["ok"] and not EK.kept(p["dir"]))
if os.path.exists((LANE_ROOT + "/loops/CKPT-DELETE-FREEZE.flag")):      # lead 81956: the freeze stops the script after selection and before any count line, dry or not
    check("GREEN the delete freeze flag is honoured with --only-probes (exit 3, REFUSED); the count checks are skipped while the freeze stands", r1.returncode == 3 and "REFUSED: CKPT-DELETE-FREEZE.flag" in r1.stdout and n1 is None)
else:
    check("GREEN --only-probes dry run exits 0 and says DRY RUN", r1.returncode == 0 and "DRY RUN" in r1.stdout)
    check("RED --only-probes selects exactly the guard-eligible probes (%s expected, %s selected), nothing from (a)/(b)" % (expect, n1), n1 == expect)
n_ref = sum(1 for p in json.load(open((LANE_ROOT + "/logs/ckpt-probes.json"))) if not PG.probe_eligibility(p["dir"], kept=EK.kept)["ok"])
check("GREEN every guard-refused probe (%d now) is printed as PROBE REFUSED with its stable code" % n_ref, r1.stdout.count("PROBE REFUSED") == n_ref)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
