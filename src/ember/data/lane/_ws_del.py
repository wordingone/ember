# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, json, hashlib, time, shutil
D = (LANE_ROOT + "/wikisource-20220501"); M = (LANE_ROOT + "/logs/manifests-20261108/wikisource-manifest.jsonl")
rows = []
for f in sorted(os.listdir(D)):
    p = D + "/" + f; h1 = hashlib.sha1(); h2 = hashlib.sha256()
    with open(p, "rb") as fh:
        for c in iter(lambda: fh.read(8 << 20), b""): h1.update(c); h2.update(c)
    rows.append(dict(path=p, size=os.path.getsize(p), sha1=h1.hexdigest(), sha256=h2.hexdigest(), archive_url="https://archive.org/download/enwikisource-20220501/enwikisource-20220501-pages-articles.xml.bz2" if f.endswith(".xml.bz2") else None,
        kind="raw dump" if f.endswith((".bz2", ".ok")) else "derived by scripts/wikisource_prep.py from the dump (regenerable after refetch)", note="deleted per lead 81781; refetch if we use it", ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
os.makedirs(os.path.dirname(M), exist_ok=True)
open(M, "w").write("".join(json.dumps(r) + "\n" for r in rows)); print("MANIFEST", len(rows), sum(r["size"] for r in rows))
for r in rows: os.remove(r["path"])
os.rmdir(D); print("DELETED", D)
