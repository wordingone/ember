# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Reds for probe_terminal_guard.py (lead ruling 82451). Run: python scripts/tests/probe_terminal_guard_red_test.py [--live]
All cases build a synthetic receipts tree under a temp dir and pass it in; nothing under <m-root>/ember-live-receipts is touched. --live prints the
eligibility of today's real probe dirs (read-only, informational: it asserts nothing because the answer moves as hours end)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import M_ROOT
import glob
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import probe_terminal_guard as PG  # noqa: E402
import evict_ckpt_list as E  # noqa: E402

ok = True
BIG = 1 << 20


def check(label, cond):
    global ok
    ok &= bool(cond)
    print("PASS" if cond else "FAIL", label)


def build(root, stamp, mid, size=BIG, hour=None, hour_terminal=False, age_s=0):
    """One probe dir (a trained-child with one 1 MiB object and an optimizer file) and, optionally, the hour that names it."""
    base = f"{root}/receipts/cia-probe-a1-five-attn-stage-d4-{stamp}/measurement-{mid}/trained-child"
    os.makedirs(base + "/objects")
    for rel in ("objects/a.pt", "optimizer-state.pt"):
        with open(f"{base}/{rel}", "wb") as f:
            f.write(b"x" * size)
    if age_s:
        t = time.time() - age_s
        for rel in ("objects/a.pt", "optimizer-state.pt"):
            os.utime(f"{base}/{rel}", (t, t))
    if hour:
        hd = f"{root}/receipts/cia-hour-a1-five-attn-stage-d4-{hour}"
        os.makedirs(hd + "/measurement-" + "0" * 32, exist_ok=True)
        with open(hd + "/prediction.json", "w") as f:
            json.dump(dict(identity=dict(checkpoint_probe=dict(custody_root=f"{M_ROOT}/ember-live-receipts/x/measurement-{mid}"))), f)
        if hour_terminal:
            with open(hd + "/measurement-" + "0" * 32 + "/hour-result.json", "w") as f:
                f.write("{}")
    return base


def verdict(root, child, kept=None, window=False):
    marker = root + "/gpu-window-open"
    if window:
        open(marker, "w").write("x")
    return PG.probe_eligibility(child, kept=kept, receipts=root + "/receipts", in_root=root + "/in", window=marker)


M1, M2, M3, M4, M5, M6 = (c * 32 for c in "123456")

with tempfile.TemporaryDirectory() as r:
    c = build(r, "20261110T034921Z", M1, hour="20261110T034921Z")
    v = verdict(r, c)
    check("RED a probe whose hour has a prediction but no terminal receipt is refused PENDING_CONSUMER (the running H49 shape)", not v["ok"] and v["reason"] == "PENDING_CONSUMER")

with tempfile.TemporaryDirectory() as r:
    c = build(r, "20261109T193128Z", M2, hour="20261109T193128Z", hour_terminal=True, age_s=5 * 3600)
    v = verdict(r, c)
    check("GREEN a probe whose consumer hour has hour-result.json passes clause A and names the receipt", v["ok"] and v["clause"].startswith("A") and v["terminal_receipt"] and v["terminal_receipt"][0].endswith("hour-result.json"))

with tempfile.TemporaryDirectory() as r:
    old = build(r, "20261109T100107Z", M3, hour="20261109T100107Z", hour_terminal=True, age_s=9 * 3600)
    new = build(r, "20261110T034921Z", M4, age_s=5 * 3600)
    check("RED the newest probe dir while a window is open is refused WINDOW_NEWEST", (lambda v: not v["ok"] and v["reason"] == "WINDOW_NEWEST")(verdict(r, new, window=True)))
    check("GREEN an older probe with a terminal consumer still passes while a window is open", verdict(r, old)["ok"])
    check("GREEN the newest probe passes once no window is open and it is idle (clause B)", (lambda v: v["ok"] and v["clause"].startswith("B"))(PG.probe_eligibility(new, receipts=r + "/receipts", in_root=r + "/in", window=r + "/no-such-marker")))

with tempfile.TemporaryDirectory() as r:
    c = build(r, "20261109T233136Z", M5, age_s=8 * 3600)
    v = verdict(r, c, kept=lambda p: "cia-probe" in p)
    check("RED a KEEP-marked probe is refused KEEP before any other clause", not v["ok"] and v["reason"] == "KEEP")
    v = verdict(r, c)
    check("GREEN an orphan probe (no hour names it) idle 8 h passes clause B (the 233136Z shape)", v["ok"] and v["clause"].startswith("B"))

with tempfile.TemporaryDirectory() as r:
    c = build(r, "20261109T233136Z", M5, age_s=60)
    v = verdict(r, c)
    check("RED a fresh orphan probe (idle < 2 h: the b-floor wait between probe and hour prep) is refused FRESH_ORPHAN", not v["ok"] and v["reason"] == "FRESH_ORPHAN")

with tempfile.TemporaryDirectory() as r:
    c = build(r, "20261109T172522Z", M6, hour="20261109T172522Z", hour_terminal=True, age_s=5 * 3600)
    outside = r + "/receipts/catalog-train-cache"
    os.makedirs(outside)
    os.link(c + "/objects/a.pt", outside + "/same-bytes.pt")
    v = verdict(r, c)
    check("RED a probe whose bytes are hard-linked from outside the child is refused LINKED_OUTSIDE (never freed by name)", not v["ok"] and v["reason"].startswith("LINKED_OUTSIDE"))

with tempfile.TemporaryDirectory() as r:
    c = build(r, "20261109T142405Z", M6, hour="20261109T142405Z", hour_terminal=True, age_s=5 * 3600)
    os.makedirs(r + "/in/x")
    with open(r + "/in/x/checkpoint-probe-reference.json", "w") as f:
        f.write(json.dumps(dict(custody_root=(M_ROOT + "/ember-live-receipts/x/measurement-") + M6)))
    v = verdict(r, c)
    check("GREEN a stale checkpoint-probe-reference.json naming the probe does not block a terminal consumer, and is listed for the manifest", v["ok"] and any(k == "ref" for k, _ in v["consumers"]))

with tempfile.TemporaryDirectory() as r:
    c = build(r, "20261109T142405Z", M6, hour="20261109T142405Z", hour_terminal=True, age_s=5 * 3600)
    hour_child = r + "/receipts/cia-hour-a1-five-attn-stage-d4-20261109T142405Z/measurement-" + "0" * 32 + "/trained-child"
    os.makedirs(hour_child)
    check("RED an hour's own trained-child is not in this class (NOT_A_PROBE)", PG.probe_eligibility(hour_child, receipts=r + "/receipts")["reason"] == "NOT_A_PROBE")

src = open(os.path.join(os.path.dirname(HERE), "probe_terminal_guard.py"), encoding="utf-8").read()
check("the guard never removes or writes a file", not any(t in src for t in ("os." + "remove", "unlink", "rmtree", "open(p, \"w", "os.rename")))
ld = open(os.path.join(os.path.dirname(HERE), "ckpt_lineage_delete.py"), encoding="utf-8").read()
check("branch (c) of ckpt_lineage_delete.py asks the guard before it selects a probe", "probe_eligibility(r[\"dir\"], kept=_EK.kept)" in ld and ld.index("probe_eligibility") < ld.index("hf_repo=None, prefix=None, via=\"probe child"))
check("the manifest row carries consumer, terminal receipt and clause", all(k in ld for k in ("probe_consumers", "probe_terminal", "probe_clause")))

if "--live" in sys.argv:
    print("\nLIVE (read-only, informational):")
    for d in sorted(glob.glob((M_ROOT + "/ember-live-receipts/cia-probe-*/measurement-*/trained-child")) + glob.glob((M_ROOT + "/ember-live-receipts/cia-probe-*/measurement-*/.checkpoint-quarantine/candidate-trained-child-*"))):
        v = PG.probe_eligibility(d, kept=E.kept)
        print(("ELIGIBLE " if v["ok"] else "REFUSED  ") + d.replace("\\", "/").split("ember-live-receipts/")[1].split("/measurement-")[0], v["clause"] or v["reason"])

print("ALL PASS" if ok else "FAILED")
sys.exit(0 if ok else 1)
