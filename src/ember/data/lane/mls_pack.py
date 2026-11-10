# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Audio lane (queue item 8a): stream-through pack of MLS-English TRAIN into audio spec v1 shards, G parquet files per pack (default 4).
Per group: download -> mls_manifest (train-only, heldout, dedup) -> pack_media audio -> delete parquet+decoded audio -> pack dir is picked up by the intake/upload ticks. dev/test never touched.
Resumable via staging/mls-pack/state.json. Usage: python scripts/mls_pack.py [G=4]    NOTE spec v1 stores raw s16 16 kHz = 115.2 MB per hour: size the plan before running."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, time, subprocess, shutil
from huggingface_hub import HfApi
import net_cap as _nc      # M-NET-2 (lead 82238): every lane download goes through the shared, cap-aware downloader (unthrottled while the cap is off)
def hf_hub_download(repo, path, repo_type="dataset", revision=None, local_dir=".", **kw): return _nc.download(repo, path, rev=revision, local_dir=local_dir, repo_type=repo_type)
from lane_config import LANE_ROOT as ROOT; W = ROOT + "/staging/mls-pack"; R = "wordingone/ember-raw-private"; G = int(sys.argv[1]) if len(sys.argv) > 1 else 4; TARGET_H = float(os.environ.get("MLS_HOURS", "500")); CAP_S = os.environ.get("MLS_SPK_CAP_S", "600")   # lead 81981: plan B = 500 h speaker-balanced subset
os.makedirs(W, exist_ok=True); ST = W + "/state.json"; state = json.load(open(ST)) if os.path.exists(ST) else {"done": {}}
pass; import reserve_plan
def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)
def wait_space(gib):
    while shutil.disk_usage("B:/").free / 2**30 - gib < reserve_plan.floor_gib() + 1: log("waiting for space (reserve planner)", reserve_plan.describe()); time.sleep(120)
api = HfApi(); files = sorted((t.path, t.size) for t in api.list_repo_tree(R, repo_type="dataset", path_in_repo="audio/mls-eng", recursive=True) if hasattr(t, "size") and os.path.basename(t.path).startswith("train-"))
log(len(files), "train parquet files", round(sum(s for _, s in files) / 2**30, 1), "GiB")
groups = [files[i:i + G] for i in range(0, len(files), G)]
for gi, grp in enumerate(groups):
    name = f"mls-eng-train-g{gi:03d}"
    if name in state["done"]: continue
    if sum(v.get("hours", 0) for v in state["done"].values()) >= TARGET_H: log("target hours reached"); break
    gib = sum(s for _, s in grp) / 2**30; wait_space(gib * 6 + 5)      # parquet + decoded audio + packed PCM (~3-4x the opus size)
    paths = [hf_hub_download(R, p, repo_type="dataset", local_dir=W + f"/dl{gi}") for p, _ in grp]
    out = W + f"/prep{gi}"; r = subprocess.run([sys.executable, ROOT + "/scripts/mls_manifest.py", *paths, "--out", out, "--spk-state", W + "/speaker-seconds.json", "--cap-s", CAP_S], capture_output=True, text=True)
    if r.returncode: log("MANIFEST FAILED", r.stderr[-300:]); sys.exit(2)
    shutil.rmtree(W + f"/dl{gi}", ignore_errors=True)
    meta = out + "/meta.json"; json.dump({"dataset_id": "media:" + name, "content_date_max": "2020-12-31"}, open(meta, "w"))
    outd = "A:/ember-stage/media-packed" if shutil.disk_usage("A:/").free > 40 * 2**30 else ROOT + "/media-packed"
    r = subprocess.run([sys.executable, ROOT + "/scripts/pack_media.py", "audio", outd, name, out + "/manifest.jsonl", meta], capture_output=True, text=True); log(r.stdout[-300:], r.stderr[-200:])
    if r.returncode: sys.exit(3)
    hrs = json.load(open(out + "/stats.json")).get("seconds", 0) / 3600; shutil.rmtree(out, ignore_errors=True); state["done"][name] = dict(files=[p for p, _ in grp], ts=time.time(), hours=hrs); json.dump(state, open(ST, "w")); log("packed", name, "->", outd)
open(W + "/ALL.done", "w").write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())); log("DONE")
