# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Detached tick runner for the MECHANICAL data-lane ticks (lead 82344): upload, fetch, census run here on a fixed schedule with no LLM session in the loop.
The judgment ticks (intake: NEW_PACKED pointers to the training seat; prep) stay as session crons.

  python scripts/loops/run_loops.py            start (exits at once if another runner holds the singleton lock)
  python scripts/loops/run_loops.py --once X   run tick X once through the same wrapper (used by the red test)

Guarantees
  - ONE runner: an exclusive OS lock on loops/run-loops.lock for the life of the process (a second start exits 0 after printing who holds it).
  - ONE instance of each tick at a time: a tick that is still running is skipped (never stacked) and the skip is logged.
  - Per-tick timeout (kills the tick's own process tree via kill_with_receipt.py, receipt first); BELOW_NORMAL priority; output appended to logs/run-loops.log.
  - Heartbeat loops/run-loops.heartbeat.json {ts, pid, last: {tick: {ts, rc, secs, line}}} written every cycle, so a watcher can alarm on a stale heartbeat.
  - The tick's own receipt row (loops/receipts.jsonl) is written by tick.py as before.
  - Mail (mb_send, read back by subject): a tick line containing ESCALATE -> lead, once per tick per hour; '<pack>: VERIFIED <n> files' -> lead, once per pack (loops/verified-mailed.json).
Schedule (minutes past the hour, local clock): upload 22,52; fetch 7,27,47; census 37. Late ticks run as soon as the runner is free (no catch-up pile-up: at most one run per slot)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT, SEAT_LEAD
import os, sys, json, time, subprocess, re, msvcrt
from lane_config import LANE_ROOT as ROOT; L = ROOT + "/loops"; LOG = ROOT + "/logs/run-loops.log"
SCHEDULE = {"upload": (22, 52), "fetch": (7, 27, 47), "census": (37,)}
TIMEOUT_S = {"upload": 40 * 60, "fetch": 40 * 60, "census": 30 * 60}
HEART = L + "/run-loops.heartbeat.json"; VM = L + "/verified-mailed.json"


def log(*a):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f: f.write(time.strftime("%Y-%m-%dT%H:%M:%S ") + " ".join(str(x) for x in a) + "\n")


def take_lock(path=L + "/run-loops.lock"):
    """-> open handle holding an exclusive lock, or None if another runner holds it."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fh = open(path, "a+b"); fh.seek(0)
    try: msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        fh.close(); return None
    fh.truncate(0); fh.write(str(os.getpid()).encode()); fh.flush(); return fh


def mail(subject, body):
    try:
        sys.path.insert(0, ROOT + "/scripts"); import mb_send
        return mb_send.send(SEAT_LEAD, subject, body)
    except Exception as e:
        log("MAIL FAILED", type(e).__name__, str(e)[:160]); return None


def after_tick(name, out):
    """Mechanical relays: ESCALATE and first-time VERIFIED packs go to lead."""
    line = out.strip().splitlines()[-1] if out.strip() else ""
    if "ESCALATE" in line:
        key = f"{name}-{time.strftime('%Y%m%d%H')}"; st = json.load(open(VM)) if os.path.exists(VM) else {}
        if not st.get("esc", {}).get(key):
            mid = mail(f"ESCALATE from the {name} tick (runner)", line[:3500])
            if mid: st.setdefault("esc", {})[key] = mid; json.dump(st, open(VM, "w"))
    if name == "upload":
        st = json.load(open(VM)) if os.path.exists(VM) else {}; done = st.setdefault("verified", {})
        for m in re.finditer(r"(train-[\w.\-]+): VERIFIED (\d+) files vs HF", line):
            pk, n = m.group(1), m.group(2)
            if pk in done: continue
            ap = json.load(open(L + "/approved-uploads.json")); it = next((i for i in ap if i["name"] == pk), {})
            mid = mail(f"VERIFIED: {pk} on {it.get('repo', 'the private train repo')}", f"{pk}: {n} files verified against HF (size + server LFS sha256), repo {it.get('repo', '?')}, path {it.get('path', '?')}. Sent by the detached tick runner (scripts/loops/run_loops.py).")
            if mid: done[pk] = mid; json.dump(st, open(VM, "w"))


def run_tick(name, running):
    """Run one tick as a child; returns (rc, secs, last_line). A tick already running is skipped (rc None)."""
    if name in running and running[name].poll() is None:
        log("SKIP", name, "previous run still alive pid", running[name].pid); return None, 0, "skipped: previous run alive"
    t0 = time.time()
    p = subprocess.Popen([sys.executable, ROOT + "/scripts/loops/tick.py", name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", cwd=ROOT,
                         creationflags=0x00004000 | 0x08000000, env=dict(os.environ, PYTHONIOENCODING="utf-8"))      # BELOW_NORMAL | CREATE_NO_WINDOW
    running[name] = p
    try: out, _ = p.communicate(timeout=TIMEOUT_S[name])
    except subprocess.TimeoutExpired:
        log("TIMEOUT", name, "pid", p.pid, "-> kill_with_receipt")
        subprocess.run([sys.executable, ROOT + "/scripts/kill_with_receipt.py", "--reason", f"run_loops: {name} tick exceeded {TIMEOUT_S[name]}s", str(p.pid)], capture_output=True)
        try: out, _ = p.communicate(timeout=30)
        except Exception: out = ""
    secs = round(time.time() - t0, 1); line = (out or "").strip().splitlines()[-1][:600] if (out or "").strip() else ""
    log(name, "rc", p.returncode, f"{secs}s", line[:300])
    try: after_tick(name, out or "")
    except Exception as e: log("after_tick error", name, type(e).__name__, str(e)[:160])
    return p.returncode, secs, line


def due(now, last_slot):
    """-> [(tick, slot_epoch)] whose latest passed slot (this or the previous hour) has not run yet; one run per slot, no catch-up pile-up. now = epoch seconds."""
    lt = time.localtime(now); h0 = now - lt.tm_min * 60 - lt.tm_sec - (now % 1)      # epoch of the start of the current local hour
    out = []
    for name, mins in SCHEDULE.items():
        slots = sorted(h0 + dh * 3600 + m * 60 for dh in (-1, 0) for m in mins)
        passed = [x for x in slots if x <= now]
        if passed and passed[-1] > last_slot.get(name, 0): out.append((name, passed[-1]))
    return out


def main():
    if "--once" in sys.argv:
        r = run_tick(sys.argv[sys.argv.index("--once") + 1], {}); print(r); return
    fh = take_lock()
    if fh is None:
        print("run_loops: another runner holds loops/run-loops.lock; exiting"); return
    log("runner start pid", os.getpid()); running = {}; last_slot = {}; last = {}
    for name, mins in SCHEDULE.items(): last_slot[name] = time.time() - 1        # do not fire a backlog at start: wait for the next slot
    while True:
        for name, slot in due(time.time(), last_slot):
            last_slot[name] = slot; rc, secs, line = run_tick(name, running); last[name] = dict(ts=time.strftime("%Y-%m-%dT%H:%M:%S"), rc=rc, secs=secs, line=line[:300])
        json.dump(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%S"), pid=os.getpid(), last=last), open(HEART, "w"))
        time.sleep(20)


if __name__ == "__main__":
    main()
