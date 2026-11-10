# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Upload Project Gutenberg raw gz + provenance files to the PRIVATE raw repo, ONE FILE AT A TIME (clean pause points; lead 81597).
Public-domain source, rule 6 (lead 81232/81592). Never overwrites: a remote file that already exists is skipped (size must match or the run stops).
No HOLD/pause checks (lead 81608); rerun resumes. Remote sha lines come from the separate verify step."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import sys as _hs; _hs.path.insert(0, (LANE_ROOT + "/scripts")); import hf_push   # lead 82104: one funnel for HF writes
import sys, os, glob, time
from huggingface_hub import HfApi, CommitOperationAdd
REPO = "wordingone/ember-raw-private"; DEST = "text/pg-raw"; SRC = (LANE_ROOT + "/pg")
api = HfApi()
prov = ["pg_catalog.csv", "pg-expected.tsv", "pg-expected2.tsv", "pg-verify.txt", "fetch_pg.log"]
files = sorted(os.path.basename(p) for p in glob.glob(SRC + "/*_pg.jsonl.gz")) + [p for p in prov if os.path.exists(f"{SRC}/{p}")]
def remote():
    try: return {t.path: t.size for t in api.list_repo_tree(REPO, repo_type="dataset", path_in_repo=DEST, recursive=True) if hasattr(t, "size")}
    except Exception as e:
        if "404" in str(e) or "Not Found" in str(e): return {}
        raise
have = remote(); done = skipped = 0
for f in files:
    rp = f"{DEST}/{f}"; sz = os.path.getsize(f"{SRC}/{f}")
    if rp in have:
        if have[rp] != sz: print("STOP: remote size differs for", rp, have[rp], sz); sys.exit(2)
        skipped += 1; continue
    t0 = time.time()
    hf_push.upload_file(api, path_or_fileobj=f"{SRC}/{f}", path_in_repo=rp, repo_id=REPO, repo_type="dataset", commit_message=f"PG raw {f} (Project Gutenberg, public domain; data data lane)")
    done += 1; print(f"uploaded {f} {sz} B in {time.time()-t0:.0f}s ({done} done, {skipped} skipped, {len(files)-done-skipped} left)", flush=True)
print("DONE", done, "uploaded", skipped, "already there", flush=True)
