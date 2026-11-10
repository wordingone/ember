# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Free space on B: (lead 81345). Verified-duplicate / verified-on-HF / ruled regenerable-garbage deletes only. Receipts: audit/free-b-receipts-<ts>.jsonl (one row per file, fsynced BEFORE its remove) + audit/free-b-receipt-<ts>.json (summary).
#2454: nothing runs on import; `python free_b.py` is a DRY RUN that verifies and removes nothing, `--go` deletes. Every delete is one of three named paths of verified_remove.py:
  1) <m-root>/shards-v0 files that are sha256-identical duplicates of <m-root>/ember-data/shards-v0 (remove_dup: both hashed now, the duplicate must be a different file),
  2) upload/raw + upload/train files with a server copy (remove_verified: server entry read back NOW with size AND LFS sha256; an entry without an LFS sha256 is not accepted on size; the candidate HF paths come from a tree listing but the
     proof is the fresh per-file read),
  3) NO-COPY garbage (wiki .bad partials, the TextCaps source zip): ruled-no-copy only, ruling id required (--ruling, default none -> these two are skipped), manifest fsynced first, never labelled verified.
Python only; no rmtree; emptied directories go with os.rmdir."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_RAW_REPO, HF_TRAIN_REPO, M_ROOT
import os, sys, json, time, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verified_remove as VR

BS = chr(92); from lane_config import M_ROOT as B; DS = B + "/data-staging"
SHARDS_A = B + "/shards-v0"; SHARDS_B = B + "/ember-data/shards-v0"; UPLOAD = DS + "/upload"; AUDIT = DS + "/audit"
WIKI_PARTS = DS + "/wikipedia-20220501/parts"; TEXTCAPS_ZIP = DS + "/textcaps/train_val_images.zip"; TEXTCAPS_TRAIN = DS + "/textcaps/images/train"
REPOS = (("raw", ("wordingone/" + HF_RAW_REPO)), ("train", ("wordingone/" + HF_TRAIN_REPO)))
READER = None          # tests inject a fake server reader and a fake tree lister; production asks the Hub NOW for every file
TREE = None


def files(p):
    return {os.path.relpath(os.path.join(dp, f), p).replace(BS, "/"): os.path.join(dp, f) for dp, _, fs in os.walk(p) for f in fs}


def prune_empty(d):
    for dp, _, _ in sorted(os.walk(d), key=lambda x: -len(x[0])):
        try: os.rmdir(dp)
        except OSError: pass


def tree_paths(repo):
    if TREE is not None: return TREE(repo)
    from huggingface_hub import HfApi
    return [t.path for t in HfApi().list_repo_tree(repo, repo_type="dataset", recursive=True) if hasattr(t, "size")]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    go = "--go" in argv; ruling = argv[argv.index("--ruling") + 1] if "--ruling" in argv else None
    ts = time.strftime("%Y%m%d-%H%M%S"); os.makedirs(AUDIT, exist_ok=True); RC = f"{AUDIT}/free-b-receipts-{ts}.jsonl"; MAN = f"{AUDIT}/free-b-nocopy-manifest-{ts}.jsonl"
    reader = READER or VR.hub_reader()
    R = dict(ts=ts, mode=("GO" if go else "DRY"), deleted=[], skipped=[], free_before_gib=shutil.disk_usage("B:/").free / 2**30)

    def tally(path, res, why):
        if res["ok"]: R["deleted"].append(dict(path=path.replace(BS, "/"), bytes=res["bytes"], why=why))
        else: R["skipped"].append(f"{path.replace(BS, '/')}: {res['why']}")
    # 1) shards-v0 vs ember-data/shards-v0
    if os.path.isdir(SHARDS_A) and os.path.isdir(SHARDS_B):
        a = files(SHARDS_A); b = files(SHARDS_B)
        for k, p in sorted(a.items()):
            if k not in b: R["skipped"].append(f"{p.replace(BS, '/')}: no duplicate in {SHARDS_B}"); continue
            tally(p, VR.remove_dup(p, b[k], roots=[SHARDS_A], other_roots=[SHARDS_B], receipt=RC, authority="lead 81345", dry=not go), "sha256-identical duplicate of " + SHARDS_B + "/" + k)
        if go: prune_empty(SHARDS_A)
    # 2) upload/raw + upload/train with a server copy
    for sub, repo in REPOS:
        root = f"{UPLOAD}/{sub}"
        if not os.path.isdir(root): continue
        tp = tree_paths(repo)
        for rel, p in sorted(files(root).items()):
            cands = [k for k in tp if k.endswith("/" + rel) or k == rel]
            res = dict(ok=False, why="no candidate path on the server", bytes=0, size=0)
            for k in cands:
                res = VR.remove_verified(p, repo, k, roots=[root], receipt=RC, authority="lead 81345", reader=reader, dry=not go)
                if res["ok"]: break
            tally(p, res, f"server-verified on {repo}")
    # 3) no-copy garbage: ruled only
    garbage = []
    if os.path.isdir(WIKI_PARTS): garbage += [(WIKI_PARTS + "/" + f, WIKI_PARTS, "failed partial download (sha1 mismatch), superseded") for f in sorted(os.listdir(WIKI_PARTS)) if ".bad" in f]
    n = len(files(TEXTCAPS_TRAIN)) if os.path.isdir(TEXTCAPS_TRAIN) else 0
    if os.path.exists(TEXTCAPS_ZIP) and n >= 21953: garbage.append((TEXTCAPS_ZIP, os.path.dirname(TEXTCAPS_ZIP), f"re-downloadable public source zip; {n} train images already extracted"))
    if garbage and not ruling: R["skipped"] += [f"{g[0].replace(BS, '/')}: no copy exists, needs --ruling ID" for g in garbage]
    elif garbage:
        for p, root, why in garbage:
            if not go: R["deleted"].append(dict(path=p.replace(BS, "/"), bytes=os.path.getsize(p), why="DRY: " + why)); continue
            rows, refused = VR.ruled_manifest([p], MAN, ruling=ruling, note=why, roots=[root], require_nlink=1)
            if refused: R["skipped"].append(f"{p.replace(BS, '/')}: {refused[0][1]}"); continue
            tally(p, VR.remove_ruled(rows[0], roots=[root], receipt=RC, require_nlink=1), why)
    R["free_after_gib"] = shutil.disk_usage("B:/").free / 2**30; R["freed_gib"] = round(sum(d["bytes"] for d in R["deleted"]) / 2**30, 2)
    json.dump(R, open(f"{AUDIT}/free-b-receipt-{ts}.json", "w"), indent=1)
    print(json.dumps(dict(mode=R["mode"], freed_gib=R["freed_gib"], free_before=round(R["free_before_gib"], 1), free_after=round(R["free_after_gib"], 1), deleted=len(R["deleted"]), skipped=R["skipped"][:8]), indent=1))
    return R


if __name__ == "__main__":
    main()
