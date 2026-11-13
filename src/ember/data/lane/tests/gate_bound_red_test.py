# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green for the gate-bound refusal (lead 83469; 2026-11-13 the C2 trained ledger h42-ledger-v1.jsonl was deleted as "regenerable" while every C1/C2 receipt bound it).
protected_set.bound_hit / verified_remove.protected_hit must refuse: the bound file, a directory holding it, a path inside a bound directory, a path in protected-set.json `bound_paths`; fail closed on an unreadable
receipt, an empty receipt dir and a receipt set with no `inputs`; allow an unrelated dir. A mutant (bound check off) proves the red discriminates. Tmp tree only (scratch); no real receipt is read or written.
Run: python scripts/tests/gate_bound_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT, M_ROOT, SEAT_TRAIN
import os, sys, json, shutil, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import protected_set as PS, verified_remove as V
ok = True


def check(label, cond):
    global ok
    ok &= bool(cond); print("PASS" if cond else "FAIL", label)


SCR = (LANE_ROOT + "/scratch"); os.makedirs(SCR, exist_ok=True)
T = tempfile.mkdtemp(dir=SCR, prefix="gb-test-").replace("\\", "/"); G = T + "/gate"; S = T + "/stage"; os.makedirs(G); os.makedirs(S + "/h-ratio-k3"); os.makedirs(S + "/other-dir"); os.makedirs(S + "/h-extra")
LED = S + "/h-ratio-k3/h-ledger-v1.jsonl"; open(LED, "w").write("x"); open(S + "/other-dir/f.bin", "w").write("y"); open(S + "/h-extra/z.bin", "w").write("z")
PSF = T + "/protected-set.json"
json.dump({"markers": [{"marker": "keep-this-hour-zz-20991231T000000Z/"}], "reserve_markers": []}, open(PSF, "w"))
PS.PATH = PSF; PS.GATE_DIR = G
rcp = lambda name, inputs: json.dump({"inputs": inputs, "verdict": "PASS"}, open(G + "/" + name, "w"))
rcp("c1c2-pack-a.json", {"trained": LED, "trained_sha256": "00", "candidate": T + "/packed/pack-a/ledger.jsonl", "trained_end": 5})
hit = lambda p: V.protected_hit(p)[0] is not None

check("the bound ledger file is refused", hit(LED))
check("the directory holding the bound ledger is refused", hit(S + "/h-ratio-k3"))
check("a directory that contains the bound dir (the staging root) is refused", hit(S))
check("the candidate pack dir (holds the bound candidate ledger) and the ledger itself are refused", hit(T + "/packed/pack-a") and hit(T + "/packed/pack-a/ledger.jsonl"))
check("backslash form of the bound dir is refused", hit(S.replace("/", "\\") + "\\h-ratio-k3"))
check("an unrelated sibling dir is allowed", not hit(S + "/other-dir") and not hit(S + "/other-dir/f.bin"))
check("verified_remove._pre refuses the bound ledger (no removal path reaches os.remove)", V._pre(LED, [S], 1)[0] is None)
check("verified_remove._pre allows the unrelated file", V._pre(S + "/other-dir/f.bin", [S], 1)[0] is not None)
# the training seat's own protect list in protected-set.json
json.dump({"markers": [{"marker": "keep-this-hour-zz-20991231T000000Z/"}], "reserve_markers": [], "bound_paths": [S + "/h-extra"]}, open(PSF, "w"))
check("protected-set.json bound_paths refuses its dir and what is inside", hit(S + "/h-extra") and hit(S + "/h-extra/z.bin"))
json.dump({"markers": [{"marker": "keep-this-hour-zz-20991231T000000Z/"}], "reserve_markers": [], "bound_paths": ["relative/path"]}, open(PSF, "w"))
check("a bad bound_paths entry fails closed (everything refused)", hit(S + "/other-dir"))
json.dump({"markers": [{"marker": "keep-this-hour-zz-20991231T000000Z/"}], "reserve_markers": []}, open(PSF, "w"))
# a new receipt binds a new path: seen at once (cache keyed by mtime/size of every receipt)
rcp("c1c2-pack-b.json", {"trained": S + "/other-dir/f.bin"})
check("a newly written receipt binds its path at once", hit(S + "/other-dir/f.bin"))
os.remove(G + "/c1c2-pack-b.json")
check("and the binding ends with the receipt (cache re-keyed)", not hit(S + "/other-dir/f.bin"))
# fail closed
open(G + "/c1c2-bad.json", "w").write("{not json")
check("an unreadable receipt refuses everything (fail closed)", hit(S + "/other-dir") and "unreadable" in V.protected_hit(S + "/other-dir")[1])
os.remove(G + "/c1c2-bad.json")
rcp("c1c2-noinputs.json", {}); doc = json.load(open(G + "/c1c2-noinputs.json")); doc.pop("inputs"); json.dump(doc, open(G + "/c1c2-noinputs.json", "w"))
os.remove(G + "/c1c2-pack-a.json")
check("no receipt with an `inputs` object refuses everything (cannot know what is bound)", hit(S + "/other-dir"))
os.remove(G + "/c1c2-noinputs.json")
check("an empty receipt dir refuses everything", hit(S + "/other-dir"))
# mutant: bound check off -> the deleter would take the ledger dir (proves the red catches it)
rcp("c1c2-pack-a.json", {"trained": LED})
orig = PS.bound_hit; PS.bound_hit = lambda *a, **k: (None, "")
check("MUTANT (bound check off) lets the ledger dir through, so the red above is real", not hit(S + "/h-ratio-k3"))
PS.bound_hit = orig
check("restored: refused again", hit(S + "/h-ratio-k3"))
# real receipts: the live set parses (read only)
PS.GATE_DIR = (M_ROOT + "/avir/" + SEAT_TRAIN + "/state"); PS.PATH = (LANE_ROOT + "/loops/protected-set.json")
try:
    b = PS.bound_paths(); check("real gate receipts parse (%d receipts, %d bound paths)" % (b["receipts"], len(b["paths"])), b["receipts"] > 0 and len(b["paths"]) > 0)
except Exception as e:
    check("real gate receipts parse: " + repr(e), False)
shutil.rmtree(T, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
