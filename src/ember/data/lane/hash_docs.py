# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""hash_docs.py IN.jsonl.zst OUT.npy : sorted unique uint64 xxh64 hashes of eligible sentences (scrub.py segmenter) of all docs."""
import sys, io, re, json, numpy as np, xxhash, zstandard
SPLIT = re.compile(r"((?<=[.!?])\s+|\n+)"); WS = re.compile(r"\s+")
hs = []
for line in io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(open(sys.argv[1], "rb")), encoding="utf-8"):
    for s in SPLIT.split(json.loads(line)["text"])[0::2]:
        n = WS.sub(" ", s.lower()).strip()
        if n.count(" ") >= 7: hs.append(xxhash.xxh64_intdigest(n))
H = np.unique(np.array(hs, dtype=np.uint64)); np.save(sys.argv[2], H); print(H.size)
