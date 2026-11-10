# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Reds for the tick upload gates (python scripts/tests/tick_gates_red_test.py). 1) a stale C1/C2 PASS (candidate_sha256 != intake ledger_sha256) is refused; 2) a matching PASS accepted; 3) FAIL refused;
4) old-format verdict (no candidate_sha256) accepted on PASS only; 5) unreadable verdict refused; 6) tick upload and upload_worker both hold while RESTORE-PRIORITY.flag exists (source-level)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import json, os, sys, tempfile
SRC = open((LANE_ROOT + "/scripts/loops/tick.py"), encoding="utf-8").read()
i = SRC.index("def gate_ok"); ns = {"json": json}; exec(SRC[i:SRC.index("\ndef ", i + 5)], ns); g = ns["gate_ok"]
d = tempfile.mkdtemp(); ok = True
def w(n, o):
    p = os.path.join(d, n); json.dump(o, open(p, "w")); return p
def chk(n, c):
    global ok; print(("PASS " if c else "FAIL ") + n); ok = ok and bool(c)
it = w("intake.json", {"ledger_sha256": "NEW"})
chk("RED stale PASS refused", g(w("a.json", {"verdict": "PASS", "inputs": {"candidate_sha256": "OLD"}}), it) is False)
chk("matching PASS accepted", g(w("b.json", {"verdict": "PASS", "inputs": {"candidate_sha256": "NEW"}}), it) is True)
chk("FAIL refused", g(w("c.json", {"verdict": "FAIL", "inputs": {"candidate_sha256": "NEW"}}), it) is False)
chk("old-format PASS (no candidate_sha256) accepted", g(w("d.json", {"verdict": "PASS"}), it) is True)
chk("unreadable verdict refused", g(os.path.join(d, "missing.json"), it) is False)
chk("tick upload holds on RESTORE-PRIORITY.flag", 'RESTORE-PRIORITY.flag"): done("held"' in SRC)
chk("upload_worker holds on RESTORE-PRIORITY.flag", "RESTORE-PRIORITY.flag" in open((LANE_ROOT + "/scripts/upload_worker.py"), encoding="utf-8").read())
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
