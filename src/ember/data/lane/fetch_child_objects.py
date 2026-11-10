# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Download checkpoint objects from private HF custody into a staging dir and verify them (lead 82368: H44 child core + two experts, ~0.9 GiB, ahead of other fetches).
Never writes into the live receipts tree; the owner of the checkpoint places the files. Per object: server LFS sha256/size read first, then the download, then a local sha256 recompute; a receipt row is appended after each verified file.
Usage: python fetch_child_objects.py <dest_dir> <receipt.jsonl> <sha256>[:<sha256>...]     (objects are located by LFS sha256 in the private raw repo under checkpoints/)"""
import os, sys, json, time, hashlib
from huggingface_hub import HfApi, hf_hub_download

REPO = "wordingone/ember-raw-private"


def sha_of(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(16 << 20), b""): h.update(c)
    return h.hexdigest()


def main():
    dest, rcpt, shas = sys.argv[1], sys.argv[2], sys.argv[3].split(":")
    os.makedirs(dest, exist_ok=True)
    api = HfApi(); idx = {}
    for e in api.list_repo_tree(REPO, path_in_repo="checkpoints", recursive=True, expand=True, repo_type="dataset"):
        if e.__class__.__name__ == "RepoFile" and e.lfs:
            sh = e.lfs["sha256"] if isinstance(e.lfs, dict) else e.lfs.sha256
            idx.setdefault(sh, (e.path, e.size))
    bad = 0
    for s in shas:
        hit = idx.get(s)
        if not hit: print("MISSING on HF:", s, flush=True); bad += 1; continue
        out = os.path.join(dest, s + ".pt")
        if os.path.exists(out) and os.path.getsize(out) == hit[1] and sha_of(out) == s:
            print("already verified", s[:12], flush=True); continue
        t0 = time.time()
        p = hf_hub_download(REPO, hit[0], repo_type="dataset", local_dir=os.path.join(dest, "_dl"))
        if os.path.getsize(p) != hit[1] or sha_of(p) != s:
            print("MISMATCH after download:", s[:12], flush=True); bad += 1; continue
        os.replace(p, out)
        with open(rcpt, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), sha256=s, size=hit[1], hf=f"{REPO}:{hit[0]}", staged=out.replace("\\", "/"), verified="server LFS sha256+size read before the download; local sha256 recomputed == name", seconds=round(time.time() - t0))) + "\n")
        print("verified", s[:12], hit[1], "bytes in", round(time.time() - t0), "s", flush=True)
    print("DONE bad=%d" % bad, flush=True)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
