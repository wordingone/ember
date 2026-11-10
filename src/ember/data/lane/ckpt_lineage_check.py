# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""lead 81925: which local ember children are already on HF inside ember-corpus checkpoints/lineage-2119 (and restart-3b-old)? READ-ONLY.
Per child: hash the local manifest -> find the lineage step dir (INDEX.json manifest_sha256) -> every local file must exist there with equal size and
server-side metadata equal to the LOCAL sha256 (LFS sha256 from list_repo_tree; non-LFS small files: git blob sha1 == blob_id). Writes logs/ckpt-lineage-check.json.
Usage: python ckpt_lineage_check.py [names...]   (default: older + probes + H40-H43 + SLEEP; H38/H39 are in ember-raw-private already)"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, hashlib, time, concurrent.futures as cf
pass
from huggingface_hub import HfApi, hf_hub_download
import ckpt_children as C
R = "wordingone/ember-corpus"; api = HfApi()
def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)
_hc = {}
def sha256(p):
    st = os.stat(p); k = (st.st_ino, st.st_size, st.st_mtime_ns)
    if k not in _hc:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for c in iter(lambda: f.read(1 << 24), b""): h.update(c)
        _hc[k] = h.hexdigest()
    return _hc[k]
def gitsha1(p):
    h = hashlib.sha1(b"blob %d\0" % os.path.getsize(p))
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""): h.update(c)
    return h.hexdigest()
log("listing", R, "checkpoints/")
tree = {}
for t in api.list_repo_tree(R, repo_type="dataset", path_in_repo="checkpoints", recursive=True):
    if hasattr(t, "size"):
        l = getattr(t, "lfs", None); tree[t.path] = (t.size, (l.sha256 if hasattr(l, "sha256") else l["sha256"]) if l else None, getattr(t, "blob_id", None))
log("HF files", len(tree))
idx = json.load(open(hf_hub_download(R, "checkpoints/lineage-2119/INDEX.json", repo_type="dataset"), encoding="utf-8"))["checkpoints"]
by_manifest = {v["manifest_sha256"]: (k, v) for k, v in idx.items()}
names = sys.argv[1:] or [n for n in C.CH if n not in ("H38", "H39")] + [r["name"] for r in json.load(open((LANE_ROOT + "/logs/ckpt-probes.json")))]
reg = dict(C.CH)
for r in json.load(open((LANE_ROOT + "/logs/ckpt-probes.json"))): reg[r["name"]] = (r["id8"], r["dir"], None)
out = {}
def check(name):
    id8, d, _ = reg[name]
    files = [os.path.relpath(os.path.join(dp, f), d).replace("\\", "/") for dp, _, fn in os.walk(d) for f in fn]
    msha = sha256(d + "/checkpoint-manifest.json")
    ent = by_manifest.get(msha)
    row = dict(name=name, id8=id8, dir=d, manifest_sha=msha, files=len(files), bytes=sum(os.path.getsize(d + "/" + f) for f in files))
    if not ent: row.update(status="NOT_IN_LINEAGE", step_dir=None, matched=0, missing=len(files), bad=[]); return row
    sd, v = ent; row["step_dir"] = sd; ok = 0; miss = []; bad = []
    for rel in files:
        h = tree.get(f"{sd}/{rel}"); p = d + "/" + rel; sz = os.path.getsize(p)
        if h is None: miss.append(rel); continue
        if h[0] != sz: bad.append((rel, "size", sz, h[0])); continue
        if h[1] is not None:
            if sha256(p) != h[1]: bad.append((rel, "lfs sha256", h[1])); continue
        elif h[2] is not None:
            if gitsha1(p) != h[2]: bad.append((rel, "blob sha1")); continue
        else: bad.append((rel, "no server hash")); continue
        ok += 1
    row.update(matched=ok, missing=len(miss), missing_files=miss[:6], bad=bad[:6], status="COVERED" if ok == len(files) else ("PARTIAL" if ok else "NOT_COVERED"))
    return row
for n in names:
    r = check(n); out[n] = r
    log(n, r["id8"], r["status"], f"{r['matched']}/{r['files']} files", f"{r['bytes']/2**30:.2f} GiB", r.get("step_dir"), "missing", r["missing"], "bad", len(r["bad"]))
    json.dump(out, open((LANE_ROOT + "/logs/ckpt-lineage-check.json"), "w"), indent=1)
log("CHECK DONE covered", sum(1 for r in out.values() if r["status"] == "COVERED"), "of", len(out))
