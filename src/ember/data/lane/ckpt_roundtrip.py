# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, M_ROOT
import os, sys, hashlib, time, json
T = (LANE_ROOT + "/tmp-roundtrip")
os.environ["HF_XET_CACHE"] = T + "/xet"; os.environ["HF_HUB_CACHE"] = T + "/hub"   # token stays at the default HF_HOME; only caches move to B:
from huggingface_hub import hf_hub_download, HfApi
D = (M_ROOT + "/ember-live-receipts/cia-hour-a1-five-attn-stage-d4-20261107T073017Z/measurement-60bd6b8de01742389ea577ca2ccdbd0a/trained-child")
REPO = "wordingone/ember-raw-private"; DEST = "checkpoints/d4a908e3-H39"
def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 24), b""): h.update(c)
    return h.hexdigest()
api = HfApi()
for rel in ["objects/9205a0f9e0117a667e411c3862e4f4a6d2c0bd098240ec8df8a8c7b1b53320e3.pt", "optimizer-state.pt"]:
    ri = api.get_paths_info(REPO, [f"{DEST}/{rel}"], repo_type="dataset", expand=True)[0]
    t0 = time.time()
    p = hf_hub_download(REPO, f"{DEST}/{rel}", repo_type="dataset", local_dir=T + "/dl")
    dt = time.time() - t0
    rs = sha(p); ls = sha(D + "/" + rel)
    m = (rs == ls == (ri.lfs.sha256 if ri.lfs else ls))
    if m and not os.path.exists((LANE_ROOT + "/logs/ckpt-roundtrip.PASS")): open((LANE_ROOT + "/logs/ckpt-roundtrip.PASS"), "w").write(json.dumps(dict(rel=rel, sha=rs, ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))))   # gate for ckpt_backup deletes (lead 81923)
    print(json.dumps(dict(rel=rel, size=os.path.getsize(p), local_size=os.path.getsize(D + "/" + rel), dl_s=round(dt), server_lfs_sha=ri.lfs.sha256 if ri.lfs else None, downloaded_sha=rs, local_sha=ls, match=(rs == ls == (ri.lfs.sha256 if ri.lfs else ls)))), flush=True)
print("ROUNDTRIP DONE", flush=True)
