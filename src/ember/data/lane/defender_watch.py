# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Sample MsMpEng CPU every 30 s (lead 83165): one line per sample to logs/defender-watch.jsonl with the top 4 other CPU users, and
loops/DEFENDER-UNDER-1CORE.flag present only while the last 10 samples (5 min) were all below 100% of one core. Read-only; never touches Defender or any process.
Write chains stay suspended until the flag exists AND lead lifts the load cut."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import json, os, time, psutil
from lane_config import LANE_ROOT as ROOT; LOG = ROOT + "/logs/defender-watch.jsonl"; FLAG = ROOT + "/loops/DEFENDER-UNDER-1CORE.flag"
WIN = 10; INTERVAL = 30
recent = []


def snap():
    return {p.pid: (p.name(), sum(p.cpu_times()[:2])) for p in psutil.process_iter() if _ok(p)}


def _ok(p):
    try: p.cpu_times(); return True
    except Exception: return False


while True:
    a = {}
    for p in psutil.process_iter():
        try: a[p.pid] = (p, sum(p.cpu_times()[:2]))
        except Exception: pass
    t0 = time.time(); time.sleep(INTERVAL); dt = time.time() - t0
    rows = []
    for pid, (p, c0) in a.items():
        try: rows.append(((sum(p.cpu_times()[:2]) - c0) / dt * 100, pid, p.name(), p))
        except Exception: continue
    rows.sort(key=lambda r: -r[0])
    for i, r in enumerate(rows[:10]):      # cmdline/parent only for the few that matter (the full sweep cost ~35% of a core)
        cmd, par = "", ""
        try: cmd = " ".join(r[3].cmdline())[:90]
        except Exception: cmd = "(protected)"
        if r[2].lower() in ("du.exe", "find.exe"):
            try: par = " parent=" + ((r[3].parent().name() + ":" + str(r[3].ppid())) if r[3].parent() else "orphan")
            except Exception: par = " parent=?"
        rows[i] = (r[0], r[1], r[2], cmd + par)
    rows = [(r[0], r[1], r[2], r[3] if isinstance(r[3], str) else "") for r in rows]
    mp = sum(r[0] for r in rows if r[2].lower() == "msmpeng.exe")
    others = [dict(cpu=round(r[0]), pid=r[1], name=r[2], cmd=r[3]) for r in rows if r[2].lower() not in ("msmpeng.exe", "system idle process")][:4]
    recent.append(mp); del recent[:-WIN]
    ok = len(recent) == WIN and max(recent) < 100
    with open(LOG, "a", encoding="utf-8") as f: f.write(json.dumps(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%S%z"), msmpeng_pct=round(mp), under_1core_5min=ok, top_others=others)) + "\n")
    if ok and not os.path.exists(FLAG): open(FLAG, "w").write(time.strftime("%Y-%m-%dT%H:%M:%S"))
    if not ok and os.path.exists(FLAG): os.remove(FLAG)
