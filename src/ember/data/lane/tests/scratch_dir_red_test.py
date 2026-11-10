# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green test for scratch_dir.py: every scratch writer removes its own scratch on exit, and a killed writer's leftovers are swept (lead 82361).
Runs entirely under a throwaway root outside B:."""
import os, sys, json, time, shutil, tempfile, subprocess
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import psutil
import scratch_dir as S

ok = True


def check(name, cond):
    global ok
    ok = ok and bool(cond); print(("PASS " if cond else "FAIL ") + name)


R = tempfile.mkdtemp(prefix="scr-red-"); LOG = os.path.join(R, "sweep.jsonl"); W = os.path.join(R, "w"); os.makedirs(W)
CODE = "import sys; sys.path.insert(0, %r); import scratch_dir as S\n%%s" % HERE.replace("\\", "/")
try:
    # GREEN 1: normal exit removes the dir
    out = subprocess.run([sys.executable, "-c", CODE % ("d = S.ScratchDir('th-', root=%r).path; open(d + '/big', 'wb').write(b'x' * 1000); print(d)" % W.replace("\\", "/"))], capture_output=True, text=True).stdout.strip()
    check("GREEN a writer that exits normally leaves nothing behind", out and not os.path.exists(out) and not os.listdir(W))
    # GREEN 2: an exception removes the dir
    out = subprocess.run([sys.executable, "-c", CODE % ("with S.ScratchDir('th-', root=%r) as d:\n  print(d, flush=True); raise RuntimeError('boom')" % W.replace("\\", "/"))], capture_output=True, text=True).stdout.strip()
    check("GREEN a writer that raises leaves nothing behind", out and not os.path.exists(out))
    # RED: a killed writer cannot clean up -> the dir stays, a stamped owner is dead, the sweep removes it and writes the receipt first
    p = subprocess.Popen([sys.executable, "-c", CODE % ("d = S.ScratchDir('th-', root=%r).path; open(d + '/part', 'wb').write(b'y' * 2048); print(d, flush=True); import time; time.sleep(60)" % W.replace("\\", "/"))], stdout=subprocess.PIPE, text=True)
    killed_dir = p.stdout.readline().strip()
    check("RED a live writer's dir is NOT swept", S.sweep(root=W, min_age_s=0, log=LOG) == [] and os.path.isdir(killed_dir))
    psutil.Process(p.pid).kill(); p.wait()
    check("RED a killed writer leaves its dir behind (atexit cannot run)", os.path.isdir(killed_dir))
    check("GREEN a dir younger than min_age_s is not swept", S.sweep(root=W, min_age_s=3600, log=LOG) == [])
    res = S.sweep(root=W, min_age_s=0, log=LOG)
    check("GREEN the sweep removes the dead owner's dir", [os.path.normcase(d) for d, _ in res] == [os.path.normcase(killed_dir)] and not os.path.exists(killed_dir))
    rows = [json.loads(l) for l in open(LOG, encoding="utf-8")]
    check("GREEN a receipt row (bytes, owner) was written for the removal", len(rows) == 1 and rows[0]["bytes"] >= 2048 and rows[0]["owner"]["pid"] == p.pid)
    # RED: an unstamped dir is never touched
    os.makedirs(W + "/not-mine"); open(W + "/not-mine/f", "w").write("z")
    check("RED a directory without an owner stamp is never swept", S.sweep(root=W, min_age_s=0, log=LOG) == [] and os.path.exists(W + "/not-mine/f"))
    # RED: pid reuse -> the stamp names a live pid but another create_time -> treated as gone
    d2 = S.make("th-", root=W); st = json.load(open(d2 + "/.owner")); st["create_time"] = (st["create_time"] or 0) - 3600; json.dump(st, open(d2 + "/.owner", "w"))
    check("RED a reused pid (create_time differs) does not keep a dead writer's dir alive", [os.path.normcase(d) for d, _ in S.sweep(root=W, min_age_s=0, log=LOG)] == [os.path.normcase(d2)])
    # GREEN: the writers use it
    for f in ("th_gate.py",):
        src = open(os.path.join(HERE, f), encoding="utf-8").read()
        check("GREEN %s takes its scratch from scratch_dir (no bare mkdtemp into the scratch root)" % f, "scratch_dir" in src and 'tempfile.mkdtemp(dir=SCRATCH' not in src)
    tk = open(os.path.join(HERE, "loops", "tick.py"), encoding="utf-8").read()
    check("GREEN tick.py sweeps dead writers' scratch every run", "scratch_dir" in tk and "sweep(" in tk)
finally:
    shutil.rmtree(R, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
