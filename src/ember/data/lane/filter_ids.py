# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""filter_ids.py IN OUT_KEEP OUT_EXCL IDS.json KEYFIELD : split docs by membership of doc[KEYFIELD] in IDS.json keys."""
import sys, io, os, json, zstandard
IN, KEEP, EXCL, IDS, KEY = sys.argv[1:6]
ids = set(json.load(open(IDS)))
c = zstandard.ZstdCompressor(level=6); c2 = zstandard.ZstdCompressor(level=6); k = e = tk = te = 0
import reserve_plan; assert reserve_plan.write_gate("filter_ids.py out", os.path.getsize(IN) + (64 << 20)), "B: below the reserve floor for the whole gate cap: not writing"      # lead 82324 / lead 82669: every lane write path waits on the floor
with open(IN, "rb") as f, open(KEEP, "wb") as fk, open(EXCL, "wb") as fe, c.stream_writer(fk) as wk, c2.stream_writer(fe) as we:
    for line in io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(f), encoding="utf-8"):
        d = json.loads(line)
        if d[KEY] in ids: we.write(line.encode()); e += 1; te += d["tokens"]
        else: wk.write(line.encode()); k += 1; tk += d["tokens"]
print(json.dumps(dict(kept=k, kept_tokens=tk, excluded=e, excluded_tokens=te)))
