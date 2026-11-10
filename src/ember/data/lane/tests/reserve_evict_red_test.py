# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT, M_ROOT
import sys, os, tempfile, hashlib
pass
import reserve_evict as R
ok = True
def check(l, c):
    global ok; ok &= bool(c); print("PASS" if c else "FAIL", l)
L = (M_ROOT + "/ember-live-receipts/")
check("RED H49 hour refused", R.refuse_reason(L + "cia-hour-a1-five-attn-stage-d4-20261109T233136Z/measurement-x/trained-child/objects/a.pt") == "under a KEEP path")
check("RED H48 trained-child 9457a769 refused", R.refuse_reason(L + "cia-hour-a1-five-attn-stage-d4-20261109T193128Z/measurement-9457a769f1b543c0949d4296d850d2b6/trained-child/objects/a.pt") == "under a KEEP path")
check("GREEN H47 hour is no longer a KEEP path (lead 82318/training 82321)", R.refuse_reason(L + "cia-hour-a1-five-attn-stage-d4-20261109T172522Z/measurement-x/trained-child/objects/a.pt") is None)
check("RED H49 probe refused", R.refuse_reason(L + "cia-probe-a1-five-attn-stage-d4-20261109T233136Z/m/trained-child/optimizer-state.pt") == "under a KEEP path")
check("RED H46 head trained-child refused", R.refuse_reason(L + "cia-hour-a1-five-attn-stage-d4-20261109T142405Z/measurement-0043505768944816b459f4cedbd1996e/trained-child/objects/a.pt") == "under a KEEP path")
check("RED H45 child refused", R.refuse_reason(L + "cia-hour-a1-five-attn-stage-d4-20261109T100107Z/measurement-e62e/trained-child/objects/a.pt") == "under a KEEP path")
check("RED H44 child e73486d2 objects refused (lead 82363)", R.refuse_reason(L + "cia-hour-a1-five-attn-stage-d4-20261109T072659Z/measurement-99364f2a0e624c98981335f3ef65bbc0/trained-child/objects/a.pt") == "under a KEEP path")
check("RED H44 child optimizer-state refused (lead 82363)", R.refuse_reason(L + "cia-probe-a1-five-attn-stage-d4-20261109T072659Z/m/trained-child/optimizer-state.pt") == "under a KEEP path")
check("RED H41 child cb516ed9 objects + optimizer refused (lead 82363)", R.refuse_reason(L + "cia-hour-a1-five-attn-stage-d4-20261107T165532Z/measurement-8fe5f0ef58e34d68831174450d3f50d7/trained-child/objects/a.pt") == "under a KEEP path" and R.refuse_reason(L + "cia-probe-a1-five-attn-stage-d4-20261107T165532Z/m/trained-child/optimizer-state.pt") == "under a KEEP path")
check("RED catalog-train-cache refused", R.refuse_reason((M_ROOT + "/ember-data/catalog-train-cache/2c557e7f/2720f6d1/x.pt")) == ("outside " + M_ROOT + "/ember-live-receipts"))
check("RED selected head json refused", R.refuse_reason(L + "selected-continuation-head.json") == "under a KEEP path")
check("GREEN old ancestor object allowed", R.refuse_reason(L + "cia-hour-a1-five-attn-stage-d4-20260927T080708Z/measurement-d6/trained-child/objects/a.pt") is None)
d = tempfile.mkdtemp(dir=(LANE_ROOT + "/scratch")); m = d + "/m.tsv"; open(m, "w").write("status\tgib\tsha256\thf\tpath\nCANDIDATE\t1\tab\tr:p\tB:/x.pt\nPROTECTED\t1\tcd\t\tB:/y.pt\n")
try: R.load(m, "0" * 64); check("RED wrong manifest sha refused", False)
except R.Refused: check("RED wrong manifest sha refused", True)
check("GREEN pinned manifest loads only CANDIDATE rows", [r["path"] for r in R.load(m, hashlib.sha256(open(m, "rb").read()).hexdigest())] == ["B:/x.pt"])
sys.argv = ["x", m]
try: R.main(); check("RED missing --ack refused", False)
except R.Refused: check("RED missing --ack refused", True)
src = open((LANE_ROOT + "/scripts/reserve_evict.py"), encoding="utf-8").read()
check("receipt is written before os.remove", src.index("open(RC") < src.index("os.remove(p)"))
import shutil; shutil.rmtree(d, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
