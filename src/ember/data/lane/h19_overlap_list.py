# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, io, psutil, zstandard as z
psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
try: psutil.Process().ionice(psutil.IOPRIO_VERYLOW)
except Exception: pass
RT = 1085721231
MAPS = ["A:/ember-staging/h19-percatalog-20261004/file3-article-map-v1.jsonl", "A:/ember-staging/h19-percatalog-20261004/file4-article-map-v1.jsonl", "A:/ember-staging/h19-percatalog-20261004/file5-article-map-v1.jsonl", "A:/ember-staging/h19-percatalog-files6-10-v2-20261004T190306Z/file6-article-map-v1.jsonl"]
h19 = {}
for i, pth in enumerate(MAPS):
    for l in open(pth, encoding="utf-8"):
        d = json.loads(l); h19[str(d["id"])] = (3 + i, int(d["ver"]))
packs = sorted(n for n in os.listdir((LANE_ROOT + "/packed")) if n.startswith("wikipedia-20220501-") and not n.endswith(".jsonl") and not n.endswith("-r1"))
out = open((LANE_ROOT + "/audit/h19-overlap-exclude-proposal.jsonl"), "w", encoding="utf-8"); n = 0
for b in packs:
    pk = b + "-r1" if os.path.isdir(f"{LANE_ROOT}/packed/{b}-r1") else b
    for l in io.TextIOWrapper(z.ZstdDecompressor().stream_reader(open(f"{LANE_ROOT}/packed/{pk}/docs-index.jsonl.zst", "rb")), encoding="utf-8"):
        if not l.strip(): continue
        d = json.loads(l); h = h19.get(str(d["id"]))
        if h: out.write(json.dumps(dict(pack=pk, base_pack=b, id=str(d["id"]), object_index=d["object_index"], tokens=d["token_end"] - d["token_start"], h19_file=h[0], h19_rev=h[1], cls="same_revision" if h[1] <= RT else "later_revision")) + "\n"); n += 1
out.close(); print("rows", n)
