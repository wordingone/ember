# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Free space on B: (lead 81345). Verified-duplicate / verified-on-HF / regenerable-garbage deletes only. Receipt: audit/free-b-receipt-<ts>.json. python os.remove only."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, M_ROOT
import os, sys, json, hashlib, time, shutil
BS = chr(92); R = dict(ts=time.strftime("%Y-%m-%dT%H:%M:%S"), deleted=[], skipped=[], free_before_gib=shutil.disk_usage("B:/").free / 2**30)
def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 24), b""): h.update(b)
    return h.hexdigest()
def files(p): return {os.path.relpath(os.path.join(dp, f), p).replace(BS, "/"): os.path.join(dp, f) for dp, _, fs in os.walk(p) for f in fs}
def rm(path, why, size=None):
    s = os.path.getsize(path); os.remove(path); R["deleted"].append(dict(path=path.replace(BS, "/"), bytes=s, why=why))
# 1) <m-root>/shards-v0 vs <m-root>/ember-data/shards-v0 (per-file sha256)
a = files((M_ROOT + "/shards-v0")); b = files((M_ROOT + "/ember-data/shards-v0")); ok = set(a) <= set(b)
if ok:
    for k, p in sorted(a.items()):
        if os.path.getsize(p) != os.path.getsize(b[k]) or sha(p) != sha(b[k]): ok = False; R["skipped"].append(f"shards-v0 mismatch {k}"); break
if ok:
    for k, p in sorted(a.items()): rm(p, ("sha256-identical duplicate of " + M_ROOT + "/ember-data/shards-v0/") + k)
    for dp, ds, fs in os.walk((M_ROOT + "/shards-v0"), topdown=False):
        try: os.rmdir(dp)
        except OSError: pass
else: R["skipped"].append("shards-v0 not fully verified; untouched")
# 2) upload/raw + upload/train: files verified on HF (LFS sha256 or size) -> delete verified local copies
from huggingface_hub import HfApi
api = HfApi()
for sub, repo in (("raw", "wordingone/ember-raw-private"), ("train", "wordingone/ember-train-private")):
    root = (LANE_ROOT + "/upload/") + sub
    if not os.path.isdir(root): continue
    tree = {t.path: t for t in api.list_repo_tree(repo, repo_type="dataset", recursive=True) if hasattr(t, "size")}
    for dp, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(dp, f); rel = os.path.relpath(p, root).replace(BS, "/")
            cands = [t for k, t in tree.items() if k.endswith("/" + rel) or k == rel]
            good = False
            for t in cands:
                if getattr(t, "lfs", None): good = (t.lfs.sha256 == sha(p))
                else: good = (t.size == os.path.getsize(p))
                if good: break
            if good: rm(p, f"sha-verified on HF {repo}")
            else: R["skipped"].append(f"upload/{sub}/{rel}: not matched on HF")
# 3) wiki partial downloads (.bad*) = failed partials, never used
for f in os.listdir((LANE_ROOT + "/wikipedia-20220501/parts")):
    if ".bad" in f: rm((LANE_ROOT + "/wikipedia-20220501/parts/") + f, "failed partial download (sha1 mismatch), superseded")
# 4) TextCaps source zip (images for TextCaps train already extracted: 21,953/21,953; zip re-downloadable)
z = (LANE_ROOT + "/textcaps/train_val_images.zip")
n = len(files((LANE_ROOT + "/textcaps/images/train"))) if os.path.isdir((LANE_ROOT + "/textcaps/images/train")) else 0
if os.path.exists(z) and n >= 21953: rm(z, f"re-downloadable public source zip; {n} train images already extracted")
R["free_after_gib"] = shutil.disk_usage("B:/").free / 2**30; R["freed_gib"] = round(sum(d["bytes"] for d in R["deleted"]) / 2**30, 2)
os.makedirs((LANE_ROOT + "/audit"), exist_ok=True)
json.dump(R, open(f"{LANE_ROOT}/audit/free-b-receipt-{time.strftime('%Y%m%d-%H%M%S')}.json", "w"), indent=1)
print(json.dumps(dict(freed_gib=R["freed_gib"], free_before=round(R["free_before_gib"], 1), free_after=round(R["free_after_gib"], 1), deleted=len(R["deleted"]), skipped=R["skipped"][:8]), indent=1))
