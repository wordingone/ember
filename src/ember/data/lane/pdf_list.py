# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, M_ROOT
import os, re, json
bases = [(M_ROOT + "/data/corpus"), (M_ROOT + "/ember-data/objects"), (M_ROOT + "/ember-data/raw"), (M_ROOT + "/ember-data/recovered-20260805"), (M_ROOT + "/ember-data/catalog-train-cache")]
dates = json.load(open((LANE_ROOT + "/audit/arxiv-dates.json")))
seen = {}; tot = 0; noid = 0
for r in bases:
    for dp, _, fs in os.walk(r):
        for f in fs:
            if not f.lower().endswith(".pdf"):
                continue
            tot += 1
            m = re.match(r"^(.+)v(\d+)\.pdf$", f)
            if not m:
                noid += 1
                continue
            aid, v = m.group(1), int(m.group(2))
            key = aid.replace("_", "/") if re.match(r"^[a-z\-]+(\.[A-Z]{2})?_\d{7}$", aid) else aid
            seen.setdefault((key, v), os.path.join(dp, f))
ok = []
stats = dict(total_pdf_files=tot, no_id=noid, unique_id_ver=len(seen), no_meta=0, listed=0, updated_le_split=0, later_versions_listed=0)   # no date wall (lead 83389): every version with OAI metadata is listed; content_date_max = created for v1, updated (an upper bound) for later versions, derived from the (created, updated) pair by arxiv_manifest (oai_created / oai_updated)
for (aid, v), p in seen.items():
    d = dates.get(aid)
    if d is None:
        stats["no_meta"] += 1
        continue
    created, updated = d
    stats["listed"] += 1
    if updated <= "2022-10-31": stats["updated_le_split"] += 1      # informational split only (the old pre-wall packs hold these), never an exclusion
    elif v != 1: stats["later_versions_listed"] += 1
    ok.append((aid, v, p, created, updated))
json.dump(ok, open((LANE_ROOT + "/audit/pdf-prewall-list.json"), "w"))
print(stats)
