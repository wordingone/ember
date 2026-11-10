# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Stale drivers (lead 82534): a long-lived lane process keeps the OLD code of every module it imported at start. After a gate edit (reserve_plan, text_lane, bulk_lane, pack, verified_remove ...) the drivers started before the edit still run the old gate: 2026-11-10 the 02:41 text_lane drivers ignored the 316 floor for 14 h.
line() -> one tick line: lists each running lane process (python script under scripts/) whose own file or any scripts/ module it imports (transitively) was modified after the process started.  Read-only; never stops anything: restart a stale driver at a step boundary with scripts/kill_lane.ps1.
Usage: python stale_drivers.py   (prints the line);  stale_drivers.line() from the tick."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, re, ast, time, sys

SCRIPTS = os.environ.get("STALE_SCRIPTS", (LANE_ROOT + "/scripts")).replace("\\", "/")
SLACK = 3.0   # seconds: a file written at process start is not newer


def _imports(path, seen, depth=0):
    """-> set of absolute paths of scripts/ modules imported by path (transitively, depth<=4)"""
    out = set()
    if depth > 4 or path in seen: return out
    seen.add(path)
    try: tree = ast.parse(open(path, encoding="utf-8", errors="replace").read())
    except Exception: return out
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import): names.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level: names.add(n.module.split(".")[0])
    for nm in names:
        p = "%s/%s.py" % (SCRIPTS, nm)
        if os.path.isfile(p):
            out.add(p); out |= _imports(p, seen, depth + 1)
    return out


def script_of(cmdline):
    """the scripts/*.py a python process runs (first argv ending .py that resolves under SCRIPTS), else None"""
    for a in cmdline[1:]:
        a = a.replace("\\", "/")
        if not a.endswith(".py"): continue
        p = a if re.match(r"^[A-Za-z]:/", a) else SCRIPTS.rsplit("/scripts", 1)[0] + "/" + a
        p = os.path.normpath(p).replace("\\", "/")
        if p.startswith(SCRIPTS + "/") and os.path.isfile(p): return p
        return None
    return None


def stale(procs, mtime=os.path.getmtime):
    """procs: iterable of (pid, create_time_epoch, cmdline list) -> [(pid, script, [(module, mtime_epoch)...], started_epoch)]"""
    res = []
    for pid, started, cmd in procs:
        if not cmd or "python" not in os.path.basename(cmd[0]).lower(): continue
        s = script_of(cmd)
        if not s: continue
        mods = {s} | _imports(s, set())
        newer = sorted(((os.path.basename(m)[:-3], mtime(m)) for m in mods if mtime(m) > started + SLACK), key=lambda x: -x[1])
        if newer: res.append((pid, os.path.basename(s)[:-3] + (" " + " ".join(a for a in cmd[2:4] if not a.startswith("-") and "/" not in a and "\\" not in a)).rstrip(), newer, started))
    return res


def _procs():
    import psutil
    for p in psutil.process_iter(["pid", "create_time", "cmdline"]):
        try: yield p.info["pid"], p.info["create_time"], p.info["cmdline"] or []
        except Exception: pass


def line(procs=None, mtime=os.path.getmtime, show=8):
    try:
        r = stale(list(procs) if procs is not None else _procs(), mtime)
    except Exception as e:
        return "stale_drivers error %s: %s" % (type(e).__name__, e)
    if not r: return "stale_drivers 0"
    hm = lambda t: time.strftime("%H:%M", time.localtime(t))
    return "STALE_DRIVERS %d (restart each at a step boundary; kill_lane.ps1): " % len(r) + "; ".join("pid %d %s: %s edited %s > start %s" % (pid, nm, nw[0][0], hm(nw[0][1]), hm(st)) + ("+%d" % (len(nw) - 1) if len(nw) > 1 else "") for pid, nm, nw, st in sorted(r, key=lambda x: x[3])[:show]) + ("; +%d more" % (len(r) - show) if len(r) > show else "")


if __name__ == "__main__":
    print(line())
