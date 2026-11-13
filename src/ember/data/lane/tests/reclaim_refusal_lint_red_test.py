# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Lint for gap 2 of #2486: a seat reclaim script (<seat scripts>/*reclaim*.py) that can remove a file or directory must either be RETIRED (SystemExit at the top) or call the lane refusal
(`protected_set.bound_hit` or `verified_remove`) before it removes anything. 2026-10-07 training's reclaim_payload.py removed the whole #2116 lineage root (254 files) with no such call.
Selftest (always run): a tmp dir with an unguarded script (must be flagged), a RETIRED one, a bound_hit one and a verified_remove one (must pass), plus a mutant lint that flags nothing (proves the red discriminates).
Real run: `python tests/reclaim_refusal_lint_red_test.py --seat` (or `--dir <seat scripts dir>`) lists every offender and exits 1 when there is one (the seat fixes its script; the lane never edits it)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import M_ROOT, SEAT_TRAIN
import os, re, sys, glob, shutil, tempfile
REMOVERS = re.compile(r"os\.remove\(|os\.unlink\(|shutil\.rmtree\(|\.unlink\(|\.rmdir\(|os\.rmdir\(")
RETIRED = re.compile(r"^\s*raise\s+SystemExit\(\s*[\"']RETIRED", re.M)
GUARDED = re.compile(r"bound_hit\s*\(|verified_remove|reclaim-lint: allow \S")   # the pragma `# reclaim-lint: allow <reason>` is for a script that removes only its own lease/output file


def offenders(d):
    out = []
    for f in sorted(glob.glob(d.rstrip("/\\") + "/*reclaim*.py")):
        if os.path.basename(f).startswith("test_"): continue
        t = open(f, encoding="utf-8", errors="replace").read()
        if REMOVERS.search(t) and not RETIRED.search(t) and not GUARDED.search(t): out.append(os.path.basename(f))
    return out


ok = True


def check(label, cond):
    global ok
    ok &= bool(cond); print("PASS" if cond else "FAIL", label)


if "--dir" in sys.argv or "--seat" in sys.argv:
    d = sys.argv[sys.argv.index("--dir") + 1] if "--dir" in sys.argv else (M_ROOT + "/avir/" + SEAT_TRAIN + "/scripts"); bad = offenders(d)
    for b in bad: print("OFFENDER", b)
    print("OFFENDERS", len(bad)); sys.exit(1 if bad else 0)
T = tempfile.mkdtemp(prefix="rl-lint-")
w = lambda n, body: open(T + "/" + n, "w").write(body)
w("a_reclaim_bad.py", "import shutil\nshutil.rmtree(p)\n")
w("b_reclaim_retired.py", 'raise SystemExit("RETIRED 2026-11-10: use ckpt_lineage_delete")\nimport shutil\nshutil.rmtree(p)\n')
w("c_reclaim_guarded.py", "import protected_set as PS, shutil\nif PS.bound_hit(p)[0]: raise SystemExit(2)\nshutil.rmtree(p)\n")
w("d_reclaim_vr.py", "import verified_remove\nverified_remove.remove(p)\nos.remove(x)\n")
w("g_reclaim_allow.py", "# reclaim-lint: allow removes only its own lease file" + chr(10) + "os.remove(LEASE)" + chr(10))
w("test_reclaim_x.py", "shutil.rmtree(p)" + chr(10))
w("e_reclaim_readonly.py", "print('census only')\n")
w("f_other_bad.py", "import shutil\nshutil.rmtree(p)\n")
check("an unguarded reclaim script is flagged, and only it (RETIRED, bound_hit, verified_remove, read-only and non-reclaim names pass)", offenders(T) == ["a_reclaim_bad.py"])
real = offenders; offenders = lambda d: []
check("MUTANT (lint off) no longer yields the flagged-only-the-bad-script result, so the first check discriminates", offenders(T) != ["a_reclaim_bad.py"])
offenders = real
shutil.rmtree(T, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
