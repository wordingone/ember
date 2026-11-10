# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Rolling raw budget (lead 81397): upload local raw files to the PRIVATE raw HF repo, verify (LFS sha256 + size), then delete the local copy with a receipt.
roll(files=[(local_path, path_in_repo)], repo) -> list of rows. Receipts: audit/raw-roll-receipts.jsonl (one row per deleted file: local, repo, path, bytes, sha256, commit).
#2454: the delete is verified_remove.remove_verified per file: inside <lane-root> with no link/junction on the way, st_nlink == 1, the server entry read back NOW with size AND LFS sha256 (an entry without an LFS sha256 is NOT
accepted on size alone any more), local sha256 recomputed NOW, and the receipt row (both hashes) fsynced BEFORE the os.remove. A file that does not verify stays local and is returned with ok=False and the reason.
CLI: raw_roll.py lv-catchup  -> roll every mp3 in lvpilot/pairs.jsonl still on disk (batches of 100)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_RAW_REPO, LANE_ROOT
import sys as _hs; _hs.path.insert(0, (LANE_ROOT + "/scripts")); import hf_push   # lead 82104: one funnel for HF writes
import verified_remove as VR
import os, sys, json, time, hashlib
from huggingface_hub import HfApi, CommitOperationAdd
from lane_config import LANE_ROOT as ROOT; REC = ROOT + "/audit/raw-roll-receipts.jsonl"
def sha256f(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 24), b""): h.update(b)
    return h.hexdigest()
def roll(files, repo=("wordingone/" + HF_RAW_REPO), message="raw roll", reader=None, remove=os.remove, receipt=None):
    api = HfApi(); files = [(l, r) for l, r in files if os.path.exists(l)]
    if not files: return []
    sys.path.insert(0, ROOT + "/scripts"); import upload_refuse
    for l, _ in files: upload_refuse.check(l)      # lead 82100: pre-redaction originals never upload
    commit = hf_push.create_commit(api, repo_id=repo, repo_type="dataset", operations=[CommitOperationAdd(path_in_repo=r, path_or_fileobj=l) for l, r in files], commit_message=f"{message} ({len(files)} files)")
    reader = reader or VR.hub_reader(); out = []
    for l, r in files:
        res = VR.remove_verified(l, repo, r, roots=[ROOT], receipt=receipt or REC, authority="lead 81397 rolling raw budget", reader=reader, remove=remove, extra=dict(commit=getattr(commit, "oid", None)))
        out.append(dict(local=l.replace(chr(92), "/"), repo=repo, path=r, bytes=res["size"], commit=getattr(commit, "oid", None), ok=res["ok"], why=res["why"], verified=("lfs_sha256" if res["ok"] else None)))
    return out
if __name__ == "__main__" and sys.argv[1:] == ["lv-catchup"]:
    rows = [json.loads(l) for l in open(ROOT + "/lvpilot/pairs.jsonl", encoding="utf-8")]; todo = []
    for r in rows:
        if os.path.exists(r["path"]): todo.append((r["path"], "audio/librivox/" + r["section_id"].split("-")[0][2:] + "/" + os.path.basename(r["path"])))
    n = 0
    for i in range(0, len(todo), 100):
        res = roll(todo[i:i + 100], message="librivox mp3 catch-up"); n += sum(1 for x in res if x["ok"]); print(i, n, flush=True)
    print("rolled", n, "of", len(todo))
