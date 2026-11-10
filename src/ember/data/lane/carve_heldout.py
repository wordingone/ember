# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""carve_heldout.py IN OUT_TRAIN OUT_HELD TARGET_TOKENS : deterministic heldout carve. Docs ordered by sha256 of doc text (field 'sha'), first docs
until >= TARGET_TOKENS go to HELD, the rest to TRAIN. Prints counts and sha256 of both outputs (freeze)."""
import sys, os, io, json, hashlib, zstandard
IN, TR, HE, T = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
docs = []
for line in io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(open(IN, "rb")), encoding="utf-8"):
    d = json.loads(line); docs.append((d.get("sha") or hashlib.sha256(d["text"].encode()).hexdigest(), line, d["tokens"], d["id"]))
docs.sort(key=lambda x: x[0]); held = set(); t = 0
for sha, line, n, i in docs:
    if t >= T: break
    held.add(i); t += n
c1 = zstandard.ZstdCompressor(level=6); c2 = zstandard.ZstdCompressor(level=6); ntr = 0; ttr = 0
def _glog(m): print(m, file=sys.stderr, flush=True)      # wait lines go to stderr: stdout carries only the JSON stats line
import reserve_plan
IN_BYTES = os.path.getsize(IN); GATE_STEP = 512 << 20; next_gate = GATE_STEP
if not reserve_plan.write_gate("carve_heldout.py out", IN_BYTES + (64 << 20), log=_glog):      # lead 82324 / lead 82669: every lane write path waits on the floor
    sys.exit("write_gate refused: B: below the reserve floor for the whole gate cap: carve_heldout.py not writing")
# write to .part and rename on success: a refusal mid-stream never leaves a valid-looking partial at the final path
with open(TR + ".part", "wb") as f1, open(HE + ".part", "wb") as f2, c1.stream_writer(f1) as w1, c2.stream_writer(f2) as w2:
    for sha, line, n, i in docs:
        if f1.tell() + f2.tell() >= next_gate:      # long stream: re-gate every 512 MiB written, for what is still to come
            done = f1.tell() + f2.tell()
            if not reserve_plan.write_gate("carve_heldout.py out", max(IN_BYTES - done, 0) + (64 << 20), log=_glog):
                sys.exit("write_gate refused: B: below the reserve floor for the whole gate cap: carve_heldout.py stopped mid-stream (only .part files exist)")
            next_gate = done + GATE_STEP
        if i in held: w2.write(line.encode())
        else: w1.write(line.encode()); ntr += 1; ttr += n
os.replace(TR + ".part", TR); os.replace(HE + ".part", HE)
def sh(p):
    h = hashlib.sha256()
    for b in iter(lambda: open(p, "rb").read(), b""): h.update(b); break
    return h.hexdigest()
def shf(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()
print(json.dumps(dict(held_docs=len(held), held_tokens=t, train_docs=ntr, train_tokens=ttr, held_sha256=shf(HE), train_sha256=shf(TR))))
