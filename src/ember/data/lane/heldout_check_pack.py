# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Heldout re-check of ONE pack with UNSAMPLED sentence hashes (HS_SAMP=1) against the full heldout index + wiki-heldout-2M + arxiv heldout. Usage: heldout_check_pack.py PACKNAME [MAXDOCS]. Prints docs/hit docs/hit sentences; exit 0 only if 0 hits."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys; os.environ["HS_SAMP"] = "1"
pass
import numpy as np, overlap_gate as G
from common import gram_hashes, overlap
name = sys.argv[1]; mx = int(sys.argv[2]) if len(sys.argv) > 2 else 10**9
_P = os.environ["HC_INDEX"].split(os.pathsep) if os.environ.get("HC_INDEX") else [(LANE_ROOT + "/heldout-index-full/heldout-sent-xxh64-full.npy"), (LANE_ROOT + "/heldout-index/wiki-heldout-2M.npy"), (LANE_ROOT + "/arxiv/heldout-pdf-sent-hashes.npy")]      # HC_INDEX / HC_PACK_ROOT: test overrides only (pack_gates red); production uses the defaults
IDX = [np.load(p, mmap_mode="r") for p in _P]
n = hd = hs = 0
for r in G.iter_objects(os.environ.get("HC_PACK_ROOT", (LANE_ROOT + "/packed")) + "/" + name):
    n += 1; h = gram_hashes(r["text"]); o = sum(overlap(i, h) for i in IDX)
    if o: hd += 1; hs += o
    if n >= mx: break
print(name, "docs", n, "hit_docs", hd, "hit_sentences", hs, "ERROR(no documents)" if n == 0 else ("PASS" if hd == 0 else "FAIL")); sys.exit(2 if n == 0 else (0 if hd == 0 else 1))      # a pack with no documents proves nothing: exit 2 (error, never a pass); #2478 review
