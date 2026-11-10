# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Pack completeness gate (lead 82278 class fix): a dir under packed/ is a COMPLETE pack only when all artifacts are present; otherwise it is IN-PROGRESS (a live pack.py / source_manifest.py names it, or its newest file is younger than GRACE_S) or an ORPHAN (a killed/failed pack: incomplete, no live packer, idle > GRACE_S).
Orphans are MOVED (never deleted) to scratch/orphan-packs/<name>-<ts>/ with their .prov.jsonl, one row appended to logs/orphan-packs.jsonl (incl. whether another pack's prov already covers every doc_id: 'superseded_by'). Called from the intake tick, so every tick line says what is complete / in progress / swept.
Complete = receipt.json + ledger.jsonl + source-manifest.jsonl + docs-index.jsonl.zst + shards/ + objects/ (text packs also get domain.json from the lane). The mail to training goes out only for packs with intake.json (written by the intake tick, itself gated on receipt + source-manifest with content_date_max + modality)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, time, shutil, glob
from lane_config import LANE_ROOT as ROOT; REQUIRED = ("receipt.json", "ledger.jsonl", "source-manifest.jsonl", "docs-index.jsonl.zst")
GRACE_S = 20 * 60; PACKERS = ("pack.py", "source_manifest.py", "pack_media.py", "pack_pg.sh", "pack_wiki_group.sh", "overlap_gate.py", "text_lane.py")
def missing(d):
    m = [f for f in REQUIRED if not os.path.exists(f"{d}/{f}")]
    m += [s + "/" for s in ("shards", "objects") if not os.path.isdir(f"{d}/{s}")]
    return m
def newest(d):
    t = os.path.getmtime(d)
    for dp, dn, fn in os.walk(d):
        for f in fn:
            try: t = max(t, os.path.getmtime(os.path.join(dp, f)))
            except OSError: pass
    return t
def live_cmds():
    import psutil
    out = []
    for p in psutil.process_iter(["cmdline"]):
        try: out.append(" ".join(p.info["cmdline"] or []).replace("\\", "/"))
        except Exception: pass
    return out
def classify(packed=ROOT + "/packed", now=None, cmds=None):
    now = now or time.time(); cmds = live_cmds() if cmds is None else cmds
    res = dict(complete=[], inprogress=[], orphan=[])
    for d in sorted(glob.glob(packed + "/*/")):
        d = d.rstrip("/\\"); name = os.path.basename(d)
        if not missing(d) or os.path.exists(d + "/intake.json"): res["complete"].append(name); continue      # intake.json = already announced to training; its docs-index/ledger may have been cleared after upload (pubmed-00000-00000), never an orphan
        lane = name.rsplit("-", 2)[0]      # 2026-11-10: text_lane.py <lane> alive but waiting on the disk floor before source_manifest.py is NOT an orphan (caselaw-00000-00002 swept in error)
        named = any(name in c and any(k in c for k in PACKERS) for c in cmds) or any(("text_lane.py " + lane) in c and not (("text_lane.py " + lane + "_") in c) for c in cmds)
        if named or now - newest(d) < GRACE_S: res["inprogress"].append(name)
        else: res["orphan"].append(name)
    return res
def prov_ids(path):
    try: return {json.loads(l)["doc_id"] for l in open(path, encoding="utf-8")}
    except Exception: return None
def sweep(packed=ROOT + "/packed", scratch=ROOT + "/scratch/orphan-packs", log=ROOT + "/logs/orphan-packs.jsonl", now=None, cmds=None):
    res = classify(packed, now, cmds); moved = []
    for name in res["orphan"]:
        mine = prov_ids(f"{packed}/{name}.prov.jsonl"); by = None
        if mine:
            for other in glob.glob(packed + "/*.prov.jsonl"):
                on = os.path.basename(other)[:-len(".prov.jsonl")]
                if on == name or on in res["orphan"]: continue
                o = prov_ids(other)
                if o and mine <= o: by = on; break
        dst = f"{scratch}/{name}-{time.strftime('%Y%m%dT%H%M%S')}"; os.makedirs(dst, exist_ok=True)
        row = dict(ts=time.strftime("%Y-%m-%dT%H:%M:%S"), pack=name, missing=missing(f"{packed}/{name}"), superseded_by=by, moved_to=dst, docs_in_prov=len(mine or ()))
        open(log, "a", encoding="utf-8").write(json.dumps(row) + "\n")      # receipt before the move
        shutil.move(f"{packed}/{name}", dst + "/" + name)
        if os.path.exists(f"{packed}/{name}.prov.jsonl"): shutil.move(f"{packed}/{name}.prov.jsonl", dst + "/")
        moved.append(name)
    res["moved"] = moved; return res
def summary(res):
    return f"packs: {len(res['complete'])} complete, in progress [{', '.join(res['inprogress']) or 'none'}]" + (f", ORPHANS moved to scratch/orphan-packs [{', '.join(res['moved'])}]" if res.get("moved") else "")
if __name__ == "__main__": print(summary(sweep()))
