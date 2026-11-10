# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import os, sys, json, time, tempfile, shutil
pass
import pack_gate as G
ok = True
def check(l, c):
    global ok; ok &= bool(c); print("PASS" if c else "FAIL", l)
T = tempfile.mkdtemp(dir=(LANE_ROOT + "/scratch")); P = T + "/packed"; S = T + "/orph"; LG = T + "/o.jsonl"; os.makedirs(P)
def mk(name, full, age_s, prov_ids=()):
    d = f"{P}/{name}"; os.makedirs(d + "/shards"); os.makedirs(d + "/objects"); open(d + "/docs-index.jsonl", "w").write("x")
    if full:
        for f in G.REQUIRED: open(f"{d}/{f}", "w").write("x")
    t = time.time() - age_s
    for dp, dn, fn in os.walk(d):
        for f in fn + dn: os.utime(os.path.join(dp, f), (t, t))
    os.utime(d, (t, t))
    open(f"{P}/{name}.prov.jsonl", "w").write("".join(json.dumps({"doc_id": i}) + "\n" for i in prov_ids))
try:
    mk("good", True, 9999); mk("young", False, 60); mk("running", False, 9999); mk("orph", False, 9999, ["a", "b"]); mk("big", True, 9999, ["a", "b", "c"])
    mk("announced", False, 9999); open(P + "/announced/intake.json", "w").write("{}"); check("RED announced pack (intake.json) with cleared artifacts is complete, never an orphan", "announced" in G.classify(P, cmds=[])["complete"])
    r = G.classify(P, cmds=[("python scripts/pack.py " + LANE_ROOT + "/packed running x.zst")])
    check("GREEN all artifacts = complete", "good" in r["complete"] and "big" in r["complete"])
    check("RED young incomplete dir is in progress, not orphan", "young" in r["inprogress"] and "young" not in r["orphan"])
    check("RED incomplete dir named by a live pack.py is in progress even when old", "running" in r["inprogress"])
    check("RED old incomplete dir with no live packer is an orphan", r["orphan"] == ["orph"])
    check("RED a non-packer process naming the dir does not protect it", "orph" in G.classify(P, cmds=["notepad orph"])["orphan"])
    mk("lanex-00000-00002", False, 9999)
    check("RED old incomplete dir whose text_lane.py <lane> is alive (waiting on disk floor) is in progress", "lanex-00000-00002" in G.classify(P, cmds=["python scripts/text_lane.py lanex"])["inprogress"])
    check("RED a different lane's text_lane.py does not protect it", "lanex-00000-00002" in G.classify(P, cmds=["python scripts/text_lane.py lane"])["orphan"])
    shutil.rmtree(P + "/lanex-00000-00002"); os.remove(P + "/lanex-00000-00002.prov.jsonl")
    r = G.sweep(P, S, LG, cmds=[])
    check("orphan moved, not deleted", set(r["moved"]) == {"orph", "running"} and "announced" not in r["moved"] and not os.path.exists(P + "/orph") and any(os.path.isdir(f"{S}/{x}/orph") for x in os.listdir(S)))
    row = [json.loads(l) for l in open(LG).read().splitlines() if json.loads(l)["pack"] == "orph"][0]; check("receipt names superseded_by when another prov covers every doc", row["superseded_by"] == "big" and "receipt.json" in row["missing"])
    check("complete packs untouched", os.path.isdir(P + "/good") and os.path.isdir(P + "/big"))
finally: shutil.rmtree(T, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
