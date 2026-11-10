# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, glob, json, hashlib, time
from huggingface_hub import HfApi
api = HfApi(); REPO = "wordingone/ember-train-private"; M = (LANE_ROOT + "/logs/manifests-20261108/pg-objects-manifest.jsonl")
rows = []; bad = []
for d in sorted(glob.glob((LANE_ROOT + "/packed/pg-*/"))):
    pack = os.path.basename(d.rstrip("/\\")); od = d + "objects"
    files = [os.path.join(dp, f) for dp, _, fs in os.walk(od) for f in fs]
    if not files: continue
    rem = {}
    for t in api.list_repo_tree(REPO, repo_type="dataset", path_in_repo=f"text/{pack}/objects", recursive=True):
        if hasattr(t, "size"): rem[t.path] = t
    for p in files:
        rel = os.path.relpath(p, d).replace(chr(92), "/"); hp = f"text/{pack}/{rel}"
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for c in iter(lambda: fh.read(8 << 20), b""): h.update(c)
        t = rem.get(hp); rs = t.lfs.sha256 if t is not None and getattr(t, "lfs", None) else None
        if os.stat(p).st_nlink != 1 or t is None or rs != h.hexdigest(): bad.append((p, os.stat(p).st_nlink, t is not None, rs == h.hexdigest())); continue
        rows.append(dict(path=p.replace(chr(92), "/"), size=os.path.getsize(p), sha256=h.hexdigest(), hf_repo=REPO, hf_path=hp, nlink=1, authority="lead 81864 (training 81861: shards/ stay)", ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
if bad: print("ABORT, unverified:", bad[:5], len(bad)); raise SystemExit(1)
open(M, "w").write("".join(json.dumps(r) + "\n" for r in rows)); assert os.path.getsize(M) > 0
print("MANIFEST", len(rows), "files", round(sum(r["size"] for r in rows) / 2**30, 2), "GiB")
for r in rows: os.remove(r["path"])
print("DELETED", len(rows))
