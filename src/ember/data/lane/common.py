# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Shared helpers for the ember data lane. Deterministic only: no learned models.
Overlap signature = xxh64 of normalized sentences/lines with >= MINW words, sampled 1/SAMP by hash."""
import re, numpy as np, xxhash
SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
WS = re.compile(r"\s+")
MINW = 8
import os
SAMP = int(os.environ.get('HS_SAMP','4'))
def gram_hashes(text):
    out = []
    for seg in SPLIT.split(text):
        seg = WS.sub(" ", seg.lower()).strip()
        if seg.count(" ") < MINW - 1:
            continue
        h = xxhash.xxh64_intdigest(seg)
        if h % SAMP == 0:
            out.append(h)
    return np.array(out, dtype=np.uint64) if out else np.empty(0, dtype=np.uint64)
def overlap(idx, hs):
    if hs.size == 0:
        return 0
    pos = np.searchsorted(idx, hs)
    pos[pos >= idx.size] = idx.size - 1
    return int((idx[pos] == hs).sum())
