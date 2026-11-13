# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Verify PG raw gz on HF by sha256, then delete ONLY exact local==HF-LFS matches (lead 81589/81592).
Per file: local sha256, HF LFS sha256 (repo@revision), receipt row written BEFORE os.remove. Mismatch/missing: keep + list.
Provenance files (catalog/expected/verify/log) and all derived intermediates are kept. No shell rm; os.remove on files under pg/ only."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_RAW_REPO, LANE_ROOT
import os, glob, json, hashlib, time, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import protected_set as _PS
from huggingface_hub import HfApi
REPO = ("wordingone/" + HF_RAW_REPO); DEST = "text/pg-raw"; SRC = (LANE_ROOT + "/pg")
RECEIPT = (LANE_ROOT + "/logs/pg-delete-receipts.jsonl")
api = HfApi()
rev = api.dataset_info(REPO).sha
files = sorted(glob.glob(SRC + "/*_pg.jsonl.gz"))
paths = [f"{DEST}/{os.path.basename(f)}" for f in files]
info = {}
for i in range(0, len(paths), 50):
    for t in api.get_paths_info(REPO, paths[i:i+50], repo_type="dataset", expand=True):
        info[t.path] = t
freed = 0; kept = []; deleted = 0
for f in files:
    rp = f"{DEST}/{os.path.basename(f)}"; t = info.get(rp)
    sz = os.path.getsize(f)
    bq, bwhy = _PS.bound_hit(f)       # #2488: a gate-bound or live-lineage-root path is kept, never removed
    if bq: kept.append((f, bwhy)); continue
    if t is None or getattr(t, "lfs", None) is None:
        kept.append((f, "missing on HF or no LFS sha")); continue
    h = hashlib.sha256()
    with open(f, "rb") as fh:
        for b in iter(lambda: fh.read(8 << 20), b""): h.update(b)
    local = h.hexdigest(); remote = t.lfs.sha256 if hasattr(t.lfs, "sha256") else t.lfs["sha256"]
    if local != remote or t.size != sz:
        kept.append((f, f"MISMATCH local {local} hf {remote} size {sz}/{t.size}")); continue
    row = dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), path=f, bytes=sz, local_sha256=local, hf_repo=f"{REPO}@{rev}", hf_path=rp, hf_sha256=remote, action="delete")
    with open(RECEIPT, "a", encoding="utf-8") as r: r.write(json.dumps(row) + "\n")
    os.remove(f); freed += sz; deleted += 1
    print(f"deleted {os.path.basename(f)} {sz} B sha {local[:12]} == HF {remote[:12]}", flush=True)
print(f"DONE deleted {deleted} freed {freed} B = {freed/2**30:.2f} GiB; kept {len(kept)}", flush=True)
for k in kept: print("KEPT", k, flush=True)
print("repo_revision", rev)
