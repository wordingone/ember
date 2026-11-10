# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Drop a packed set's local shards/objects right after its private upload is server-verified (lead 82379 item 4 / 82381: "each set becomes droppable when its upload is verified; mail me each set when server-verified and dropped").
Called by tick.py upload() the moment a set flips to VERIFIED, and runnable by hand: python drop_uploaded.py <local pack dir> [<repo> <hf prefix>] [--go]
Per file under <local>/shards and <local>/objects: st_nlink==1 (a hard-linked file is in the training catalog union: kept), server size == local size, server LFS sha256 == local sha256 recomputed now; the receipt row is written BEFORE os.remove; any mismatch keeps the file.
docs-index / ledger / receipt / intake / source-manifest / prov files are never touched. Python only."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, time, hashlib, shutil
from lane_config import LANE_ROOT as ROOT; RC = ROOT + "/logs/drop-uploaded-receipts.jsonl"
ACK = "lead 82379(4)/82381: drop each set once its private upload is server-verified; HF-only pool waiver as 82379(2)"


def _sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(16 << 20), b""): h.update(c)
    return h.hexdigest()


def server_index(repo, prefix):
    from huggingface_hub import HfApi
    out = {}
    for e in HfApi().list_repo_tree(repo, path_in_repo=prefix, recursive=True, expand=True, repo_type="dataset"):
        if e.__class__.__name__ == "RepoFile" and e.lfs: out[e.path] = (e.size, e.lfs["sha256"] if isinstance(e.lfs, dict) else e.lfs.sha256)
    return out


def drop_pack(local, repo, prefix, srv=None, go=True, receipt=RC, remove=os.remove, subdirs=("shards", "objects")):
    """Returns dict(dropped_files, dropped_bytes, kept=[(path, why)]). `srv` maps hf path -> (size, sha256); fetched from the server when None."""
    local = local.replace("\\", "/").rstrip("/"); srv = srv if srv is not None else server_index(repo, prefix)
    res = dict(dropped_files=0, dropped_bytes=0, kept=[])
    for sub in subdirs:
        d = f"{local}/{sub}"
        if not os.path.isdir(d): continue
        for f in sorted(os.listdir(d)):
            p = f"{d}/{f}"; key = f"{prefix.rstrip('/')}/{sub}/{f}"
            try:
                st = os.lstat(p)
                if st.st_nlink > 1: res["kept"].append((p, "nlink>1 (in the training catalog union)")); continue
                s = srv.get(key)
                if not s or s[0] != st.st_size: res["kept"].append((p, "no server copy of equal size")); continue
                ls = _sha(p)
                if ls != s[1]: res["kept"].append((p, "sha mismatch")); continue
                if go:
                    with open(receipt, "a", encoding="utf-8") as r:
                        r.write(json.dumps(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), path=p, hf=f"{repo}:{key}", size=st.st_size, sha256=ls, verified="server LFS sha256+size == local sha256+size, read back now", ack=ACK)) + "\n")
                    remove(p)
                res["dropped_files"] += 1; res["dropped_bytes"] += st.st_size
            except FileNotFoundError: res["kept"].append((p, "already gone"))
            except OSError as e: res["kept"].append((p, type(e).__name__))
    return res


def run(local, repo="wordingone/ember-train-private", prefix=None, go=True):
    prefix = prefix or "text/" + os.path.basename(local.rstrip("/\\"))
    res = drop_pack(local, repo, prefix, go=go)
    free = shutil.disk_usage("B:/").free / 2**30
    msg = f"{os.path.basename(local.rstrip('/'))}: server-verified and {'dropped' if go else 'DRY would drop'} {res['dropped_files']} files {res['dropped_bytes']/2**30:.2f} GiB (kept {len(res['kept'])}); B free {free:.1f} GiB; receipts {RC}"
    return res, msg


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    r, m = run(a[0], *(a[1:3] if len(a) >= 3 else ()), go="--go" in sys.argv)
    print(m)
    for p, why in r["kept"][:10]: print("  kept", p, why)
