# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Remove from the PUBLIC ember-corpus HEAD every path whose LFS sha256 also lives in PRIVATE <raw-repo> (lead 82187 approved; training 82190 go: HEAD only, no history rewrite / super-squash).
Order inside: (a) re-read BOTH sides per file from the server now: corpus path must exist with lfs sha256+size == manifest; at least one raw-private path must exist with the same sha256+size; any mismatch aborts the whole run (nothing deleted);
(c) receipt rows (logs/dup-ckpt-delete-receipts.jsonl) are written BEFORE the single delete commit; the commit is made through hf_push; afterwards re-list and prove zero shared shas remain and every raw-private copy is intact.
Usage: python scripts/dup_ckpt_delete.py [--dry] [--wait-h46]   (without --wait-h46 a real run REFUSES while <m-root>/avir/<lead>/state/gpu-window-open exists)      Manifest: logs/dup-ckpt-20261109.json (written by dup_ckpt_report.py).  NEVER touches history."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_RAW_REPO, LANE_ROOT, M_ROOT, SEAT_LEAD
import os, sys, json, time
pass; import hf_push
from huggingface_hub import HfApi, CommitOperationDelete, CommitOperationAdd
A = "wordingone/ember-corpus"; B = ("wordingone/" + HF_RAW_REPO); MAN = (LANE_ROOT + "/logs/dup-ckpt-20261109.json"); RC = (LANE_ROOT + "/logs/dup-ckpt-delete-receipts.jsonl")
MARKER = (M_ROOT + "/avir/" + SEAT_LEAD + "/state/gpu-window-open")      # present while a governed hour (H46) window is open; lead 82193: the delete must not run until it clears
api = HfApi(); dry = "--dry" in sys.argv


def sha_size(repo, paths):
    out = {}
    for i in range(0, len(paths), 200):
        for e in api.get_paths_info(repo, paths[i:i + 200], expand=True, repo_type="dataset"):
            lf = e.lfs; out[e.path] = ((lf["sha256"] if isinstance(lf, dict) else lf.sha256) if lf else None, e.size)
    return out


def wait_marker(poll=60, max_s=6 * 3600):
    t0 = time.time()
    while os.path.exists(MARKER):
        if time.time() - t0 > max_s: print("GIVE UP: window marker still present after", max_s, "s; nothing deleted"); sys.exit(3)
        print(time.strftime("%H:%M:%S"), "waiting: gpu-window-open marker present (H46 not ENDed)", flush=True); time.sleep(poll)


def main():
    if not dry:
        if "--wait-h46" in sys.argv: wait_marker()
        elif os.path.exists(MARKER): print("REFUSED: gpu-window-open marker present (H46 window open); pass --wait-h46 to wait for it to clear (lead 82193)"); sys.exit(3)
    man = json.load(open(MAN)); rows = man["rows"]; assert api.dataset_info(B).private, "raw repo must be private"
    cp = [p for r in rows for p in r["corpus_paths"]]; rp = [p for r in rows for p in r["raw_paths"]]
    sa = sha_size(A, cp); sb = sha_size(B, rp); bad = []; ops = []; rc = []
    for r in rows:
        want = (r["sha256"], r["size"])
        okraw = sorted((p for p in r["raw_paths"] if sb.get(p) == want), key=lambda p: (not p.startswith("checkpoints/evict-custody-20261109/objects/"), p))      # prefer the custody path training names
        if not okraw: bad.append((r["sha256"], "no raw-private path with equal sha+size")); continue
        for p in r["corpus_paths"]:
            if sa.get(p) != want: bad.append((p, "corpus server sha/size != manifest", sa.get(p))); continue
            ops.append(CommitOperationDelete(path_in_repo=p)); rc.append(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), repo=A, path=p, sha256=r["sha256"], size=r["size"], raw_copy=f"{B}:{okraw[0]}", verified="server re-read both sides now: equal sha256+size", authority="lead 82187 / training 82190"))
    assert not any(c["path"].endswith("INDEX.json") for c in rc), "INDEX.json must stay byte-identical (training 82194)"
    reloc = {c["path"]: dict(sha256=c["sha256"], size=c["size"], raw_private_repo=B, raw_private_path=c["raw_copy"].split(":", 1)[1]) for c in rc}
    RELOC_PATH = "checkpoints/lineage-2119/RELOCATED-20261109.json"
    relocbytes = json.dumps(dict(schema="ember-relocation-v1", note="Objects removed from HEAD of this public repo because byte-identical copies live in the private repo (same sha256+size, verified on the server). INDEX.json is unchanged (publication record); history is untouched.", removed=len(reloc), unique_shas=len(rows), paths=reloc), indent=1, sort_keys=True).encode()
    print(f"paths to delete {len(ops)} over {len(rows)} shas ({sum(c['size'] for c in rc)/2**30:.2f} GiB logical); mismatches {len(bad)}")
    if bad: print("ABORT:", bad[:5]); sys.exit(1)
    if dry: print("DRY: nothing written; relocation map would be %d bytes" % len(relocbytes) + ""); return
    with open(RC, "a", encoding="utf-8") as f:
        for x in rc: f.write(json.dumps(x) + "\n")                       # receipts BEFORE the commit
    if sha_size(A, [RELOC_PATH]): print("ABORT: RELOCATED file already exists at HEAD; never overwritten"); sys.exit(1)
    open((LANE_ROOT + "/logs/RELOCATED-20261109.json"), "wb").write(relocbytes)
    hf_push.create_commit(api, repo_id=A, repo_type="dataset", operations=ops + [CommitOperationAdd(path_in_repo=RELOC_PATH, path_or_fileobj=relocbytes)], commit_message=f"Remove {len(ops)} checkpoint object paths ({len(rows)} shas) duplicated in a private repo (lead 82187). HEAD only; history untouched.")
    left = [p for p in cp if p in sha_size(A, cp)]      # get_paths_info returns only paths that still exist
    sb2 = sha_size(B, rp); intact = all(any(sb2.get(p) == (r["sha256"], r["size"]) for p in r["raw_paths"]) for r in rows)
    post = dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), deleted=len(ops), corpus_paths_still_present=len(left), raw_private_intact=intact, corpus_rev=api.dataset_info(A).sha)
    json.dump(post, open((LANE_ROOT + "/logs/dup-ckpt-delete-post.json"), "w"), indent=1); print(post)
    sys.exit(0 if not left and intact else 1)


if __name__ == "__main__":
    main()
