# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TruffleHog scan of one local pack dir before its HF push (operator / lead 81934). Called (detached) by tick.py upload; the tick pushes only when logs/th-scan/<name>.json says clean for the
CURRENT file signature. Fail-closed: scanner error => clean=false with the error. Never writes values.
ONE scan at a time (exclusive lock file A:/data-scan/scan.lock, env TH_SCAN_LOCK): a second caller waits (bounded, 6 h; on expiry the row is an error, clean=false) and a lock whose owner is gone is taken over.
The row carries K, workers, scan_s, parts, batches, parts_per_s (numbers read back from the run, never constants).
Usage: python th_pack_scan.py NAME LOCALDIR | selftest"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, time, hashlib
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import th_gate

OUT = os.environ.get("TH_SCAN_OUT", (LANE_ROOT + "/logs/th-scan"))
LOCK = os.environ.get("TH_SCAN_LOCK", "A:/data-scan/scan.lock")
LOCK_WAIT_S = 6 * 3600


def signature(local):
    """sha1 over the sorted (relative path, byte size) of every file under `local`: path + byte size only, NOT content (a same-size rewrite of a file keeps the signature)."""
    rows = sorted((os.path.relpath(os.path.join(dp, f), local).replace("\\", "/"), os.path.getsize(os.path.join(dp, f))) for dp, _, fs in os.walk(local) for f in fs)
    return hashlib.sha1(json.dumps(rows).encode()).hexdigest()


def _owner_alive(pid):
    """The lock's owner is alive only if the pid exists AND is a th_pack_scan process (a reused pid is not an owner)."""
    import psutil
    try:
        if not psutil.pid_exists(int(pid)): return False
        return any("th_pack_scan" in a for a in psutil.Process(int(pid)).cmdline())
    except psutil.NoSuchProcess:
        return False
    except Exception:
        return True      # cannot tell (access denied): treat as alive and keep waiting, never steal


def _lock_stale(path):
    try:
        with open(path, "r", encoding="utf-8") as f: info = json.load(f)
        return not _owner_alive(info.get("pid"))
    except FileNotFoundError:
        return False
    except Exception:      # empty / half-written file: the creator is between O_CREAT and its write; stale only if it has sat that way for a minute
        try: return time.time() - os.path.getmtime(path) > 60
        except OSError: return False


def _take_over_if_stale(path):
    """Remove a lock whose owner is gone. The check is repeated under a short-lived guard file so two waiters never remove a lock the other just created."""
    if not _lock_stale(path): return
    guard = path + ".takeover"
    try:
        open(guard, "x").close()
    except FileExistsError:
        try:
            if time.time() - os.path.getmtime(guard) > 60: os.remove(guard)      # a guard left by a crash
        except OSError: pass
        return
    try:
        if _lock_stale(path):
            try: os.remove(path)
            except FileNotFoundError: pass
    finally:
        try: os.remove(guard)
        except OSError: pass


def acquire_lock(path=None, wait_s=None, poll_s=5):
    path = path or LOCK; wait_s = LOCK_WAIT_S if wait_s is None else wait_s
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True); t0 = time.time()
    while True:
        try:
            with open(path, "x") as f: f.write(json.dumps(dict(pid=os.getpid(), ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))))
            return
        except FileExistsError:
            pass
        _take_over_if_stale(path)
        if time.time() - t0 >= wait_s:
            raise th_gate.ThError("scan lock not acquired within %d s" % wait_s)
        time.sleep(poll_s)


def release_lock(path=None):
    path = path or LOCK
    try:
        with open(path, "r", encoding="utf-8") as f: info = json.load(f)
        if info.get("pid") == os.getpid(): os.remove(path)      # only ever remove our own lock
    except Exception:
        pass


def main(name, local):
    os.makedirs(OUT, exist_ok=True)
    files = [os.path.join(dp, f) for dp, _, fs in os.walk(local) for f in fs]
    row = dict(name=name, local=local, signature=signature(local), ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), files=len(files))
    stats = {}
    try:
        acquire_lock()
        try:
            r = th_gate.scan_files(files, timeout=6 * 3600, stats=stats)
        finally:
            release_lock()
        row.update(clean=not r["hits"], hits=r["hits"], hit_files={os.path.relpath(k, local).replace("\\", "/") if os.path.isabs(k) else k: v for k, v in r["files"].items()}, error=None)
    except th_gate.ThError as e:
        row.update(clean=False, hits={}, hit_files={}, error=str(e)[:200])
    scan_s = stats.get("scan_s"); parts = stats.get("parts")
    row.update(K=stats.get("K"), workers=stats.get("workers"), scan_s=scan_s, parts=parts, batches=stats.get("batches"), parts_per_s=round(parts / scan_s, 3) if scan_s and parts is not None else None)
    tmp = os.path.join(OUT, name + ".json.tmp")
    json.dump(row, open(tmp, "w"), indent=1); os.replace(tmp, os.path.join(OUT, name + ".json"))
    print(json.dumps({k: row[k] for k in ("name", "clean", "hits", "error")}))


def selftest():
    """Lock behaviour: two concurrent callers run one after the other; a stale lock (dead pid, or a live pid that is not a th_pack_scan process) is taken over. Offline, TruffleHog stubbed (th_stub)."""
    import subprocess, tempfile, shutil, th_stub
    root = os.path.dirname(os.path.abspath(th_gate.SCRATCH)); os.makedirs(root, exist_ok=True)
    d = tempfile.mkdtemp(prefix="thps-", dir=root); ok = True

    def chk(n, c):
        nonlocal ok
        print(("PASS " if c else "FAIL ") + n); ok = ok and bool(c)

    try:
        stub = th_stub.make_launcher(d); log = os.path.join(d, "stub.log"); lock = os.path.join(d, "scan.lock"); out = os.path.join(d, "out")
        for n in ("pa", "pb"):
            os.makedirs(os.path.join(d, n)); open(os.path.join(d, n, "f.txt"), "w").write("hello\n")
        env = dict(os.environ, TH_BIN=stub, TH_STUB_MODE="sleep", TH_STUB_SLEEP="2", TH_STUB_LOG=log, TH_SCAN_LOCK=lock, TH_SCAN_OUT=out, TH_SCRATCH=os.path.join(d, "scratch"))
        me = os.path.abspath(__file__)
        ps = [subprocess.Popen([sys.executable, me, n, os.path.join(d, "p" + n)], env=env, stdout=subprocess.PIPE) for n in ("a", "b")]
        for p in ps: p.communicate(timeout=300)
        ev = [l.split() for l in th_stub.read_lines(log)]
        starts = sorted(float(e[1]) for e in ev if e[0] == "start"); ends = sorted(float(e[1]) for e in ev if e[0] == "end")
        chk("two concurrent callers ran one after the other (second TruffleHog started after the first ended)", len(starts) == 2 and len(ends) == 2 and starts[1] >= ends[0] and all(p.returncode == 0 for p in ps))
        rows = [json.load(open(os.path.join(out, n + ".json"))) for n in ("a", "b")] if all(os.path.exists(os.path.join(out, n + ".json")) for n in ("a", "b")) else []
        chk("both receipts are clean, carry K/workers/scan_s/parts/batches/parts_per_s read back from the run", len(rows) == 2 and all(r["clean"] and r["parts"] == 1 and r["batches"] == 1 and r["scan_s"] and r["parts_per_s"] and r["K"] and r["workers"] for r in rows))
        chk("the lock is released after the run", not os.path.exists(lock))
        dead = subprocess.Popen([sys.executable, "-c", "pass"]); dead.wait()
        json.dump(dict(pid=dead.pid), open(lock, "w"))
        env2 = dict(env, TH_STUB_MODE="clean"); t0 = time.time()
        p = subprocess.run([sys.executable, me, "c", os.path.join(d, "pa")], env=env2, stdout=subprocess.PIPE, timeout=120)
        chk("a stale lock (dead pid) is taken over and the scan runs", p.returncode == 0 and json.load(open(os.path.join(out, "c.json")))["clean"] is True and not os.path.exists(lock))
        live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            json.dump(dict(pid=live.pid), open(lock, "w"))
            p = subprocess.run([sys.executable, me, "e", os.path.join(d, "pa")], env=env2, stdout=subprocess.PIPE, timeout=120)
            chk("a lock held by a live pid that is NOT a th_pack_scan process (pid reuse) is taken over", p.returncode == 0 and json.load(open(os.path.join(out, "e.json")))["clean"] is True)
        finally:
            live.terminate()
        os.makedirs(os.path.dirname(lock), exist_ok=True)
        json.dump(dict(pid=os.getpid()), open(lock, "w"))      # this very process: a live th_pack_scan owner (its cmdline names th_pack_scan.py)
        try:
            acquire_lock(lock, wait_s=2, poll_s=0.5); got = True
        except th_gate.ThError:
            got = False
        chk("a lock held by a live th_pack_scan process is NOT stolen: the wait is bounded and then raises (fail closed)", got is False and os.path.exists(lock))
        os.remove(lock)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        selftest()
    else:
        main(sys.argv[1], sys.argv[2].replace("\\", "/"))
