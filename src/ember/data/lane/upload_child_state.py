# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Upload a checkpoint child's optimizer-state.pt + replay-state.pt (plus its manifest and expert index, so the HF dir restores on its own) to the private raw repo (lead 82370).
Order: local sha256 recompute vs the manifest (optimizer + replay) -> hf_cap.check -> ONE commit through the hf_push funnel (never overwrites an existing path; refuses if the target already holds any file) -> server read-back of every file (LFS sha256 for the .pt files, size for all) -> receipt row.
Usage: python upload_child_state.py <trained-child dir> <id8-name>          e.g. ... e73486d2-H44"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_RAW_REPO, LANE_ROOT
import os, sys, json, glob, time, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hf_cap, hf_push
from huggingface_hub import HfApi, CommitOperationAdd

REPO = ("wordingone/" + HF_RAW_REPO); RT = "dataset"; RC = (LANE_ROOT + "/logs/upload-child-state-receipts.jsonl")


def sha_of(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(16 << 20), b""): h.update(c)
    return h.hexdigest()


def main():
    d = sys.argv[1].replace("\\", "/").rstrip("/"); tag = sys.argv[2]; dest = f"checkpoints/{tag}"
    m = json.load(open(d + "/checkpoint-manifest.json", encoding="utf-8"))
    if sha_of(d + "/checkpoint-manifest.json")[:8] != tag.split("-")[0]: raise SystemExit("manifest sha prefix != child id: refusing")
    files = {"optimizer-state.pt": d + "/optimizer-state.pt", "replay-state.pt": d + "/replay-state.pt", "checkpoint-manifest.json": d + "/checkpoint-manifest.json"}
    for e in glob.glob(d + "/expert-index-*.json"): files[os.path.basename(e)] = e.replace("\\", "/")
    sh = {rel: sha_of(p) for rel, p in files.items()}
    if sh["optimizer-state.pt"] != m["optimizer"]["sha256"] or sh["replay-state.pt"] != m["replay"]["sha256"]: raise SystemExit("optimizer/replay sha != manifest: refusing")
    size = {rel: os.path.getsize(p) for rel, p in files.items()}
    print("local verified", {k: (size[k], sh[k][:12]) for k in files}, flush=True)
    api = HfApi()
    from huggingface_hub.errors import RemoteEntryNotFoundError
    try: have = [t.path for t in api.list_repo_tree(REPO, repo_type=RT, path_in_repo=dest, recursive=True) if hasattr(t, "size")]
    except RemoteEntryNotFoundError: have = []      # the target dir does not exist yet: the expected case
    if have: raise SystemExit(f"{dest} already holds files {have[:3]}: refusing to overwrite")
    while not hf_cap.check(sum(size.values()), f"ckpt state {tag}", REPO): time.sleep(300)
    ops = []
    for rel, p in files.items():
        hf_push.check_path(p); ops.append(CommitOperationAdd(path_in_repo=f"{dest}/{rel}", path_or_fileobj=p))
    t0 = time.time()
    hf_push.create_commit(api, repo_id=REPO, repo_type=RT, operations=ops, commit_message=f"{tag} optimizer + replay state, manifest, expert index (lead 82370)")
    print("committed in", round(time.time() - t0), "s", flush=True)
    srv = {i.path: i for i in api.get_paths_info(REPO, [f"{dest}/{r}" for r in files], expand=True, repo_type=RT)}
    bad = []
    for rel in files:
        i = srv.get(f"{dest}/{rel}")
        lf = getattr(i, "lfs", None) if i else None
        ssha = (lf["sha256"] if isinstance(lf, dict) else getattr(lf, "sha256", None)) if lf else None
        if i is None or i.size != size[rel] or (rel.endswith(".pt") and ssha != sh[rel]): bad.append(rel)
    row = dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), repo=REPO, dest=dest, files={r: dict(size=size[r], sha256=sh[r]) for r in files}, server_verified=not bad, bad=bad, seconds=round(time.time() - t0), authority="lead 82370")
    open(RC, "a", encoding="utf-8").write(json.dumps(row) + "\n")
    print("SERVER READ-BACK", "OK" if not bad else f"MISMATCH {bad}", flush=True)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
