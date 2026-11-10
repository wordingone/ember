# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fetch-hold flag release by the fetch's own completion (lead 82475), never by hand.
The hold flag (loops/RESTORE-PRIORITY.flag, text starting LANE-FETCH-HOLD) pauses the shared uploader while a model fetch needs the downlink. It is released by:
  (a) fetch_open_model.py --hold-flag PATH   (released in a finally block when the fetch returns, success or failure), or
  (b) python scripts/hold_flag.py --pid N --flag PATH --reason TEXT   (waits for that fetch process to exit, then releases; for a fetch started before (a) existed).
A flag that does not start with the marker (the checkpoint-restore hold, training's) is never touched. Every release appends a receipt row BEFORE the flag is removed: logs/fetch-hold-releases.jsonl."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, time, argparse

RECEIPTS = (LANE_ROOT + "/logs/fetch-hold-releases.jsonl")
MARKER = "LANE-FETCH-HOLD"


def release(flag, reason, receipts=RECEIPTS):
    """-> 'absent' | 'not-ours' | 'released'."""
    if not os.path.exists(flag):
        return "absent"
    txt = open(flag, encoding="utf-8", errors="replace").read(400)
    if not txt.startswith(MARKER):
        return "not-ours"
    row = dict(ts=time.strftime("%Y-%m-%dT%H:%M:%S"), flag=flag.replace("\\", "/"), flag_text=txt[:200], reason=reason)
    with open(receipts, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.remove(flag)
    return "released"


def wait_then_release(pid, flag, reason, poll=15.0, receipts=RECEIPTS):
    import psutil
    try:
        created = psutil.Process(pid).create_time()
    except psutil.NoSuchProcess:
        return release(flag, reason + " (process already gone)", receipts)
    while True:
        try:
            p = psutil.Process(pid)
            if p.create_time() != created or p.status() == psutil.STATUS_ZOMBIE:
                break
        except psutil.NoSuchProcess:
            break
        time.sleep(poll)
    return release(flag, reason + " (fetch process %d exited)" % pid, receipts)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--flag", required=True)
    ap.add_argument("--reason", default="fetch finished")
    a = ap.parse_args()
    print(wait_then_release(a.pid, a.flag, a.reason), flush=True)
