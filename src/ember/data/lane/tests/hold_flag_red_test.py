# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green for hold_flag.py and fetch_open_model --hold-flag (lead 82475): the uploader hold is released by the fetch's own completion, only when it is ours, receipt first.
Run: python scripts/tests/hold_flag_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import os, sys, json, time, tempfile, subprocess, threading, shutil
pass
import hold_flag as H
ok = True
def check(l, c):
    global ok; ok &= bool(c); print("PASS" if c else "FAIL", l)
T = tempfile.mkdtemp(dir=(LANE_ROOT + "/scratch")); rc = T + "/rel.jsonl"; fl = T + "/RESTORE-PRIORITY.flag"
open(fl, "w").write("LANE-FETCH-HOLD 2026-11-10: test hold\n")
check("GREEN our flag is released", H.release(fl, "unit", rc) == "released" and not os.path.exists(fl))
rows = [json.loads(l) for l in open(rc)]
check("GREEN a receipt row (flag text, reason) was written", len(rows) == 1 and rows[0]["reason"] == "unit" and rows[0]["flag_text"].startswith("LANE-FETCH-HOLD"))
open(fl, "w").write("checkpoint restore has the downlink (training)\n")
check("RED a flag without our marker (the checkpoint-restore hold) is never touched", H.release(fl, "unit", rc) == "not-ours" and os.path.exists(fl) and len(open(rc).read().splitlines()) == 1)
os.remove(fl)
check("GREEN an absent flag is a no-op", H.release(fl, "unit", rc) == "absent")
open(fl, "w").write("LANE-FETCH-HOLD again\n")
p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"])
res = {}
t = threading.Thread(target=lambda: res.setdefault("r", H.wait_then_release(p.pid, fl, "unit wait", poll=0.3, receipts=rc))); t.start()
time.sleep(1.2)
check("RED the flag stays while the fetch process is alive", os.path.exists(fl) and "r" not in res)
t.join(30)
check("GREEN the flag is released when the fetch process exits, receipt reason names the pid", res.get("r") == "released" and not os.path.exists(fl) and "exited" in json.loads(open(rc).read().splitlines()[-1])["reason"])
src = open((LANE_ROOT + "/scripts/fetch_open_model.py"), encoding="utf-8").read()
check("source: fetch_open_model releases the hold in a finally block and __main__ goes through run()", "finally:" in src and "hold_flag.release(ns.hold_flag" in src and 'sys.exit(run())' in src)
shutil.rmtree(T, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
