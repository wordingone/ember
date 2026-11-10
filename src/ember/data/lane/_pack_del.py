# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, hashlib, time
from huggingface_hub import HfApi
api = HfApi(); NAMES = sys.argv[2:]; AUTH = sys.argv[1]
ap = {i["name"]: i for i in json.load(open((LANE_ROOT + "/loops/approved-uploads.json")))}
M = (LANE_ROOT + "/logs/manifests-20261108/packed-drop-manifest.jsonl"); rows = []; bad = []
for n in NAMES:
    it = ap["train-" + n] if "train-" + n in ap else ap[n]; d = it["local"].rstrip("/"); repo = it["repo"]; base = it["path"].rstrip("/")
    tree = {t.path: t for t in api.list_repo_tree(repo, repo_type="dataset", path_in_repo=base, recursive=True) if hasattr(t, "size")}
    for dp, _, fs in os.walk(d):
        for f in fs:
            p = os.path.join(dp, f); s = os.stat(p)
            if s.st_nlink != 1 or s.st_size < (1 << 20): continue      # linked files and small metadata (intake/receipt/ledger) stay
            hp = base + "/" + os.path.relpath(p, d).replace(chr(92), "/"); h = hashlib.sha256()
            with open(p, "rb") as fh:
                for c in iter(lambda: fh.read(8 << 20), b""): h.update(c)
            t = tree.get(hp); rs = t.lfs.sha256 if t is not None and getattr(t, "lfs", None) else None
            if t is None or rs != h.hexdigest(): bad.append((p, t is not None)); continue
            rows.append(dict(set=n, path=p.replace(chr(92), "/"), size=s.st_size, sha256=h.hexdigest(), hf_repo=repo, hf_path=hp, nlink=1, authority=AUTH, ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
if bad: print("ABORT unverified:", bad[:5], len(bad)); raise SystemExit(1)
open(M, "a").write("".join(json.dumps(r) + "\n" for r in rows)); assert rows
print("MANIFEST", len(rows), "files", round(sum(r["size"] for r in rows) / 2**30, 2), "GiB; by set", {n: sum(1 for r in rows if r["set"] == n) for n in NAMES})
for r in rows: os.remove(r["path"])
print("DELETED", len(rows))
