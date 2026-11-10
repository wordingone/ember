# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Restore files our delete manifests removed (lead 81958). Source = the HF copy named in the manifest row (hf_ref 'repo:path' or the ckpt-delete rows' hf_repo/hf_path).
Safe by construction: download each UNIQUE sha256 once into <lane-root>/scratch/restore (never inside a checkpoint dir), verify sha256 == manifest sha256, then place a COPY at the original path via a temp name in the
same scratch volume + os.replace (atomic, no stray tmp files can land inside objects/). A file already present with the right size+sha is left alone. Ledger: logs/ckpt-restore.jsonl. Resumable.
Usage: python ckpt_restore.py plan [--chain H39] [--only objects|all]      (prints counts/bytes, writes nothing)
       python ckpt_restore.py run  [--chain H39] [--only objects|all]
--only objects restores objects/*.pt + small files first; 'all' adds optimizer-state.pt (the 1.9 GB per-child file)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import json, sys, os, time, hashlib, shutil, collections
pass
import ckpt_chain as K
from huggingface_hub import hf_hub_download

SCR = (LANE_ROOT + "/scratch/restore"); LEDGER = (LANE_ROOT + "/logs/ckpt-restore.jsonl")
BS = chr(92)


def sha256f(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 24), b""):
            h.update(c)
    return h.hexdigest()


def ref_of(r):
    if r.get("hf_ref"):
        repo, path = r["hf_ref"].split(":", 1); return repo, path
    return r["hf_repo"], r["hf_path"]


def load(chain_name, only):
    ch = K.chain(__import__("ckpt_children").CH[chain_name][1]); rows = []
    dels = collections.defaultdict(list)
    for r in K.deleted_rows():
        dels[K.child_dir(r["path"])].append(r)
    for c in ch:
        rows += dels.get(c["dir"], [])
    if only == "objects":
        rows = [r for r in rows if "/objects/" in K.norm(r["path"])]
    return rows


def done_sha():
    d = set()
    if os.path.exists(LEDGER):
        for l in open(LEDGER):
            try:
                d.add(json.loads(l)["path"])
            except Exception:
                pass
    return d


def main():
    mode = sys.argv[1]; name = sys.argv[sys.argv.index("--chain") + 1] if "--chain" in sys.argv else "H39"
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else "all"
    rows = load(name, only); uniq = {}
    for r in rows:
        uniq.setdefault(r["sha256"], r)
    print(f"chain {name}: files to restore {len(rows)} ({sum(r['size'] for r in rows)/2**30:.1f} GiB logical) | unique sha256 to download {len(uniq)} ({sum(r['size'] for r in uniq.values())/2**30:.1f} GiB)")
    if mode == "plan":
        return
    os.makedirs(SCR, exist_ok=True); dn = done_sha()
    by_sha = collections.defaultdict(list)
    for r in rows:
        by_sha[r["sha256"]].append(r)
    order = sorted(by_sha, key=lambda s: by_sha[s][0]["size"])        # small first: progress is visible early
    import threading
    lock = threading.Lock(); cnt = [0]

    def one(s):
        targets = [r for r in by_sha[s] if K.norm(r["path"]) not in dn and not os.path.exists(r["path"])]
        if not targets:
            return
        r0 = targets[0]; repo, hp = ref_of(r0); t0 = time.time(); p = None
        for att in range(1, 6):
            try:
                tmpd = SCR + "/dl-" + s[:12]
                p = hf_hub_download(repo, hp, repo_type="dataset", local_dir=tmpd)
                if sha256f(p) != s or os.path.getsize(p) != r0["size"]:
                    raise RuntimeError("sha256/size mismatch after download")
                break
            except Exception as e:
                p = None; print("retry", att, type(e).__name__, str(e)[:100], flush=True); shutil.rmtree(SCR + "/dl-" + s[:12], ignore_errors=True); time.sleep(15)
        if p is None:
            print("GAVE UP", hp, flush=True); return
        for r in targets:
            os.makedirs(os.path.dirname(r["path"]), exist_ok=True)
            tmp = SCR + "/place-" + s[:12] + ".tmp"; shutil.copyfile(p, tmp)
            os.replace(tmp, r["path"])
            with lock, open(LEDGER, "a") as f:
                f.write(json.dumps(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), path=K.norm(r["path"]), size=r["size"], sha256=s, via=repo + ":" + hp, secs=round(time.time() - t0, 1))) + "\n")
        shutil.rmtree(SCR + "/dl-" + s[:12], ignore_errors=True)
        with lock:
            cnt[0] += 1
            if cnt[0] % 5 == 0: print(time.strftime("%H:%M:%S"), cnt[0], "/", len(order), "unique files restored", flush=True)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(int(os.environ.get("RESTORE_WORKERS", "4"))) as ex:
        list(ex.map(one, order))
    print("RESTORE DONE", flush=True)


if __name__ == "__main__":
    main()
