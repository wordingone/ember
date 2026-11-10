# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Remedy for the HF secret-scan finding (lead 81676/81687): move ONE file from public ember-corpus to private <raw-repo>.
1. stream objects/heldout/...H-heldout-2.tar.gz from the PUBLIC repo to a temp file (Range-resume on drops), sha256 on the fly, must equal the public LFS oid.
2. upload to wordingone/<raw-repo> heldout/<same name>; verify remote LFS sha256 == public oid.
3. ONLY then delete that single path from ember-corpus HEAD (commit message states why). No history rewrite. Receipt: logs/remedy-hheldout2.json (no secret values anywhere)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_RAW_REPO, LANE_ROOT
import sys as _hs; _hs.path.insert(0, (LANE_ROOT + "/scripts")); import hf_push   # lead 82104: one funnel for HF writes
import os, sys, json, time, hashlib, requests
from huggingface_hub import HfApi
PUB = "wordingone/ember-corpus"; PRIV = ("wordingone/" + HF_RAW_REPO)
PATH = "objects/heldout/issue1719-license-partitions-wave10-20260819T0215Z__H-heldout-2.tar.gz"
DEST = "heldout/" + os.path.basename(PATH)
from lane_config import LANE_ROOT as ROOT; TMPD = ROOT + "/remedy"; os.makedirs(TMPD, exist_ok=True); LOC = TMPD + "/" + os.path.basename(PATH); RCPT = ROOT + "/logs/remedy-hheldout2.json"
api = HfApi()
def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)
info = api.get_paths_info(PUB, [PATH], repo_type="dataset", expand=True)[0]; size = info.size; oid = info.lfs.sha256
log("public file", size, "bytes, oid", oid[:12])
url = f"https://huggingface.co/datasets/{PUB}/resolve/main/{PATH}"
have = os.path.getsize(LOC) if os.path.exists(LOC) else 0
while have < size:
    try:
        with requests.get(url, stream=True, timeout=(30, 90), headers={"Range": f"bytes={have}-", "User-Agent": "ember-remedy/1.0"}) as r:
            r.raise_for_status()
            with open(LOC, "ab") as f:
                for c in r.iter_content(4 << 20): f.write(c); have += len(c)
    except Exception as e:
        log("drop:", type(e).__name__, "resuming at", have); time.sleep(5); have = os.path.getsize(LOC)
    log(f"downloaded {have/2**20:.0f}/{size/2**20:.0f} MiB")
h = hashlib.sha256()
with open(LOC, "rb") as f:
    for c in iter(lambda: f.read(8 << 20), b""): h.update(c)
if h.hexdigest() != oid: log("SHA MISMATCH local", h.hexdigest(), "!= public", oid, "- aborting, nothing uploaded or deleted"); sys.exit(2)
log("download sha256 == public oid")
hf_push.upload_file(api, path_or_fileobj=LOC, path_in_repo=DEST, repo_id=PRIV, repo_type="dataset", commit_message="heldout/: H-heldout-2 moved from public ember-corpus (third-party credentials found by the HF secret scan; lead 81687)")
ri = api.get_paths_info(PRIV, [DEST], repo_type="dataset", expand=True)[0]
if not (ri.lfs and ri.lfs.sha256 == oid and ri.size == size): log("PRIVATE VERIFY FAILED - public file NOT deleted"); sys.exit(3)
log("private copy verified: LFS sha256 == public oid; size equal")
c = api.delete_file(PATH, repo_id=PUB, repo_type="dataset", commit_message=("Remove objects/heldout/...H-heldout-2.tar.gz from public HEAD: third-party credentials found by the HF secret scan; moved to private (wordingone/" + HF_RAW_REPO + " heldout/). History not rewritten."))
json.dump(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), file=PATH, bytes=size, sha256=oid, private_repo=PRIV, private_path=DEST, public_delete_commit=str(c)), open(RCPT, "w"), indent=1)
os.remove(LOC); log("DONE: deleted from public HEAD;", c)
