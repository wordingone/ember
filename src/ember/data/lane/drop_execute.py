# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Execute an ACKed drop manifest (lead 82379 ACK of 82377, manifest logs/drop-manifest-20261110T012235Z.tsv).
Tier 1: manifest rows DROP-FREE + DROP-HF-ONLY (waiver recorded in every HF-ONLY receipt row) plus scratch/orphan-packs files that match an HF copy.
Tier 2: named scratch dirs (intermediates of finished jobs). Skipped if any process names the dir or any file in it changed in the last 10 min.
Per Tier-1 file: st_nlink==1 re-checked now; server size + LFS sha256 read back now; local sha256 recomputed now; receipt row written BEFORE os.remove; skip on any mismatch. python only.
Usage: python drop_execute.py <manifest.tsv> [--go] [--tier2]   (default: dry, verifies but deletes nothing)"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_TRAIN_REPO, LANE_ROOT
import os, sys, json, time, hashlib, shutil, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from huggingface_hub import HfApi

from lane_config import LANE_ROOT as ROOT; REPO = ("wordingone/" + HF_TRAIN_REPO); ACK = "lead 82379 (ack of 82377)"
TIER2 = ["pes2o-00000-00002-pre-redaction-1230", "pes2o-00000-00002-redacted", "thdbg-t691x_z_",
         "wikipedia-20220501-p41243p151573-r2-pre-redaction-1223", "wikipedia-20220501-p41243p151573-r2"]
RC = f"{ROOT}/logs/drop-exec-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.jsonl"
lock = threading.Lock()


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(16 << 20), b""): h.update(c)
    return h.hexdigest()


def lfs_sha(e):
    return e.lfs["sha256"] if isinstance(e.lfs, dict) else e.lfs.sha256


def row(**kw):
    kw["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with lock, open(RC, "a", encoding="utf-8") as f: f.write(json.dumps(kw) + "\n")


def main():
    global ACK
    go = "--go" in sys.argv; tier2 = "--tier2" in sys.argv; no_orphan = "--no-orphan" in sys.argv
    if "--ack" in sys.argv: ACK = sys.argv[sys.argv.index("--ack") + 1]
    man = [a for a in sys.argv[1:] if not a.startswith("--") and a != ACK][0]
    api = HfApi(); hf = {}
    for e in api.list_repo_tree(REPO, path_in_repo="text", recursive=True, expand=True, repo_type="dataset"):
        if e.__class__.__name__ == "RepoFile" and e.lfs: hf[e.path] = (e.size, lfs_sha(e))
    print("server files indexed:", len(hf), flush=True)
    work = []
    for l in open(man, encoding="utf-8").read().splitlines()[1:]:
        cls, gib, pack, sub, key, path = l.split("\t")
        if cls in ("DROP-FREE", "DROP-HF-ONLY"): work.append((cls, REPO, key, path))
    # orphan-packs: any file whose (sha,size) matches an HF copy per the scan; the server is read again by path below
    scans = sorted(f for f in os.listdir(f"{ROOT}/logs") if f.startswith("drop-scan-") and f.endswith(".jsonl"))
    for l in (open(f"{ROOT}/logs/{scans[-1]}", encoding="utf-8") if scans and not no_orphan else []):
        r = json.loads(l)
        if "/scratch/orphan-packs/" in r["path"] and r["hf"] and r["nlink"] == 1:
            repo, _, hp = r["hf"][0].partition(":"); work.append(("ORPHAN", repo, hp, r["path"]))
    print("tier1 candidates:", len(work), flush=True)
    freed = {"DROP-FREE": 0, "DROP-HF-ONLY": 0, "ORPHAN": 0}; skipped = []; stop = [False]
    srv_cache = {}

    def server(repo, hp):
        if repo == REPO and hp in hf: return hf[hp]
        k = (repo, hp)
        if k not in srv_cache:
            try:
                e = api.get_paths_info(repo, [hp], repo_type="dataset", expand=True)
                srv_cache[k] = (e[0].size, lfs_sha(e[0])) if e and e[0].lfs else None
            except Exception: srv_cache[k] = None
        return srv_cache[k]

    def one(w):
        cls, repo, hp, p = w
        try:
            st = os.lstat(p)
            if st.st_nlink > 1: skipped.append((p, "nlink>1 (in the union)")); return
            s = server(repo, hp)
            if not s or s[0] != st.st_size: skipped.append((p, "no server copy of equal size")); return
            ls = sha(p)
            if ls != s[1]: skipped.append((p, "sha mismatch")); print("MISMATCH kept:", p, flush=True); return
            if go:
                row(tier=1, cls=cls, path=p.replace("\\", "/"), hf=f"{repo}:{hp}", size=st.st_size, sha256=ls, verified="server LFS sha256+size == local sha256+size, read back now", ack=ACK,
                    waiver=(ACK + ": class-guard waiver for admitted-unconsumed shard; pool becomes HF-only" if cls == "DROP-HF-ONLY" else None))
                os.remove(p)
            with lock: freed[cls] += st.st_size
        except FileNotFoundError: skipped.append((p, "already gone"))
        except OSError as e: skipped.append((p, type(e).__name__ + " " + str(e)[:80]))
    with ThreadPoolExecutor(3) as ex: list(ex.map(one, work))
    print(("" if go else "DRY ") + "tier1 freed GiB:", {k: round(v / 2**30, 2) for k, v in freed.items()}, "skipped", len(skipped), flush=True)
    for p, why in skipped[:20]: print("  skip", p, why, flush=True)
    if go: print("B free GiB after tier1:", round(shutil.disk_usage("B:/").free / 2**30, 1), flush=True)
    if tier2:
        import psutil
        cmd = " ".join(" ".join(p.info["cmdline"] or []) for p in psutil.process_iter(["cmdline"])).replace("\\", "/")
        t2 = 0
        for name in TIER2:
            d = f"{ROOT}/scratch/{name}"
            if not os.path.isdir(d): print("tier2 absent", name); continue
            if name in cmd: print("tier2 SKIP (a live process names it)", name, flush=True); continue
            files = []; newest = 0
            for dp, _, fn in os.walk(d):
                for f in fn:
                    q = os.path.join(dp, f).replace("\\", "/")
                    try: st = os.lstat(q)
                    except OSError: continue
                    files.append((q, st.st_size, st.st_nlink)); newest = max(newest, st.st_mtime)
            if time.time() - newest < 600: print("tier2 SKIP (changed in the last 10 min)", name, flush=True); continue
            if any(n > 1 for _, _, n in files): print("tier2 SKIP (hard-linked file inside)", name, flush=True); continue
            size = sum(s for _, s, _ in files)
            if go:
                row(tier=2, dir=d, files=[[q, s] for q, s, _ in files], bytes=size, verified="intermediate of a finished job; packed form on HF (lead 82377 tier 2)", ack=ACK)
                shutil.rmtree(d, ignore_errors=False)
            t2 += size; print(("" if go else "DRY ") + "tier2", name, round(size / 2**30, 2), "GiB", flush=True)
        print("tier2 GiB:", round(t2 / 2**30, 2), flush=True)
    print("B free GiB now:", round(shutil.disk_usage("B:/").free / 2**30, 1), "receipt:", RC, flush=True)


if __name__ == "__main__":
    main()
