# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Commons v2 delta manifest: rows of commons-pilot/manifest.jsonl not already in the packed commons-human-v1 set (by origin). Usage: commons_finish.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import json
seen = set()
for l in open("A:/ember-stage/media-packed/commons-human-v1/index.jsonl", encoding="utf-8"): seen.add(json.loads(l).get("origin"))
n = 0
with open((LANE_ROOT + "/commons-pilot/manifest-v2.jsonl"), "w", encoding="utf-8") as f:
    for l in open((LANE_ROOT + "/commons-pilot/manifest.jsonl"), encoding="utf-8"):
        d = json.loads(l)
        if d["origin"] not in seen: f.write(l); n += 1
print("v2 delta rows", n)
