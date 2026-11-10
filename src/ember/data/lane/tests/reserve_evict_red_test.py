# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red test for reserve_evict + the declared protected set (issue 2450). The protected paths come FROM loops/protected-set.json, so a re-declaration can never leave this test stale.
Run: python scripts/tests/reserve_evict_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT, M_ROOT
import sys, os, json, tempfile, hashlib, shutil
pass
import protected_set as PS
import evict_ckpt_list as EK
import reserve_evict as R
ok = True
def check(l, c):
    global ok; ok &= bool(c); print("PASS" if c else "FAIL", l)
L = (M_ROOT + "/ember-live-receipts/")
D = PS.load()
def path_under(marker):
    return L + marker.rstrip("/") + "/m/trained-child/objects/a.pt" if marker.endswith("/") else L + marker

# 1. every declared marker (shared + reserve) is refused, whatever the hour: the test follows the file
check("declared set is non-empty (shared %d, reserve %d)" % (len(D["markers"]), len(D["reserve_markers"])), len(D["markers"]) > 0 and len(D["reserve_markers"]) > 0)
for m in D["markers"] + D["reserve_markers"]:
    check("RED declared marker refused: " + m[-48:], R.refuse_reason(path_under(m)) == "under a KEEP path")
for m in D["markers"]:
    check("RED shared marker also refused by evict_ckpt_list: " + m[-48:], EK.kept(path_under(m)) == m and EK.refuse_reason(path_under(m)) is not None)
check("RED a probe optimizer-state under a declared hour dir is refused", R.refuse_reason(L + D["markers"][-1].rstrip("/") + "/m/trained-child/optimizer-state.pt") == "under a KEEP path")
check("RED catalog-train-cache refused", R.refuse_reason((M_ROOT + "/ember-data/catalog-train-cache/2c557e7f/2720f6d1/x.pt")) == ("outside " + M_ROOT + "/ember-live-receipts"))
check("RED selected head json refused", R.refuse_reason(L + "selected-continuation-head.json") == "under a KEEP path")
check("GREEN old ancestor object allowed", R.refuse_reason(L + "cia-hour-a1-five-attn-stage-d4-20260927T080708Z/measurement-d6/trained-child/objects/a.pt") is None)

# 2. the declaration is the ONLY source: a marker added to the file protects at once with no code edit; the keep-list is not a literal in either deleter
d = tempfile.mkdtemp(dir=(LANE_ROOT + "/scratch")); decl = d + "/protected-set.json"
doc = json.load(open(PS.PATH, encoding="utf-8")); doc["reserve_markers"].append({"marker": "cia-hour-zz-new-hour-20991231T000000Z/"})
json.dump(doc, open(decl, "w")); old = PS.PATH; PS.PATH = decl
try:
    check("RED a newly declared marker is refused with no code change", R.refuse_reason(L + "cia-hour-zz-new-hour-20991231T000000Z/m/trained-child/objects/a.pt") == "under a KEEP path")
    check("GREEN the same path was not protected before the declaration", (PS.PATH == decl) and (R.refuse_reason(L + "cia-hour-zz-new-hour-20991231T000000Z/m/trained-child/objects/a.pt") is not None))
    PS.PATH = old
    check("GREEN back on the live declaration the new hour is not protected", R.refuse_reason(L + "cia-hour-zz-new-hour-20991231T000000Z/m/trained-child/objects/a.pt") is None)
    # 3. fail closed: missing / empty / malformed / too-broad declaration -> ProtectedSetError (the deleter removes nothing)
    def raises(content):
        pth = d + "/bad.json"
        if content is None:
            if os.path.exists(pth): os.remove(pth)
        else: open(pth, "w").write(content)
        PS.PATH = pth
        try: R.refuse_reason(L + "cia-hour-x/m/trained-child/objects/a.pt"); return False
        except PS.ProtectedSetError: return True
        finally: PS.PATH = old
    check("RED missing declaration -> fail closed", raises(None))
    check("RED empty marker list -> fail closed", raises('{"markers": []}'))
    check("RED malformed JSON -> fail closed", raises("{not json"))
    check("RED too-broad marker '/' -> fail closed", raises('{"markers": [{"marker": "/"}]}'))
    check("RED non-object JSON -> fail closed", raises("[1,2]"))
finally:
    PS.PATH = old
src = open((LANE_ROOT + "/scripts/reserve_evict.py"), encoding="utf-8").read(); src_ek = open((LANE_ROOT + "/scripts/evict_ckpt_list.py"), encoding="utf-8").read()
check("no hour literal in reserve_evict.py code", "cia-hour-a1" not in src.split('"""', 2)[2] and "cia-probe-a1" not in src.split('"""', 2)[2])
check("no hour literal in evict_ckpt_list.py code", "cia-hour-a1" not in src_ek.split('"""', 2)[2])

# 4. manifest and acknowledgement gates
m = d + "/m.tsv"; open(m, "w").write("status\tgib\tsha256\thf\tpath\nCANDIDATE\t1\tab\tr:p\tB:/x.pt\nPROTECTED\t1\tcd\t\tB:/y.pt\n")
try: R.load(m, "0" * 64); check("RED wrong manifest sha refused", False)
except R.Refused: check("RED wrong manifest sha refused", True)
check("GREEN pinned manifest loads only CANDIDATE rows", [r["path"] for r in R.load(m, hashlib.sha256(open(m, "rb").read()).hexdigest())] == ["B:/x.pt"])
sys.argv = ["x", m]
try: R.main(); check("RED missing --ack refused", False)
except R.Refused: check("RED missing --ack refused", True)

# 5. receipts: written before os.remove; carry the protected-set sha; one run row holds the reserve declaration and the free space after each eviction
check("receipt is written before os.remove", src.index("open(RC") < src.index("os.remove(p)"))
check("per-file receipt row records protected_set_sha256", 'protected_set_sha256=PSD["sha256"]' in src)
check("free space is measured after EACH eviction", 'free_after_bytes=shutil.disk_usage("B:/").free))' in src and src.index("os.remove(p)") < src.index("free_after_bytes=shutil.disk_usage"))
check("one run receipt holds the reserve declaration, protected set, free before/after", all(k in src for k in ("reserve_declaration=rdecl", "protected_set=dict(", "free_before_bytes=free0", "free_after_each=st[")))
rd = R.reserve_decl(d + "/nope.json"); check("missing reserve declaration is recorded as missing, not invented", rd.get("missing") is True)
open(d + "/res.json", "w").write('{"chain_start_floor_gib": 305}'); rd = R.reserve_decl(d + "/res.json")
check("reserve declaration is recorded with its sha256", rd["declaration"]["chain_start_floor_gib"] == 305 and rd["sha256"] == hashlib.sha256(open(d + "/res.json", "rb").read()).hexdigest())
shutil.rmtree(d, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
