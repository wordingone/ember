# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""filter_ids.py IN OUT_KEEP OUT_EXCL IDS.json KEYFIELD : split docs by membership of doc[KEYFIELD] in IDS.json keys."""
import sys, io, os, json, zstandard
IN, KEEP, EXCL, IDS, KEY = sys.argv[1:6]
ids = set(json.load(open(IDS)))
c = zstandard.ZstdCompressor(level=6); c2 = zstandard.ZstdCompressor(level=6); k = e = tk = te = 0
def _glog(m): print(m, file=sys.stderr, flush=True)      # wait lines go to stderr: stdout carries only the JSON stats line
import reserve_plan
IN_BYTES = os.path.getsize(IN); GATE_STEP = 512 << 20; next_gate = GATE_STEP
if not reserve_plan.write_gate("filter_ids.py out", IN_BYTES + (64 << 20), log=_glog):      # lead 82324 / lead 82669: every lane write path waits on the floor
    sys.exit("write_gate refused: B: below the reserve floor for the whole gate cap: filter_ids.py not writing")
# write to .part and rename on success: a refusal mid-stream never leaves a valid-looking partial at the final path
with open(IN, "rb") as f, open(KEEP + ".part", "wb") as fk, open(EXCL + ".part", "wb") as fe, c.stream_writer(fk) as wk, c2.stream_writer(fe) as we:
    for line in io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(f), encoding="utf-8"):
        if fk.tell() + fe.tell() >= next_gate:      # long stream: re-gate every 512 MiB written, for what is still to come
            done = fk.tell() + fe.tell()
            if not reserve_plan.write_gate("filter_ids.py out", max(IN_BYTES - done, 0) + (64 << 20), log=_glog):
                sys.exit("write_gate refused: B: below the reserve floor for the whole gate cap: filter_ids.py stopped mid-stream (only .part files exist)")
            next_gate = done + GATE_STEP
        d = json.loads(line)
        if d[KEY] in ids: we.write(line.encode()); e += 1; te += d["tokens"]
        else: wk.write(line.encode()); k += 1; tk += d["tokens"]
os.replace(KEEP + ".part", KEEP); os.replace(EXCL + ".part", EXCL)
print(json.dumps(dict(kept=k, kept_tokens=tk, excluded=e, excluded_tokens=te)))
