# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""List arXiv ids that appear in ANY heldout-named directory under the corpus bases (conservative id-level exclusion)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import M_ROOT
import os, re, json, collections
bases = [(M_ROOT + "/data/corpus"), (M_ROOT + "/ember-data/objects"), (M_ROOT + "/ember-data/raw"), (M_ROOT + "/ember-data/recovered-20260805"), (M_ROOT + "/ember-data/catalog-train-cache"), (M_ROOT + "/ember-data/custody")]
held = collections.defaultdict(set); other = set(); dirs = collections.Counter()
for r in bases:
    for dp, _, fs in os.walk(r):
        isheld = "heldout" in dp.lower().replace("\\", "/")
        for f in fs:
            m = re.match(r"^(.+)v(\d+)\.pdf$", f)
            if not m: continue
            aid = m.group(1); key = aid.replace("_", "/") if re.match(r"^[a-z\-]+(\.[A-Z]{2})?_\d{7}$", aid) else aid
            if isheld:
                held[key].add(dp.replace("\\", "/")); dirs[dp.replace("\\", "/")] += 1
            else: other.add(key)
json.dump({k: sorted(v) for k, v in held.items()}, open("audit/arxiv-heldout-ids.json", "w"))
print("heldout ids", len(held), "heldout pdf files", sum(dirs.values())); print(dirs.most_common(12))
print("ids in both heldout and non-heldout dirs", len(set(held) & other))
