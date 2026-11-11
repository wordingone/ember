# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red for the upload-tick scan gate (lead 82933, PR 2467 review r1 item C and D): python scripts/tests/tick_upload_scan_skip_red_test.py
The REAL upload() of loops/tick.py runs against a temp lane (stubbed Hub, spawn, mail, cap check, signature, process listing); the REAL scan_listing/scan_pids run against a recorded listing. Checks:
 a) REFUSED by hits, never PASS: no push, no scan spawn, no mail, no cap check (the item's repo name ends in -private, so a cap call WOULD be counted), no blocked tick, named as skipped
 a2) REFUSED by hits and was PASS (scan_pass, or only `started` = pushed before scan_pass existed): blocked, no push
 b) NOT RUN (no record) / stale signature / unreadable record / scanner-error record, scan_tries 0..2: exactly one scan spawned, scan_tries incremented in the queue file, no push, no mail, no cap, not blocked
 b3) the same states at scan_tries 3: NO spawn, blocked, ONE mail (scan_escalated recorded), a second tick sends no second mail
 c) a scan RUNNING (listing names the process): no push, NO spawn, not blocked
 d) pid lookup raising: no push, no spawn, not blocked, no escalation even at scan_tries 3; the signature call raising: no push, no cap check, bounded by scan_tries
 e) clean pack: push spawned, scan_pass recorded, no scan spawn; a clean record that carries hits is REFUSED (no push)
 f) dispatch: any decision other than "push" (even an unknown one) never pushes
 g) mutant: a cap check placed before the scan decision makes the no-cap-check assertion FAIL (the assertion can fail)
 h) the REAL scan_listing/scan_pids on a recorded process listing: pid for NAME, none for another name or a prefix name, and an empty/garbled/failed listing RAISES (lookup failed, never 'not running')
 i) push_decision: every row of the decision table
Exits 0 on ALL PASS. Needs no network and no live lane files."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import json, os, sys, types, tempfile, glob, time, hashlib

LANE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))      # the lane dir this test sits in (live scripts/ or the tree copy)
SRC = open(os.environ.get("TICK_SRC", LANE + "/loops/tick.py"), encoding="utf-8").read()
sys.path.insert(0, LANE)
import pack_scan_status as real_pss

i = SRC.index("\ndef upload()"); j = SRC.index("\ndef census()")
UPLOAD_SRC = SRC[i:j]
si = SRC.index("def scan_listing()") if "def scan_listing()" in SRC else SRC.index("def scan_pids(")
SCAN_SRC = SRC[si:SRC.index("# ---- CPU cap")]
ok = True
nfail = 0
def chk(n, c):
    global ok, nfail; print(("PASS " if c else "FAIL ") + n); ok = ok and bool(c); nfail += (not c)
def case(fn):
    try: fn()
    except Exception as e:
        global ok, nfail
        print("FAIL %s raised %s: %s" % (fn.__name__, type(e).__name__, str(e)[:160])); ok = False; nfail += 1


class Done(Exception):
    def __init__(self, status, note): self.status, self.note = status, note


REAL = object()      # go(decision=...) default: use the real push_decision
REPO = "acct/test-train-private"      # ends in -private: a hf_cap.check call for it is counted, so "no cap check" can FAIL
RUN_LINE = (4242, "python.exe scripts/th_pack_scan.py train-pk packed/pk ")


def make_lane(rec="none", scan_pass=False, started=False, tries=None, escalated=False, rec_sig="SIG"):
    """rec: 'none' (no record file) | 'garbled' (invalid JSON file) | dict (record, signature = rec_sig)"""
    root = tempfile.mkdtemp(); loops = root + "/loops"; os.makedirs(loops); os.makedirs(root + "/logs/th-scan")
    local = root + "/packed/pk"; os.makedirs(local + "/shards"); open(local + "/shards/s0.zst", "wb").write(b"x" * 10); open(local + "/intake.json", "w").write("{}")
    it = dict(name="train-pk", repo=REPO, path="text/pk", local=local, approved_by="test")
    if scan_pass: it["scan_pass"] = "2026-11-10T00:00:00"
    if started: it["started"] = True
    if tries is not None: it["scan_tries"] = tries
    if escalated: it["scan_escalated"] = "2026-11-10T00:00:00"
    json.dump([it], open(loops + "/approved-uploads.json", "w"))
    rp = root + "/logs/th-scan/train-pk.json"
    if rec == "garbled": open(rp, "w").write("{not json")
    elif rec != "none": json.dump(dict(rec, signature=rec_sig), open(rp, "w"))
    return dict(root=root, loops=loops, spawns=[], mails=[], caps=[])


def go(lane, running=False, listing_raises=False, sig_raises=False, src=None, decision=REAL):
    """One upload() tick on the lane. -> (done, item_after). Spawns, mails and cap calls accumulate in the lane dict."""
    root, loops, spawns, mails, caps = lane["root"], lane["loops"], lane["spawns"], lane["mails"], lane["caps"]
    ns = dict(os=os, sys=sys, json=json, time=time, glob=glob, hashlib=hashlib, ROOT=root, L=loops, subprocess=None, SEAT_LEAD="lead", HF_TRAIN_REPO="x", M_ROOT=root,
              mglob=lambda t: [], gate_ok=lambda *a: False, sha256f=lambda p: "0", alive=lambda pat: 0,
              spawn=lambda cmd, log: (spawns.append(cmd) or True))
    def done(status, note): raise Done(status, note)
    ns["done"] = done
    exec(SCAN_SRC, ns)      # the REAL scan_listing / scan_pids ...
    def listing():
        if listing_raises: raise RuntimeError("process lookup rc=1")
        return [(4, ""), (812, "svchost.exe -k netsvcs")] + ([RUN_LINE] if running else [])
    ns["scan_listing"] = listing      # ... fed by a stub listing (the real parse is tested in h)
    stub_ur = types.ModuleType("upload_refuse"); stub_ur.refused = lambda p: False
    stub_cap = types.ModuleType("hf_cap"); stub_cap.check = lambda *a, **k: (caps.append(a) or True)
    stub_th = types.ModuleType("th_pack_scan")
    def _sig(p):
        if sig_raises: raise OSError("signature boom")
        return "SIG"
    stub_th.signature = _sig
    stub_mb = types.ModuleType("mb_send"); stub_mb.send = lambda *a, **k: mails.append(a)
    class _Api:
        def list_repo_tree(self, *a, **k): return iter([])      # nothing on the Hub: every local file is missing
    stub_hf = types.ModuleType("huggingface_hub"); stub_hf.HfApi = _Api
    pss = real_pss
    if decision is not REAL:
        pss = types.ModuleType("pack_scan_status"); pss.__dict__.update({k: v for k, v in real_pss.__dict__.items() if not k.startswith("__")}); pss.push_decision = lambda *a, **k: decision
    names = ("upload_refuse", "hf_cap", "th_pack_scan", "mb_send", "huggingface_hub", "pack_scan_status")
    old = {k: sys.modules.get(k) for k in names}
    sys.modules.update(upload_refuse=stub_ur, hf_cap=stub_cap, th_pack_scan=stub_th, mb_send=stub_mb, huggingface_hub=stub_hf, pack_scan_status=pss)
    d = None
    try:
        exec(src or UPLOAD_SRC, ns)
        try: ns["upload"]()
        except Done as e: d = (e.status, e.note)
    finally:
        for k, v in old.items():
            if v is None: sys.modules.pop(k, None)
            else: sys.modules[k] = v
    return d, json.load(open(loops + "/approved-uploads.json"))[0]


def pushes(l): return [s for s in l["spawns"] if s.startswith("hf upload")]
def scans(l): return [s for s in l["spawns"] if "th_pack_scan.py" in s]
def blocked(d): return bool(d) and d[0] == "blocked"
HITS = dict(clean=False, hits={"AWS": 3}, hit_files={"a": {"AWS": 3}})
ERR = dict(clean=False, hits={}, hit_files={}, error="trufflehog crashed")


def t_a():
    L = make_lane(HITS); d, it = go(L)
    chk("a) REFUSED never-PASS: no push attempt", not pushes(L))
    chk("a) REFUSED never-PASS: no scan spawn (the verdict is final for this file set)", not scans(L))
    chk("a) REFUSED never-PASS: no mail", not L["mails"])
    chk("a) REFUSED never-PASS: no cap check (repo name ends in -private)", not L["caps"] and REPO.endswith("-private"))
    chk("a) REFUSED never-PASS: tick is not blocked (status %s)" % (d and d[0]), d and not blocked(d))
    chk("a) REFUSED never-PASS: named as skipped", d and "skipped by scan state" in d[1] and "train-pk" in d[1])
    chk("a) REFUSED never-PASS: no scan_pass recorded", "scan_pass" not in it)
    for kw in (dict(scan_pass=True), dict(started=True)):
        L = make_lane(HITS, **kw); d, it = go(L)
        chk("a2) was-PASS (%s) now REFUSED by hits: blocked (escalates), still no push, no cap" % list(kw)[0], blocked(d) and "REFUSED" in d[1] and not pushes(L) and not L["caps"])


def t_b():
    variants = (("no record", "none", "SIG"), ("stale signature", dict(clean=True, hits={}, hit_files={}), "OLD"), ("unreadable record", "garbled", "SIG"), ("scanner-error record", ERR, "SIG"))
    for label, rec, rsig in variants:
        for tries in (None, 0, 1, 2):
            L = make_lane(rec, tries=tries, rec_sig=rsig); d, it = go(L)
            t = tries or 0
            chk("b) %s, scan_tries %s: exactly one scan spawned, tries -> %d, no push/mail/cap, not blocked" % (label, tries, t + 1),
                len(scans(L)) == 1 and it.get("scan_tries") == t + 1 and not pushes(L) and not L["mails"] and not L["caps"] and not blocked(d))
        L = make_lane(rec, tries=3, rec_sig=rsig); d, it = go(L)
        chk("b3) %s, scan_tries 3: no spawn, blocked, one mail naming the pack, scan_escalated recorded, no push" % label,
            not scans(L) and blocked(d) and len(L["mails"]) == 1 and "train-pk" in " ".join(str(x) for x in L["mails"][0]) and it.get("scan_escalated") and not pushes(L) and not L["caps"])
        d2, it2 = go(L)
        chk("b3) %s: a second tick is still blocked but sends NO second mail (mails exactly once)" % label, blocked(d2) and len(L["mails"]) == 1)


def t_c():
    for rec, label in (("none", "no record"), (ERR, "error record")):
        L = make_lane(rec, tries=0); d, it = go(L, running=True)
        chk("c) scan running (%s): no push, NO spawn, not blocked, tries untouched" % label, not pushes(L) and not scans(L) and d and not blocked(d) and it.get("scan_tries") == 0)
    L = make_lane("none", tries=3); d, it = go(L, running=True)
    chk("c) scan running at scan_tries 3: still wait, no escalation, no mail", not blocked(d) and not L["mails"] and not scans(L))


def t_d():
    for tries in (0, 3):
        L = make_lane("none", tries=tries); d, it = go(L, listing_raises=True)
        chk("d) pid lookup raises, scan_tries %d: no push, NO spawn, not blocked, no mail" % tries, not pushes(L) and not scans(L) and d and not blocked(d) and not L["mails"] and it.get("scan_tries") == tries)
    L = make_lane(ERR, tries=0); d, it = go(L, listing_raises=True)
    chk("d) pid lookup raises on an error record: no spawn, no push", not scans(L) and not pushes(L))
    L = make_lane(dict(clean=True, hits={}, hit_files={}), tries=0); d, it = go(L, sig_raises=True)
    chk("d) signature call raises: no push, no cap check", not pushes(L) and not L["caps"])
    chk("d) signature call raises: bounded (at most one scan this tick, tries counted)", len(scans(L)) <= 1 and it.get("scan_tries") == len(scans(L)))
    L = make_lane(dict(clean=True, hits={}, hit_files={}), tries=3); d, it = go(L, sig_raises=True)
    chk("d) signature call raises at scan_tries 3: escalates once, no spawn", not scans(L) and blocked(d) and len(L["mails"]) == 1)


def t_e():
    L = make_lane(dict(clean=True, hits={}, hit_files={}), tries=2, escalated=True); d, it = go(L)
    chk("e) clean: push spawned", len(pushes(L)) == 1)
    chk("e) clean: scan_pass recorded on the item", bool(it.get("scan_pass")))
    chk("e) clean: no scan spawned, retry state cleared", not scans(L) and "scan_tries" not in it and "scan_escalated" not in it)
    chk("e) clean: cap checked for the private repo", len(L["caps"]) == 1)
    L = make_lane(dict(clean=True, hits={"AWS": 1}, hit_files={"a": {"AWS": 1}})); d, it = go(L)
    chk("e) clean=true carrying hits is REFUSED: no push, no cap, no spawn, skipped", not pushes(L) and not L["caps"] and not scans(L) and d and not blocked(d))
    L = make_lane(dict(clean=True, hits={"AWS": 1}, hit_files={}), started=True); d, it = go(L)
    chk("e) clean=true carrying hits on a was-PASS item: blocked", blocked(d) and not pushes(L))


def t_f():
    for dec in ("bogus", "", None, "skip", "wait", "RESCAN", "escalate"):
        L = make_lane(dict(clean=True, hits={}, hit_files={})); d, it = go(L, decision=dec)
        chk("f) decision %r from a clean record: never pushes (anything other than 'push' does not push)" % (dec,), not pushes(L))


def t_g():
    mutant = UPLOAD_SRC.replace('            _st, _sd = _pss.pack_scan_status(', '            sys.path.insert(0, ROOT + "/scripts"); import hf_cap as _hc\n            if it["repo"].endswith("-private"): _hc.check(1, "mutant", "x")\n            _st, _sd = _pss.pack_scan_status(', 1)
    chk("g) the mutant source differs from the real one", mutant != UPLOAD_SRC)
    L = make_lane(HITS); go(L, src=mutant)
    chk("g) mutant (cap check before the scan decision): the no-cap-check assertion FAILS (%d cap calls counted)" % len(L["caps"]), len(L["caps"]) > 0)


# h) the real process-listing parse, on a recorded sample of the listing's text
LISTING = ("4\t\n812\t\"C:\\Windows\\system32\\svchost.exe\" -k netsvcs -p\n"
           "5120\tpython.exe scripts/th_pack_scan.py train-pk packed/pk\n"
           "5190\tpython.exe scripts/th_pack_scan.py train-pk2 packed/pk2\n"
           "6001\tpython tick.py upload th_pack_scan.py train-pk x\n"
           "7788\t\"C:\\Program Files\\Python310\\python.exe\" scripts/overlap_gate.py check-pack packed/other\n")


def real_scan(stdout, rc=0):
    ns = dict(subprocess=types.SimpleNamespace(run=lambda *a, **k: types.SimpleNamespace(returncode=rc, stdout=stdout, stderr="")))
    exec(SCAN_SRC, ns); return ns


def raises(fn):
    try: fn()
    except Exception: return True
    return False


def t_h():
    ns = real_scan(LISTING)
    chk("h) real lookup: pack with a live `th_pack_scan.py NAME ` process -> [pid]", ns["scan_pids"]("train-pk") == [5120])
    chk("h) real lookup: a name that is only a prefix of another pack's does not match", ns["scan_pids"]("train-pk2") == [5190] and ns["scan_pids"]("train") == [])
    chk("h) real lookup: another pack (no process) -> []", ns["scan_pids"]("train-other") == [])
    chk("h) real lookup: the tick's own command line (tick.py) is not a scan", 6001 not in ns["scan_pids"]("train-pk"))
    chk("h) an empty listing raises (lookup failed, not 'not running')", raises(lambda: real_scan("")["scan_pids"]("train-pk")))
    chk("h) a garbled listing (no pid column) raises", raises(lambda: real_scan("garbage line\nanother line\n")["scan_pids"]("train-pk")))
    chk("h) a failed listing command (rc != 0) raises", raises(lambda: real_scan(LISTING, rc=1)["scan_pids"]("train-pk")))
    rows = ns["scan_listing"]()
    chk("h) one listing, many packs: scan_pids reads the shared rows without running the listing again", ns["scan_pids"]("train-pk", rows) == [5120] and ns["scan_pids"]("train-other", rows) == [])


def t_i():
    pd = real_pss.push_decision
    exp = []
    for tries in (0, 1, 2, 3, 4):
        for st in ("error", "unknown"):
            exp.append(((st, False, tries), "rescan" if tries < 3 else "escalate"))
            exp.append(((st, True, tries), "rescan" if tries < 3 else "escalate"))
    got = [(k, pd(*k)) for k, _ in exp]
    chk("i) error/unknown x scan_tries 0..4 (was_pass either way): rescan below 3, escalate from 3", got == exp)
    chk("i) lookup failed -> wait for error and unknown at any tries", all(pd(st, wp, t, True) == "wait" for st in ("error", "unknown") for wp in (False, True) for t in (0, 3)))
    chk("i) clean -> push; running -> wait", pd("clean", False) == "push" and pd("clean", True, 3) == "push" and pd("running", False) == "wait" and pd("running", True, 9) == "wait")
    chk("i) refused_hits: skip never-PASS, escalate was-PASS", pd("refused_hits", False) == "skip" and pd("refused_hits", True) == "escalate")
    outs = {pd(s, w, t, l) for s in ("clean", "running", "refused_hits", "error", "unknown", "weird", "refused") for w in (False, True) for t in (0, 1, 3) for l in (False, True)}
    chk("i) the only values ever returned are the five (%s)" % sorted(outs), outs <= {"push", "wait", "skip", "escalate", "rescan"} and "push" in outs)
    chk("i) an unrecognised state never pushes", pd("weird", True) == "skip" and pd("refused", False) == "skip")


for f in (t_a, t_b, t_c, t_d, t_e, t_f, t_g, t_h, t_i): case(f)
print("ALL PASS" if ok else "FAILED (%d checks failed)" % nfail); sys.exit(0 if ok else 1)
