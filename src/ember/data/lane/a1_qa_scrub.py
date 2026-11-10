# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Heldout sentence scrub of caption/QA text for rows in a1-v5 manifest (clean sources only: a-okvqa, ai2d, iconqa, scienceqa) - lead 81317. Report only (no rewrite).
Same normalisation as scrub.py: eligible sentence = >=8 words after lowercase+ws normalise; xxh64 vs full heldout index + wiki2M + arXiv heldout-PDF hashes."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, M_ROOT
import sys, re, json, collections, numpy as np, xxhash
IDX = [np.load(p, mmap_mode="r") for p in ((LANE_ROOT + "/heldout-index-full/heldout-sent-xxh64-full.npy"), (LANE_ROOT + "/heldout-index/wiki-heldout-2M.npy"), (LANE_ROOT + "/arxiv/heldout-pdf-sent-hashes.npy"))]
SPLIT = re.compile(r"((?<=[.!?])\s+|\n+)"); WS = re.compile(r"\s+")
def inidx(h):
    for a in IDX:
        i = int(np.searchsorted(a, h))
        if i < len(a) and int(a[i]) == h: return True
    return False
tot = collections.Counter(); hit = collections.Counter(); rows_hit = collections.Counter(); ex = {}
for l in open((M_ROOT + "/ember-data/custody/a1-v5-manifest/combined-train-manifest-v5-no-arxivqa.jsonl"), encoding="utf-8"):
    d = json.loads(l); ds = d["dataset_id"]
    if ds not in ("a-okvqa", "ai2d", "iconqa", "scienceqa"): continue
    tot[ds] += 1; el = hs = 0
    for s in SPLIT.split(d["caption"]):
        n = WS.sub(" ", s.lower()).strip()
        if n.count(" ") < 7: continue
        el += 1
        if inidx(xxhash.xxh64_intdigest(n)): hs += 1
    hit[ds] += hs
    if hs: rows_hit[ds] += 1; ex.setdefault(ds, d["caption"][:160])
    tot[ds + ":eligible"] += el
print(json.dumps(dict(rows=dict(tot), hit_sentences=dict(hit), rows_with_hit=dict(rows_hit), example=ex), indent=1))
