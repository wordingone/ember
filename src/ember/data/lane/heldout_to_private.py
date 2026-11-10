# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Move the PUBLIC held-out eval set private (lead 82083, decided; no data is deleted anywhere):
  1. copy wordingone/ember-corpus:acquisition/heldout/ -> PRIVATE dataset repo (server-side CommitOperationCopy: no download/upload traffic, creates a commit on the destination);
  2. verify EVERY file: path set, size and server-side hash equal between source and destination (LFS sha256 for LFS files; git blob id for the few non-LFS files), and, when a local copy exists, local sha256 == server sha256; write the receipt logs/heldout-private-receipt.json;
  3. ONLY if 2 is 100% equal: remove acquisition/heldout/ from the PUBLIC repo head with one delete commit (history is untouched, the private copy is the custody copy);
  4. re-list the public head and prove the folder is gone and the private repo still has every file.
Usage: python scripts/heldout_to_private.py plan     (read-only listing + sizes)
       python scripts/heldout_to_private.py copy     (steps 1-2; creates the private repo if absent; never touches the public repo)
       python scripts/heldout_to_private.py remove   (steps 3-4; refuses unless a fresh verify of the private copy is 100% equal)
Run copy/remove only after the H39 restore milestone (lead 82083)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_RAW_REPO, LANE_ROOT
import sys as _hs; _hs.path.insert(0, (LANE_ROOT + "/scripts")); import hf_push   # lead 82104: one funnel for HF writes
import os, sys, json, time
from huggingface_hub import HfApi, CommitOperationDelete
PUB = "wordingone/ember-corpus"; PRIV = ("wordingone/" + HF_RAW_REPO); PREFIX = "acquisition/heldout"   # token is scoped to existing repos (no repo-create right, 403): custody copy lives in the existing PRIVATE raw repo
REC = (LANE_ROOT + "/logs/heldout-private-receipt.json")
api = HfApi()


def listing(repo, prefix):
    from huggingface_hub.errors import RemoteEntryNotFoundError
    out = {}
    try:
        for e in api.list_repo_tree(repo, path_in_repo=prefix, recursive=True, expand=True, repo_type="dataset"):
            if e.__class__.__name__ != "RepoFile": continue
            lfs = getattr(e, "lfs", None); out[e.path] = dict(size=e.size, lfs_sha256=(lfs["sha256"] if isinstance(lfs, dict) else getattr(lfs, "sha256", None)) if lfs else None, blob_id=e.blob_id)
    except RemoteEntryNotFoundError: pass      # folder absent = empty listing (after the public remove the prefix is gone)
    return out


def verify():
    s = listing(PUB, PREFIX); d = listing(PRIV, PREFIX); bad = []
    for p, r in s.items():
        q = d.get(p)
        if not q: bad.append((p, "missing at destination")); continue
        if q["size"] != r["size"]: bad.append((p, "size", r["size"], q["size"])); continue
        if r["lfs_sha256"] or q["lfs_sha256"]:
            if r["lfs_sha256"] != q["lfs_sha256"]: bad.append((p, "lfs sha256", r["lfs_sha256"], q["lfs_sha256"]))
        elif r["blob_id"] != q["blob_id"]: bad.append((p, "blob_id"))
    extra = sorted(set(d) - set(s))
    rec = dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), source=PUB, dest=PRIV, prefix=PREFIX, files=len(s), bytes=sum(r["size"] for r in s.values()), lfs_files=sum(1 for r in s.values() if r["lfs_sha256"]),
               dest_files=len(d), mismatches=bad[:20], n_mismatch=len(bad), extra_at_dest=extra[:10], equal=(not bad and len(d) >= len(s) and len(s) > 0),
               source_rev=api.dataset_info(PUB).sha, dest_rev=api.dataset_info(PRIV).sha, note="source and destination hashes are the server-side LFS sha256 (git blob id for non-LFS files); no local copy of this folder exists on this PC")
    json.dump(rec, open(REC, "w"), indent=1); return rec


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "plan"
    if mode == "plan":
        s = listing(PUB, PREFIX); print(f"{PUB}:{PREFIX}: {len(s)} files {sum(r['size'] for r in s.values())/2**30:.2f} GiB, LFS {sum(1 for r in s.values() if r['lfs_sha256'])}"); return
    if mode == "copy":
        info = api.dataset_info(PRIV)
        assert info.private, "destination must be PRIVATE"
        api.copy_files(f"hf://datasets/{PUB}/{PREFIX}/", f"hf://datasets/{PRIV}/{PREFIX}/")
        rec = verify(); print(json.dumps({k: rec[k] for k in ("files", "bytes", "dest_files", "n_mismatch", "equal")})); sys.exit(0 if rec["equal"] else 1)
    if mode == "remove":
        assert api.dataset_info(PRIV).private, "destination must be PRIVATE"
        rec = verify()
        if not rec["equal"]: print("REFUSED: private copy is not 100% equal to the public folder", rec["n_mismatch"], rec["mismatches"][:3]); sys.exit(1)
        hf_push.create_commit(api, repo_id=PUB, repo_type="dataset", operations=[CommitOperationDelete(path_in_repo=PREFIX + "/", is_folder=True)],
                          commit_message="Remove held-out eval set from public head (moved to a private repo; lead 82083). History untouched.")
        left = listing(PUB, PREFIX); back = listing(PRIV, PREFIX)
        rec.update(public_files_left=len(left), private_files_after=len(back), removed=(len(left) == 0 and len(back) == rec["files"]), public_rev_after=api.dataset_info(PUB).sha)
        json.dump(rec, open(REC, "w"), indent=1); print(json.dumps({k: rec[k] for k in ("files", "public_files_left", "private_files_after", "removed")})); sys.exit(0 if rec["removed"] else 1)
    print(__doc__)


if __name__ == "__main__":
    main()
