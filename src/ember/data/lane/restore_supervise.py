# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Supervise the H39 ancestor restore (lead 82044; stall seen 2026-11-09 14:02 KST: 0.04 MB/s NIC, +0.1 s CPU, 2 TCP conns, ledger frozen).
Runs `ckpt_restore.py run --chain H39 --only all` with RESTORE_WORKERS=8 (resumable by sha; partial downloads resume). A STALL = no new ledger row, no growth of scratch/restore bytes and < 2 s CPU in the restore process over STALL_S (default 420 s)
-> kill the restore through kill_with_receipt.py (receipt first, verified PID) and relaunch. When ckpt_restore exits 0 it appends `STAGE2-EXIT 0` to logs/ckpt-restore2.log (what restore_finish.py waits for); non-zero exits are retried up to MAX_TRIES.
Usage (detached): python scripts/restore_supervise.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, time, subprocess, json
L = (LANE_ROOT + "/logs/"); LOG = L + "ckpt-restore2.log"; LEDGER = L + "ckpt-restore.jsonl"; SCR = (LANE_ROOT + "/scratch/restore")
STALL_S = int(os.environ.get("STALL_S", "420")); MAX_TRIES = int(os.environ.get("MAX_TRIES", "30"))


def log(m):
    with open(LOG, "a") as f:
        f.write("%s SUPERVISOR %s\n" % (time.strftime("%H:%M:%S"), m))


def rows():
    try:
        return sum(1 for _ in open(LEDGER))
    except OSError:
        return 0


def scr_bytes():
    t = 0
    for r, _, fs in os.walk(SCR):
        for f in fs:
            try:
                t += os.path.getsize(os.path.join(r, f))
            except OSError:
                pass
    return t


def cpu(pid):
    r = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-Process -Id %d -ErrorAction SilentlyContinue).CPU" % pid], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def main():
    env = dict(os.environ, RESTORE_WORKERS="8")
    for attempt in range(1, MAX_TRIES + 1):
        with open(LOG, "a") as out:
            p = subprocess.Popen([sys.executable, "scripts/ckpt_restore.py", "run", "--chain", "H39", "--only", "all"], cwd=LANE_ROOT, env=env, stdout=out, stderr=subprocess.STDOUT)
        log("attempt %d started pid=%d" % (attempt, p.pid))
        last = (rows(), scr_bytes(), cpu(p.pid) or 0.0); t_last = time.time()
        while p.poll() is None:
            time.sleep(30)
            cur = (rows(), scr_bytes(), cpu(p.pid))
            if cur[2] is None:
                continue
            if cur[0] != last[0] or cur[1] != last[1] or cur[2] - last[2] >= 2.0:
                last = cur; t_last = time.time(); continue
            if time.time() - t_last > STALL_S:
                log("STALL pid=%d rows=%d bytes=%d cpu_delta<2s for %ds -> kill+relaunch" % (p.pid, cur[0], cur[1], STALL_S))
                subprocess.run([sys.executable, (LANE_ROOT + "/scripts/kill_with_receipt.py"), "--reason", "restore_supervise stall: no ledger rows, no scratch growth, <2s CPU for %ds; relaunching resumable restore" % STALL_S, str(p.pid)])
                break
        rc = p.wait() if p.poll() is None else p.returncode
        if rc == 0:
            with open(LOG, "a") as f:
                f.write("STAGE2-EXIT 0\n")
            return
        log("attempt %d ended rc=%s; retrying" % (attempt, rc)); time.sleep(10)
    with open(LOG, "a") as f:
        f.write("STAGE2-EXIT 1 (MAX_TRIES exhausted)\n")


if __name__ == "__main__":
    main()
