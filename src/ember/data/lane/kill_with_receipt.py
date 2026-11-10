# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Kill discipline (lead 82049): the ONLY way data kills a process. Writes the receipt row to <m-root>/avir/infra/vigil/kill-receipts.jsonl BEFORE the kill (pid, verified cmdline read live, reason), then Stop-Process.
Usage: python kill_with_receipt.py --reason "why" PID [PID ...]     (--dry = receipt-less preview).  Refuses without --reason.  Also: late(): append a late receipt (no kill)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import M_ROOT, SEAT_DATA
import sys, os, json, subprocess, time, argparse
RC = (M_ROOT + "/avir/infra/vigil/kill-receipts.jsonl")


def cmdline(pid):
    r = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Process -Filter 'ProcessId=%d').CommandLine" % pid], capture_output=True, text=True)
    return r.stdout.strip()


def receipt(pid, reason, cl, verified, extra=None):
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "actor": SEAT_DATA, "seat": SEAT_DATA, "pid": pid, "reason": reason, "cmdline": cl, "cmdline_verified": verified}
    row.update(extra or {})
    with open(RC, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--reason", required=True); ap.add_argument("--dry", action="store_true"); ap.add_argument("pids", nargs="+", type=int)
    a = ap.parse_args()
    for pid in a.pids:
        if pid <= 4:
            print(pid, "refused: system/invalid pid"); continue
        cl = cmdline(pid)
        if not cl:
            print(pid, "no such process / no cmdline; skipped"); continue
        if a.dry:
            print("DRY", pid, cl[:200]); continue
        receipt(pid, a.reason, cl, True)                                    # receipt FIRST
        r = subprocess.run(["powershell", "-NoProfile", "-Command", "Stop-Process -Id %d -Force" % pid], capture_output=True, text=True)
        print("killed", pid, "rc", r.returncode, r.stderr.strip()[:100])


if __name__ == "__main__":
    main()
