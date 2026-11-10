# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Owner-stamped scratch directories, so a finished (or killed) job never leaves bytes behind on B: (lead 82361).

make(prefix)  -> a fresh directory under the scratch root with a `.owner` stamp (pid, process create time, argv0, created). Use as a context manager: `with ScratchDir("th-") as d:`; the directory is removed on normal exit, on an exception, and
                 at interpreter exit (atexit). A process that is killed cannot run any of that, so:
sweep()       -> removes every stamped directory whose owner process is gone (pid dead, or the pid now belongs to a process created at another time) and whose stamp is older than `min_age_s`; one receipt row per removal is appended
                 to logs/scratch-sweep.jsonl BEFORE the removal. Directories without a stamp are never touched (they belong to people, not to a writer). The tick runner calls sweep() every tick.
Red: python scripts/tests/scratch_dir_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, time, shutil, atexit, tempfile

BASE = os.environ.get("SCRATCH_ROOT", (LANE_ROOT + "/scratch"))
LOG = os.environ.get("SCRATCH_SWEEP_LOG", (LANE_ROOT + "/logs/scratch-sweep.jsonl"))
STAMP = ".owner"


def _proc_ct(pid):
    try:
        import psutil
        return psutil.Process(pid).create_time()
    except Exception:
        return None


def make(prefix, root=None):
    root = root or BASE; os.makedirs(root, exist_ok=True)
    d = tempfile.mkdtemp(dir=root, prefix=prefix)
    json.dump(dict(pid=os.getpid(), create_time=_proc_ct(os.getpid()), argv0=os.path.basename(sys.argv[0]) if sys.argv else "", created=time.time()), open(os.path.join(d, STAMP), "w"))
    return d.replace("\\", "/")


class ScratchDir:
    def __init__(self, prefix, root=None): self.path = make(prefix, root); atexit.register(self.cleanup)

    def cleanup(self):
        shutil.rmtree(self.path, ignore_errors=True)

    def __enter__(self): return self.path

    def __exit__(self, *a): self.cleanup(); return False


def _tree_bytes(d):
    t = 0
    for dp, _, fs in os.walk(d):
        for f in fs:
            try: t += os.lstat(os.path.join(dp, f)).st_size
            except OSError: pass
    return t


def owner_alive(stamp):
    import psutil
    pid = stamp.get("pid")
    if not pid or not psutil.pid_exists(pid): return False
    ct = _proc_ct(pid)
    return ct is not None and (stamp.get("create_time") is None or abs(ct - stamp["create_time"]) < 2.0)


def sweep(root=None, min_age_s=300, log=None, now=None):
    """Remove stamped scratch dirs whose owner is gone. Returns [(dir, bytes)]."""
    root = root or BASE; log = log or LOG; now = now or time.time(); out = []
    if not os.path.isdir(root): return out
    for e in sorted(os.listdir(root)):
        d = os.path.join(root, e); sp = os.path.join(d, STAMP)
        if not os.path.isfile(sp): continue
        try: stamp = json.load(open(sp))
        except Exception: continue
        if now - float(stamp.get("created", now)) < min_age_s or owner_alive(stamp): continue
        n = _tree_bytes(d)
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), dir=d.replace("\\", "/"), bytes=n, owner=stamp, why="owner process gone, stamped scratch left behind")) + "\n")
        shutil.rmtree(d, ignore_errors=True); out.append((d.replace("\\", "/"), n))
    return out


if __name__ == "__main__":
    r = sweep()
    print("swept", len(r), "dirs", round(sum(b for _, b in r) / 2**30, 3), "GiB")
