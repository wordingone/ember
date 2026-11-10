# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Pack final docs (jsonl.zst) into training's training-intake form (lead 81165 / training 81162).
Usage: pack.py OUTDIR NAME IN1.jsonl.zst [IN2 ...]
Writes under OUTDIR/NAME/:
  shards/v1-{idx:05d}-{sha12}.bin   uint16 LE token stream, 4,194,304-token slices, id 0 separator after EVERY doc
  objects/{NAME}-{k:04d}.jsonl.zst  source objects (<= PART_TOK tokens each), immutable, sha256 recorded
  ledger.jsonl                      ember-catalog-train-shard-ledger-v1 CANDIDATE rows (batch-local offsets from 0; training rebases+appends)
  docs-index.jsonl.zst              per doc: id, object_index, token_start, token_end (batch-local, separator included)
  receipt.json                      counts, tokenizer sha, dataset id
Tokenizer: custody 2c557e7f, no special-token insertion; docs whose text encodes to id 0 are dropped (counted). No model anywhere."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import M_ROOT
import os, sys, io, json, hashlib, array, time
os.environ.setdefault("RAYON_NUM_THREADS", "4")
import zstandard
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import secret_scan   # lead 81693: every train-ready pack is secret-redacted; counts per pattern go in receipt.json (never values)
from tokenizers import Tokenizer
OUT, NAME, INS = sys.argv[1], sys.argv[2], sys.argv[3:]
S = 4194304; PART_TOK = 40_000_000
TOKP = (M_ROOT + "/custody-tokenizer-2c557/tokenizer-2c557.json")
tk = Tokenizer.from_file(TOKP)
base = os.path.join(OUT, NAME)
for d in ("shards", "objects"): os.makedirs(os.path.join(base, d), exist_ok=True)

def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()

def docs():
    for p in INS:
        with open(p, "rb") as f:
            r = io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(f), encoding="utf-8")
            for line in r: yield json.loads(line)

cctx = zstandard.ZstdCompressor(level=6)
parts = []                       # dicts: sha256, token_start, token_end, path
docidx = open(os.path.join(base, "docs-index.jsonl"), "w", encoding="utf-8")
red_counts = {}; red_docs = 0
buf = array.array("H"); shard_idx = 0; total = 0; sep = 0; dropped0 = 0; ndocs = 0
shard_rows = []                  # (name, sha, n_tokens)
cur = None                       # current part state
def open_part():
    k = len(parts)
    p = os.path.join(base, "objects", f"{NAME}-{k:04d}.jsonl.zst")
    fo = open(p, "wb"); w = cctx.stream_writer(fo)
    return dict(k=k, path=p, fo=fo, w=w, start=total)
def close_part(c):
    c["w"].close(); c["fo"].close()
    parts.append(dict(path=c["path"], token_start=c["start"], token_end=total, sha256=sha_file(c["path"])))
def flush_shards(final=False):
    global buf, shard_idx
    while len(buf) >= S or (final and len(buf) > 0):
        chunk = buf[:S]; buf = buf[S:]
        import reserve_plan; assert reserve_plan.write_gate("pack.py shard", len(chunk) * 2 + (64 << 20)), "B: below the reserve floor for the whole gate cap: not writing"      # lead 82324: every lane write path waits on the floor
        tmp = os.path.join(base, "shards", "tmp.bin")
        with open(tmp, "wb") as f: chunk.tofile(f)
        sha = sha_file(tmp); name = f"v1-{shard_idx:05d}-{sha[:12]}.bin"
        os.replace(tmp, os.path.join(base, "shards", name))
        shard_rows.append((name, sha, len(chunk))); shard_idx += 1
        if final and len(buf) == 0: break

t0 = time.time(); B = []
def process(batch):
    global total, sep, dropped0, ndocs, cur, red_docs
    for d in batch:
        c0 = sum(red_counts.values()); d["text"] = secret_scan.redact(d["text"], red_counts)
        if sum(red_counts.values()) > c0: red_docs += 1
    encs = tk.encode_batch([d["text"] for d in batch], add_special_tokens=False)
    for d, e in zip(batch, encs):
        ids = e.ids
        if 0 in ids: dropped0 += 1; continue
        if cur is None: cur = open_part()
        cur["w"].write((json.dumps({k: v for k, v in d.items()}, ensure_ascii=False) + "\n").encode())
        n = len(ids) + 1
        docidx.write(json.dumps(dict(id=d.get("id"), object_index=cur["k"], token_start=total, token_end=total + n)) + "\n")
        buf.extend(ids); buf.append(0); total += n; sep += 1; ndocs += 1
        if len(buf) >= S: flush_shards()
        if total - cur["start"] >= PART_TOK: close_part(cur); cur = None
for d in docs():
    B.append(d)
    if len(B) >= 256: process(B); B = []
    if ndocs and ndocs % 5000 == 0: print(ndocs, total, round(time.time() - t0), flush=True)
if B: process(B)
if cur is not None: close_part(cur)
flush_shards(final=True)
docidx.close()
# compress docs-index
with open(os.path.join(base, "docs-index.jsonl"), "rb") as f, open(os.path.join(base, "docs-index.jsonl.zst"), "wb") as fo:
    cctx.copy_stream(f, fo)
os.remove(os.path.join(base, "docs-index.jsonl"))

# ledger rows
rows = []; prev = "0" * 64
for i, (name, sha, n) in enumerate(shard_rows):
    a, b = i * S, i * S + n
    spans = []; last_k = None
    for k, p in enumerate(parts):
        lo, hi = max(a, p["token_start"]), min(b, p["token_end"])
        if lo < hi: spans.append(dict(sha256=p["sha256"], token_start=lo, token_end=hi)); last_k = k
    p = parts[last_k]
    if b < p["token_end"]: res = dict(object_index=last_k, carry_tokens=b - max(a, p["token_start"]))
    else: res = dict(object_index=last_k + 1, carry_tokens=0)
    row = dict(index=i, n_tokens=n, name=name, prev_row_sha256=prev, resume=res, schema_version="ember-catalog-train-shard-ledger-v1", sha256=sha, spans=spans)
    row["row_sha256"] = hashlib.sha256(json.dumps({k: v for k, v in row.items() if k != "row_sha256"}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    prev = row["row_sha256"]; rows.append(row)
with open(os.path.join(base, "ledger.jsonl"), "w", encoding="utf-8") as f:
    for r in rows: f.write(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n")
dsid = hashlib.sha256("\n".join(sorted(p["sha256"] for p in parts)).encode()).hexdigest()
rec = dict(name=NAME, docs=ndocs, total_tokens=total, separator_tokens=sep, content_tokens=total - sep, docs_dropped_text_encodes_to_id0=dropped0,
           shards=len(shard_rows), objects=[dict(index=k, name=os.path.basename(p["path"]), sha256=p["sha256"], token_start=p["token_start"], token_end=p["token_end"], bytes=os.path.getsize(p["path"])) for k, p in enumerate(parts)],
           tokenizer_sha256=sha_file(TOKP), tokenizer_path=TOKP, stream_format="token-shards-v0 little-endian uint16; doc-boundary separator id 0 writer-inserted",
           secret_redaction=dict(placeholder=secret_scan.PLACEHOLDER, spans_by_pattern=red_counts, spans_total=sum(red_counts.values()), docs_with_redactions=red_docs, scanner="scripts/secret_scan.py redact()"), shard_tokens=S, dataset_id=f"dataset:{NAME}:{dsid}", inputs=INS, secs=round(time.time() - t0))
json.dump(rec, open(os.path.join(base, "receipt.json"), "w"), indent=1)
print(json.dumps({k: v for k, v in rec.items() if k != "objects"}))
