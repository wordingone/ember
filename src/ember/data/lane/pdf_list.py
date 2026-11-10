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
stats = dict(total_pdf_files=tot, no_id=noid, unique_id_ver=len(seen), no_meta=0, pre_all=0, pre_v1_only=0, post=0)
for (aid, v), p in seen.items():
    d = dates.get(aid)
    if d is None:
        stats["no_meta"] += 1
        continue
    created, updated = d
    if updated <= "2022-10-31":
        stats["pre_all"] += 1
        ok.append((aid, v, p, created, updated))
    elif v == 1 and created <= "2022-10-31":
        stats["pre_v1_only"] += 1
        ok.append((aid, v, p, created, updated))
    else:
        stats["post"] += 1
json.dump(ok, open((LANE_ROOT + "/audit/pdf-prewall-list.json"), "w"))
print(stats)
