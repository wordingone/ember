# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Hash-match of the 4 traced objects (lead 81821) against data's local raw/packed/receipt hashes. 1 core, BelowNormal CPU, VeryLow IO. Output: logs/hashmatch-4obj.json"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, hashlib, time, glob, psutil
p = psutil.Process(); p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
try: p.ionice(psutil.IOPRIO_VERYLOW)
except Exception as e: print("ionice", e)
try: p.cpu_affinity([16])
except Exception: pass
BL = {"0d544e19": "A:/ember-staging/h19-percatalog-files6-10-v2-20261004T190306Z/file6-projected-text-v1.blob",
      "1983e863": "A:/ember-staging/h19-percatalog-20261004/file3-projected-text-v1.blob",
      "a6ac037d": "A:/ember-staging/h19-percatalog-20261004/file4-projected-text-v1.blob",
      "3bc93f29": "A:/ember-staging/h19-percatalog-20261004/file5-projected-text-v1.blob"}
out = {"method": "sha256 of each on-disk blob (whole file, 8 MiB reads); match = sha256 equal AND size equal against every file data holds a sha256 for; size-only prefilter for unhashed files", "objects": {}}
for k, path in BL.items():
    h = hashlib.sha256(); n = 0; t = time.time()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(8 << 20), b""): h.update(c); n += len(c)
    out["objects"][k] = dict(blob=path, size=n, sha256=h.hexdigest(), prefix_ok=h.hexdigest().startswith(k), secs=round(time.time() - t))
    print(k, n, h.hexdigest(), flush=True)
sh = {o["sha256"]: k for k, o in out["objects"].items()}; sz = {}
for k, o in out["objects"].items(): sz.setdefault(o["size"], []).append(k)
hits = {k: [] for k in BL}; size_only = {k: [] for k in BL}; scanned = collections = 0; sources = {}
def chk(src, path, size, sha):
    sources[src] = sources.get(src, 0) + 1
    if sha and sha in sh: hits[sh[sha]].append(dict(source=src, path=path, size=size, sha256=sha))
    elif size in sz and not sha:
        for k in sz[size]: size_only[k].append(dict(source=src, path=path, size=size))
for l in open((LANE_ROOT + "/census/files.jsonl"), encoding="utf-8", errors="ignore"):
    try: r = json.loads(l)
    except Exception: continue
    chk("census/files.jsonl", r.get("p"), r.get("s"), r.get("sha"))
for f in glob.glob((LANE_ROOT + "/**/*receipts*.jsonl"), recursive=True) + glob.glob((LANE_ROOT + "/logs/*receipts.jsonl")) + glob.glob((LANE_ROOT + "/packed/*/ledger.jsonl")) + glob.glob((LANE_ROOT + "/packed/*/source-manifest.jsonl")) + glob.glob((LANE_ROOT + "/media-packed/*/*.jsonl")):
    if os.path.getsize(f) > 3e9: continue
    for l in open(f, encoding="utf-8", errors="ignore"):
        for k, o in out["objects"].items():
            if o["sha256"] in l: hits[k].append(dict(source=f, line=l[:200]))
    sources[f] = 1
out["hits"] = hits; out["size_only_candidates"] = {k: v[:20] for k, v in size_only.items()}; out["sources_scanned"] = {"census_rows": sources.get("census/files.jsonl", 0), "jsonl_files": len(sources) - 1}
out["verdict"] = {k: ("MATCH" if hits[k] else "NO MATCH") for k in BL}
json.dump(out, open((LANE_ROOT + "/logs/hashmatch-4obj.json"), "w"), indent=1); print(json.dumps(out["verdict"]), json.dumps(out["sources_scanned"]), {k: len(v) for k, v in size_only.items()}, flush=True)
