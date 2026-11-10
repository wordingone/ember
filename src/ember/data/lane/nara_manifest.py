# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Build the pack_media manifest for the 8 local NARA Commons PD images. Usage: nara_manifest.py OUT.jsonl"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import M_ROOT
import json, glob, os, sys, hashlib
D = (M_ROOT + "/ember-data/raw/wikimedia-commons-pd/")
man = [json.loads(l) for l in open(D + "manifest.jsonl", encoding="utf-8")]
by = {}
for f in glob.glob(D + "File__*"):
    by[hashlib.sha256(open(f, "rb").read()).hexdigest().upper()] = f
n = 0
with open(sys.argv[1], "w", encoding="utf-8") as o:
    for m in man:
        f = by.get(m["sha256"])
        if not f:
            print("no file for", m["sha256"][:8]); continue
        t = os.path.basename(f)[6:].rsplit(".", 1)[0]
        o.write(json.dumps(dict(path=f.replace(chr(92), "/"), caption=t.replace("_", " "), licence=m["license"], origin=m["source_url"], fetch_date=m["fetched_ts"][:10])) + chr(10)); n += 1
print("rows", n)
