# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red for the upload-tick scan gate (lead 82933): python scripts/tests/tick_upload_scan_skip_red_test.py
The REAL upload() of loops/tick.py runs against a temp lane (stubbed Hub, spawn, mail, cap check, signature). Checks:
 a) a REFUSED pack in the queue (never PASS): no push attempt (no `hf upload` spawn), no mail, no cap check, no blocked tick, the pack is named as skipped
 b) a NOT RUN pack (no scan row): no push attempt, no mail, not blocked (a scan may be started, never a push)
 c) a scan RUNNING: no push, not blocked
 d) a pack that was PASS (scan_pass recorded) and is now REFUSED: blocked (the only escalation)
 e) control: a clean pack still gets the push spawn and records scan_pass
Exits 0 on ALL PASS. Needs no network and no live lane files."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import HF_TRAIN_REPO
import json, os, sys, types, tempfile, glob, time, hashlib

LANE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))      # the lane dir this test sits in (live scripts/ or the tree copy)
SRC = open(os.environ.get("TICK_SRC", LANE + "/loops/tick.py"), encoding="utf-8").read()
PSS = os.environ.get("PSS_DIR", LANE)
sys.path.insert(0, PSS)
import pack_scan_status as real_pss

i = SRC.index("\ndef upload()"); j = SRC.index("\ndef census()")
UPLOAD_SRC = SRC[i:j]
ok = True
def chk(n, c):
    global ok; print(("PASS " if c else "FAIL ") + n); ok = ok and bool(c)


class Done(Exception):
    def __init__(self, status, note): self.status, self.note = status, note


def run_case(rec, scan_pass=False, running=False):
    """rec: None (no scan row) | dict scan row (signature filled in). Returns (done, spawns, mails, cap_calls, items_after)."""
    root = tempfile.mkdtemp(); loops = root + "/loops"; os.makedirs(loops); os.makedirs(root + "/logs/th-scan")
    local = root + "/packed/pk"; os.makedirs(local + "/shards"); open(local + "/shards/s0.zst", "wb").write(b"x" * 10); open(local + "/intake.json", "w").write("{}")
    it = dict(name="train-pk", repo=("wordingone/" + HF_TRAIN_REPO), path="text/pk", local=local, approved_by="test")
    if scan_pass: it["scan_pass"] = "2026-11-10T00:00:00"
    json.dump([it], open(loops + "/approved-uploads.json", "w"))
    if rec is not None: json.dump(dict(rec, signature="SIG"), open(root + "/logs/th-scan/train-pk.json", "w"))
    spawns, mails, caps = [], [], []
    ns = dict(os=os, sys=sys, json=json, time=time, glob=glob, hashlib=hashlib, ROOT=root, L=loops,
              mglob=lambda t: [], gate_ok=lambda *a: False, sha256f=lambda p: "0",
              alive=lambda pat: 0, scan_pids=lambda n: ([4242] if running else []),
              spawn=lambda cmd, log: (spawns.append(cmd) or True))
    def done(status, note): raise Done(status, note)
    ns["done"] = done
    # stubs for the modules upload() imports (sys.modules wins over sys.path)
    stub_ur = types.ModuleType("upload_refuse"); stub_ur.refused = lambda p: False
    stub_cap = types.ModuleType("hf_cap"); stub_cap.check = lambda *a, **k: (caps.append(a) or True)
    stub_th = types.ModuleType("th_pack_scan"); stub_th.signature = lambda p: "SIG"
    stub_mb = types.ModuleType("mb_send"); stub_mb.send = lambda *a, **k: mails.append(a)
    class _Api:
        def list_repo_tree(self, *a, **k): return iter([])      # nothing on the Hub: every local file is missing
    stub_hf = types.ModuleType("huggingface_hub"); stub_hf.HfApi = _Api
    old = {k: sys.modules.get(k) for k in ("upload_refuse", "hf_cap", "th_pack_scan", "mb_send", "huggingface_hub", "pack_scan_status")}
    sys.modules.update(upload_refuse=stub_ur, hf_cap=stub_cap, th_pack_scan=stub_th, mb_send=stub_mb, huggingface_hub=stub_hf, pack_scan_status=real_pss)
    d = None
    try:
        exec(UPLOAD_SRC, ns)
        try: ns["upload"]()
        except Done as e: d = (e.status, e.note)
    finally:
        for k, v in old.items():
            if v is None: sys.modules.pop(k, None)
            else: sys.modules[k] = v
    items = json.load(open(loops + "/approved-uploads.json"))
    return d, spawns, mails, caps, items[0]


def pushes(spawns): return [s for s in spawns if s.startswith("hf upload")]

# a) REFUSED, never PASS
d, sp, ml, cp, it = run_case(dict(clean=False, hits={"AWS": 3}, hit_files={"a": 1}))
chk("a) REFUSED never-PASS: no push attempt", not pushes(sp))
chk("a) REFUSED never-PASS: no mail", not ml)
chk("a) REFUSED never-PASS: no cap check", not cp)
chk("a) REFUSED never-PASS: tick is not blocked (status %s)" % (d and d[0]), d and d[0] != "blocked")
chk("a) REFUSED never-PASS: named as skipped", d and "skipped by scan state" in d[1] and "train-pk" in d[1])
chk("a) REFUSED never-PASS: no scan_pass recorded", "scan_pass" not in it)
# b) NOT RUN
d, sp, ml, cp, it = run_case(None)
chk("b) NOT RUN: no push attempt", not pushes(sp))
chk("b) NOT RUN: no mail, no cap check", not ml and not cp)
chk("b) NOT RUN: not blocked (status %s)" % (d and d[0]), d and d[0] != "blocked")
# c) running
d, sp, ml, cp, it = run_case(None, running=True)
chk("c) scan running: no push, not blocked", not pushes(sp) and d and d[0] != "blocked")
# d) was PASS, now REFUSED
d, sp, ml, cp, it = run_case(dict(clean=False, hits={"AWS": 3}, hit_files={"a": 1}), scan_pass=True)
chk("d) was-PASS now REFUSED: blocked (escalates)", d and d[0] == "blocked" and "REFUSED" in d[1])
chk("d) was-PASS now REFUSED: still no push attempt", not pushes(sp))
# e) control: clean
d, sp, ml, cp, it = run_case(dict(clean=True, hits={}, hit_files={}))
chk("e) clean: push spawned", len(pushes(sp)) == 1)
chk("e) clean: scan_pass recorded on the item", bool(it.get("scan_pass")))
# pure function
chk("push_decision table", [real_pss.push_decision(s, w) for s, w in (("clean", False), ("running", False), ("refused", False), ("refused", True), ("unknown", True))] == ["push", "wait", "skip", "escalate", "skip"])
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
