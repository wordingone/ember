# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Rolling raw budget (lead 81397): upload local raw files to the PRIVATE raw HF repo, verify (LFS sha256 or size), then delete the local copy with a receipt.
roll(files=[(local_path, path_in_repo)], repo) -> list of rows. Receipts: audit/raw-roll-receipts.jsonl (one row per deleted file: local, repo, path, bytes, sha256, commit).
CLI: raw_roll.py lv-catchup  -> roll every mp3 in lvpilot/pairs.jsonl still on disk (batches of 100)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_RAW_REPO, LANE_ROOT
import sys as _hs; _hs.path.insert(0, (LANE_ROOT + "/scripts")); import hf_push   # lead 82104: one funnel for HF writes
import os, sys, json, time, hashlib
from huggingface_hub import HfApi, CommitOperationAdd
from lane_config import LANE_ROOT as ROOT; REC = ROOT + "/audit/raw-roll-receipts.jsonl"
def sha256f(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 24), b""): h.update(b)
    return h.hexdigest()
def roll(files, repo=("wordingone/" + HF_RAW_REPO), message="raw roll"):
    api = HfApi(); files = [(l, r) for l, r in files if os.path.exists(l)]
    if not files: return []
    sys.path.insert(0, ROOT + "/scripts"); import upload_refuse
    for l, _ in files: upload_refuse.check(l)      # lead 82100: pre-redaction originals never upload
    sh = {l: sha256f(l) for l, _ in files}
    commit = hf_push.create_commit(api, repo_id=repo, repo_type="dataset", operations=[CommitOperationAdd(path_in_repo=r, path_or_fileobj=l) for l, r in files], commit_message=f"{message} ({len(files)} files)")
    info = {i.path: i for i in api.get_paths_info(repo, [r for _, r in files], repo_type="dataset")}
    out = []; os.makedirs(ROOT + "/audit", exist_ok=True)
    with open(REC, "a", encoding="utf-8") as fo:
        for l, r in files:
            i = info.get(r); size = os.path.getsize(l)
            ok = bool(i) and ((getattr(i, "lfs", None) and i.lfs.sha256 == sh[l]) or (not getattr(i, "lfs", None) and i.size == size))
            if not ok: out.append(dict(local=l, ok=False)); continue
            row = dict(ts=time.strftime("%Y-%m-%dT%H:%M:%S"), local=l.replace(chr(92), "/"), repo=repo, path=r, bytes=size, sha256=sh[l], commit=getattr(commit, "oid", None), verified="lfs_sha256" if getattr(i, "lfs", None) else "size")
            os.remove(l); fo.write(json.dumps(row) + "\n"); out.append(dict(row, ok=True))
    return out
if __name__ == "__main__" and sys.argv[1:] == ["lv-catchup"]:
    rows = [json.loads(l) for l in open(ROOT + "/lvpilot/pairs.jsonl", encoding="utf-8")]; todo = []
    for r in rows:
        if os.path.exists(r["path"]): todo.append((r["path"], "audio/librivox/" + r["section_id"].split("-")[0][2:] + "/" + os.path.basename(r["path"])))
    n = 0
    for i in range(0, len(todo), 100):
        res = roll(todo[i:i + 100], message="librivox mp3 catch-up"); n += sum(1 for x in res if x["ok"]); print(i, n, flush=True)
    print("rolled", n, "of", len(todo))
