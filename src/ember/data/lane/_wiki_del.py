# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, json, hashlib, time
D = (LANE_ROOT + "/wikipedia-20220501"); M = (LANE_ROOT + "/logs/manifests-20261108/wikipedia-20220501-manifest.jsonl")
KEEP = {"v-heldout-2M.jsonl.zst", "pilot-2000.jsonl.zst", "meta-enwiki-20220501.json"}   # heldout split + provenance + pilot sample stay
rows = []
for f in sorted(os.listdir(D)):
    p = D + "/" + f
    if not os.path.isfile(p) or os.path.getsize(p) < 10000 or f in KEEP: continue
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for c in iter(lambda: fh.read(8 << 20), b""): h.update(c)
    raw = f.endswith(".bz2")
    rows.append(dict(path=p, size=os.path.getsize(p), sha256=h.hexdigest(), mtime=time.strftime("%Y-%m-%d", time.gmtime(os.path.getmtime(p))),
        kind=("raw dump slice (dumps.wikimedia.org enwiki 20220501 multistream2 p41243p151573)" if f.startswith("enwiki") else "verification copy of the dump slice" if f.startswith("verified") else "derived intermediate of the wikipedia pack pipeline (regenerable; packed/wikipedia-20220501-* + HF hold the result)"),
        authority="lead 81853", ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
os.makedirs(os.path.dirname(M), exist_ok=True); open(M, "w").write("".join(json.dumps(r) + "\n" for r in rows))
print("MANIFEST", len(rows), "files", sum(r["size"] for r in rows) / 2**30, "GiB")
assert os.path.getsize(M) > 0
for r in rows: os.remove(r["path"])
print("DELETED", len(rows))
