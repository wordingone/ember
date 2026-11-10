# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Read-only scan that backs a drop manifest (lead 82361). For every file under the given local dirs: size, st_nlink, local sha256 (cached by path|size|mtime), and the HF custody that matches it by (LFS sha256, size) across the account's private repos.
Writes logs/drop-scan-<ts>.jsonl (one row per file) and prints the per-directory summary. Deletes nothing.
Usage: python drop_scan.py <dir> [<dir> ...]"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, time, hashlib
from concurrent.futures import ThreadPoolExecutor
from huggingface_hub import HfApi

SC = (LANE_ROOT + "/logs/sha-cache.json")
REPOS = ("wordingone/ember-raw-private", "wordingone/ember-train-private", "wordingone/ember-corpus")


def sha_of(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(16 << 20), b""): h.update(c)
    return h.hexdigest()


def main():
    dirs = [d.replace("\\", "/").rstrip("/") for d in sys.argv[1:]]
    api = HfApi(); idx = {}
    for repo in REPOS:
        for e in api.list_repo_tree(repo, recursive=True, expand=True, repo_type="dataset"):
            if e.__class__.__name__ == "RepoFile" and e.lfs:
                sh = e.lfs["sha256"] if isinstance(e.lfs, dict) else e.lfs.sha256
                idx.setdefault((sh, e.size), []).append(f"{repo}:{e.path}")
    print("HF (sha,size) keys:", len(idx), flush=True)
    cache = json.load(open(SC)) if os.path.exists(SC) else {}
    files = []
    for d in dirs:
        for dp, _, fn in os.walk(d):
            for f in fn:
                p = os.path.join(dp, f).replace("\\", "/")
                try: st = os.lstat(p)
                except OSError: continue
                files.append((d, p, st.st_size, st.st_nlink, int(st.st_mtime)))
    print("files:", len(files), "GiB", round(sum(f[2] for f in files) / 2**30, 2), flush=True)
    lock_rows = []

    def one(t):
        d, p, sz, nl, mt = t
        k = f"{p}|{sz}|{mt}"
        s = cache.get(k)
        try:
            if not s: s = sha_of(p); cache[k] = s
        except OSError as e:      # a file held open by a live job: reported, never a reason to stop the scan
            return dict(root=d, path=p, size=sz, nlink=nl, sha256=None, hf=[], error=type(e).__name__ + ": locked or unreadable")
        return dict(root=d, path=p, size=sz, nlink=nl, sha256=s, hf=idx.get((s, sz), [])[:2])
    t0 = time.time()
    with ThreadPoolExecutor(6) as ex: rows = list(ex.map(one, files))
    json.dump(cache, open(SC, "w"))
    out = f"{LANE_ROOT}/logs/drop-scan-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        for r in rows: f.write(json.dumps(r) + "\n")
    print("hashed in", round(time.time() - t0), "s ->", out, flush=True)
    by = {}
    for r in rows:
        b = by.setdefault(r["root"], dict(files=0, gib=0.0, on_hf_files=0, on_hf_gib=0.0, shared_nlink=0))
        b["files"] += 1; b["gib"] += r["size"] / 2**30
        if r["hf"]: b["on_hf_files"] += 1; b["on_hf_gib"] += r["size"] / 2**30
        if r["nlink"] > 1: b["shared_nlink"] += 1
    for k, v in by.items(): print(k, {a: round(b, 2) for a, b in v.items()}, flush=True)


if __name__ == "__main__":
    main()
