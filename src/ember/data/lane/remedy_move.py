# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Remedy (lead 81687/81698): move public objects/ files that carry credential-shaped spans to PRIVATE, then delete them from public HEAD in ONE commit.
Phase 1 (known hits from audit/secret-audit.jsonl): H-heldout-2, H-heldout-1, B-heldout-2, K-heldout-2, H-train-2 -> copy, verify, ONE delete commit.
Phase 2: every other objects/ file is polled for its audit row; a hit -> same copy+verify -> a SECOND delete commit. Unread files are reported UNSCANNED, never clean.
Per file: Range-resumable stream download, sha256 == public LFS oid, upload to wordingone/ember-raw-private <heldout|train>/<name>, remote LFS sha256 == oid.
No history rewrite. Receipts: logs/remedy-move.json (phase 1), logs/remedy-move-2.json (phase 2). Names, sizes, oids, commit hash; no secret values."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import sys as _hs; _hs.path.insert(0, (LANE_ROOT + "/scripts")); import hf_push   # lead 82104: one funnel for HF writes
import os, sys, json, time, hashlib, requests, threading
from concurrent.futures import ThreadPoolExecutor
from huggingface_hub import HfApi, CommitOperationDelete
PUB = "wordingone/ember-corpus"; PRIV = "wordingone/ember-raw-private"; from lane_config import LANE_ROOT as ROOT; TMPD = ROOT + "/remedy"; os.makedirs(TMPD, exist_ok=True)
H = "objects/heldout/issue1719-"; T = "objects/train/issue1719-"
PHASE1 = [H + "license-partitions-wave10-20260819T0215Z__H-heldout-2.tar.gz", H + "github-license-partitions-20260818T0550Z__H-heldout-1.tar.gz",
          H + "license-partitions-wave10-20260819T0215Z__B-heldout-2.tar.gz", H + "license-partitions-wave10-20260819T0215Z__K-heldout-2.tar.gz",
          T + "github-license-partitions-20260818T0550Z__H-train-2.tar.gz"]
AUDIT = ROOT + "/audit/secret-audit.jsonl"
api = HfApi(); lock = threading.Lock()
def log(*a):
    with lock: print(time.strftime("%H:%M:%S"), *a, flush=True)
def dest_of(path):   # objects/heldout/x -> heldout/x ; objects/train/x -> train/x
    return path.split("/", 1)[1]
def copy_one(path):
    info = api.get_paths_info(PUB, [path], repo_type="dataset", expand=True)[0]; size = info.size; oid = info.lfs.sha256; name = os.path.basename(path)
    loc = f"{TMPD}/{name}"; dest = dest_of(path); short = name.split("__")[-1][:14]
    url = f"https://huggingface.co/datasets/{PUB}/resolve/main/{path}"; have = os.path.getsize(loc) if os.path.exists(loc) else 0
    while have < size:
        try:
            with requests.get(url, stream=True, timeout=(30, 90), headers={"Range": f"bytes={have}-", "User-Agent": "ember-remedy/1.0"}) as r:
                r.raise_for_status()
                with open(loc, "ab") as f:
                    for c in r.iter_content(4 << 20):
                        f.write(c); have += len(c)
        except Exception as e:
            log(short, "drop:", type(e).__name__, "resume at", have); time.sleep(5); have = os.path.getsize(loc)
        log(f"{short} downloaded {have/2**20:.0f}/{size/2**20:.0f} MiB")
    h = hashlib.sha256()
    with open(loc, "rb") as f:
        for c in iter(lambda: f.read(8 << 20), b""): h.update(c)
    if h.hexdigest() != oid: raise RuntimeError(f"{short} SHA MISMATCH; nothing uploaded or deleted")
    log(short, "download sha256 == public oid")
    ri = None
    try: ri = api.get_paths_info(PRIV, [dest], repo_type="dataset", expand=True)[0]
    except Exception: ri = None
    if not (ri is not None and ri.lfs and ri.lfs.sha256 == oid and ri.size == size):   # already verified in private on an earlier run -> skip the re-upload
        hf_push.upload_file(api, path_or_fileobj=loc, path_in_repo=dest, repo_id=PRIV, repo_type="dataset", commit_message=dest.split("/")[0] + "/: moved from public ember-corpus (third-party credentials found by secret scan; lead 81687/81698)")
        ri = api.get_paths_info(PRIV, [dest], repo_type="dataset", expand=True)[0]
    if not (ri.lfs and ri.lfs.sha256 == oid and ri.size == size): raise RuntimeError(f"{short} PRIVATE VERIFY FAILED")
    log(short, "private copy verified (LFS sha256 == public oid)")
    return dict(public_path=path, private_path=dest, bytes=size, sha256=oid)
def audit_rows():
    rows = {}
    if os.path.exists(AUDIT):
        for l in open(AUDIT, encoding="utf-8"):
            r = json.loads(l)
            if r.get("status") == "scanned": rows[r["path"]] = r
    return rows
def commit(done, rcpt, n):
    ops = [CommitOperationDelete(path_in_repo=d["public_path"]) for d in done]
    c = hf_push.create_commit(api, repo_id=PUB, repo_type="dataset", operations=ops, commit_message="Remove " + str(len(ops)) + " objects/ archive(s) from public HEAD: third-party credentials found by secret scan; moved to private (wordingone/ember-raw-private heldout/ and train/). History not rewritten.")
    json.dump(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), files=done, private_repo=PRIV, public_delete_commit=str(c.commit_url), commit_oid=c.oid), open(rcpt, "w"), indent=1)
    for d in done:
        try: os.remove(f"{TMPD}/{os.path.basename(d['public_path'])}")
        except OSError: pass
    log(f"DONE phase {n}", c.commit_url)
    return c

if os.path.exists(ROOT + "/logs/remedy-move.json"): log("phase 1 already committed; going to phase 2"); p1 = None
else:
    with ThreadPoolExecutor(3) as ex: done = list(ex.map(copy_one, PHASE1))
    p1 = commit(done, ROOT + "/logs/remedy-move.json", 1)

# ---- phase 2: every other objects/ file, polled for its audit row; a hit is copied AT ONCE, committed when no copy is in flight ----
rest = [t.path for t in api.list_repo_tree(PUB, repo_type="dataset", path_in_repo="objects", recursive=True) if hasattr(t, "size") and t.path not in PHASE1]
pending = set(rest); futs = {}; verified = []; ncommit = 0
if os.path.exists(ROOT + "/logs/remedy-move-2.json"): ncommit = 1
log(f"phase 2: waiting on audit rows for {len(pending)} other objects/ file(s)")
with ThreadPoolExecutor(2) as ex:
    while pending or futs or verified:
        rows = audit_rows()
        for p in list(pending):
            if p in rows:
                pending.discard(p)
                if rows[p]["hits"]: log("audit shows hits in", os.path.basename(p).split("__")[-1], "-> same remedy (copying now)"); futs[p] = ex.submit(copy_one, p)
                else: log("audit shows 0 hits in", os.path.basename(p).split("__")[-1], "-> stays public")
        for p in list(futs):
            if futs[p].done(): verified.append(futs.pop(p).result())
        if verified and not futs:       # nothing in flight: ONE delete commit for everything verified so far
            ncommit += 1; commit(verified, ROOT + f"/logs/remedy-move-{ncommit + 1}.json", ncommit + 1); verified = []
        if not pending and not futs and not verified: break
        time.sleep(30)
json.dump(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), note="phase 2 complete: all other objects/ files read"), open(ROOT + "/logs/remedy-move-final.json", "w"))
log("DONE phase 2: all other objects/ files read")
