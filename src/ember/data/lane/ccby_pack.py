# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Image lane (queue item 7): stream-through pack of commoncatalog-cc-by from <raw-repo> image/commoncatalog-cc-by (our verified raw copy).
Per parquet: download -> ccby_manifest (licence/human-text/heldout/dedup; no date wall) -> delete parquet. Then pack_media image over the merged manifest -> packed to A:/ember-stage/media-packed (or B: media-packed) -> delete staged images.
Resumable: staging/ccby-pack/state.json. Done marker: staging/ccby-pack/ALL.done. Usage: python scripts/ccby_pack.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_RAW_REPO, LANE_ROOT
import os, sys, json, time, subprocess, shutil
from huggingface_hub import HfApi
import net_cap as _nc      # M-NET-2 (lead 82238): every lane download goes through the shared, cap-aware downloader (unthrottled while the cap is off)
def hf_hub_download(repo, path, repo_type="dataset", revision=None, local_dir=".", **kw): return _nc.download(repo, path, rev=revision, local_dir=local_dir, repo_type=repo_type)
from lane_config import LANE_ROOT as ROOT; W = ROOT + "/staging/ccby-pack"; R = ("wordingone/" + HF_RAW_REPO); NAME = "commoncatalog-cc-by-v1"
os.makedirs(W + "/parts", exist_ok=True); ST = W + "/state.json"
state = json.load(open(ST)) if os.path.exists(ST) else {"done": {}}
def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)
pass; import reserve_plan
def wait_space(gib):
    while shutil.disk_usage("B:/").free / 2**30 - gib < reserve_plan.floor_gib() + 1: log("waiting for space (reserve planner)", reserve_plan.describe()); time.sleep(120)
api = HfApi(); files = sorted((t.path, t.size) for t in api.list_repo_tree(R, repo_type="dataset", path_in_repo="image/commoncatalog-cc-by", recursive=True) if hasattr(t, "size") and t.path.endswith(".parquet"))
log(len(files), "parquet files", round(sum(s for _, s in files) / 2**30, 1), "GiB")
for i, (p, s) in enumerate(files):
    if p in state["done"]: continue
    wait_space(3 * s / 2**30 + 8); dl = W + f"/dl{i}"; lp = hf_hub_download(R, p, repo_type="dataset", local_dir=dl)
    out = W + f"/parts/{i:03d}"
    r = subprocess.run([sys.executable, ROOT + "/scripts/ccby_manifest.py", lp, "--out", out], capture_output=True, text=True)
    if r.returncode: log("MANIFEST FAILED", p, r.stderr[-300:]); sys.exit(2)
    shutil.rmtree(dl, ignore_errors=True); state["done"][p] = r.stdout.strip()[-200:]; json.dump(state, open(ST, "w")); log("prepared", i, state["done"][p])
man = W + "/manifest.jsonl"
with open(man, "w", encoding="utf-8") as mo:
    for i in range(len(files)):
        pm = W + f"/parts/{i:03d}/manifest.jsonl"
        if os.path.exists(pm): mo.write(open(pm, encoding="utf-8").read())
cdm = ""      # pack-level content_date_max = latest per-row content_date_max (metadata only; no date wall since 2026-11-11, lead 83389)
for l in open(man, encoding="utf-8"):
    cdm = max(cdm, (json.loads(l).get("content_date_max") or ""))
meta = W + "/meta.json"; json.dump({"dataset_id": "media:" + NAME, "content_date_max": cdm or "undated"}, open(meta, "w"))
outd = "A:/ember-stage/media-packed" if shutil.disk_usage("A:/").free > 30 * 2**30 else ROOT + "/media-packed"
r = subprocess.run([sys.executable, ROOT + "/scripts/pack_media.py", "image", outd, NAME, man, meta], capture_output=True, text=True, env=dict(os.environ, PACK_MEDIA_SPEC="v2")); log(r.stdout[-400:], r.stderr[-300:])
if r.returncode: sys.exit(3)
shutil.rmtree(W + "/parts", ignore_errors=True)       # staged images are now inside the packed shards
open(W + "/ALL.done", "w").write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())); log("DONE", outd + "/" + NAME)
