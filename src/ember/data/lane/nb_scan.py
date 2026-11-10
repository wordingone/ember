# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Count notebook-looking blobs (JSON starting with a cells/metadata key and nbformat) in the local GitHub license partitions; READ-ONLY. Usage: nb_scan.py OUT.json"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import M_ROOT
import os, sys, json, re, glob
bases = glob.glob((M_ROOT + "/data/corpus/issue1719-*license*/*/blobs/sha256")) + glob.glob((M_ROOT + "/data/corpus/issue1719-license-partitions-*/*/blobs/sha256"))
res = dict(scanned=0, ipynb=0, ipynb_bytes=0, by_part={}, sample=[])
for r in sorted(set(bases)):
    part = r.replace(chr(92), "/").split("/corpus/")[1].split("/blobs")[0]; c = 0
    for dp, _, fs in os.walk(r):
        for f in fs:
            p = os.path.join(dp, f)
            try:
                with open(p, "rb") as fh: h = fh.read(400)
            except Exception: continue
            res["scanned"] += 1
            if re.match(rb'\s*\{\s*"(cells|metadata|nbformat)"', h) and (b'"cells"' in h or b'"nbformat"' in h):
                c += 1; res["ipynb"] += 1; res["ipynb_bytes"] += os.path.getsize(p)
                if len(res["sample"]) < 5: res["sample"].append(p.replace(chr(92), "/"))
    res["by_part"][part] = c
    json.dump(res, open(sys.argv[1], "w"), indent=1)
print(json.dumps(res))
