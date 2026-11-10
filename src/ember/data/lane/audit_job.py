# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# /// script
# dependencies = ["requests", "zstandard", "pyarrow", "py7zr", "huggingface_hub"]
# ///
"""One-time secret audit of the PUBLIC repo wordingone/ember-corpus as an HF Job (lead 81731). Value-free output only: path, size, hits{pattern:count}, scanned_bytes.
Never prints or stores a matched value. Results are written as NEW files audit/job/part-NNNN.jsonl in wordingone/<raw-repo> (never overwrites)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_RAW_REPO, LANE_ROOT
"""Secret-scan gate for PUBLIC uploads (lead 81676). Counts credential-shaped spans; NEVER prints or logs a matched value.
scan_path(path) -> {"hits": {pattern_name: count}, "scanned_bytes": n, "skipped": [...]}   (empty hits = clean)
Handles: plain text/jsonl/json/csv/md, .gz, .zst, .tar / .tar.gz / .tgz (recursive, nested archives too), .parquet (every string column).
Binary media (image/audio/video) and model-weight files are skipped (listed in "skipped") since credential strings in them are not text.
CLI: python secret_scan.py selftest | scan <path>        gate(path, lane, rp) -> True if clean; on a hit logs a value-free refusal row."""
import sys as _hs; _hs.path.insert(0, (LANE_ROOT + "/scripts")); import hf_push   # lead 82104: one funnel for HF writes
import os, sys, re, io, gzip, json, time, tarfile

PATTERNS = {
    "mongodb_uri": re.compile(rb"mongodb(?:\+srv)?://[^\s:/@\"'<>]{1,64}:[^\s@/\"'<>]{1,128}@"),
    "db_uri_with_password": re.compile(rb"\b(?:postgres(?:ql)?|mysql|mariadb|redis|rediss|amqps?)://[^\s:/@\"'<>]{1,64}:[^\s@/\"'<>]{1,128}@"),
    "aws_access_key": re.compile(rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "private_key_block": re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----"),
    "github_token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})\b"),
    "slack_token": re.compile(rb"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
    "generic_api_key_assignment": re.compile(rb"(?i)\bapi[_-]?key[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{20,}"),
}
LITERALS = {   # every match of the pattern must contain one of these (lowercase=True: compared against buf.lower())
    "mongodb_uri": ([b"mongodb"], False), "db_uri_with_password": ([b"://"], False), "aws_access_key": ([b"AKIA", b"ASIA"], False),
    "private_key_block": ([b"PRIVATE KEY"], False), "github_token": ([b"ghp_", b"gho_", b"ghu_", b"ghs_", b"ghr_", b"github_pat_"], False),
    "slack_token": ([b"xox"], False), "generic_api_key_assignment": ([b"api"], True),
}
def _count(buf, lt, hits):
    low = None
    for n, rx in PATTERNS.items():
        lits, ci = LITERALS[n]
        if ci:
            if low is None: low = buf.lower()
            if not any(l in low for l in lits): continue
        elif not any(l in buf for l in lits): continue
        c = sum(1 for m in rx.finditer(buf) if m.end() > lt)   # a match wholly inside the carried tail was already counted
        if c: hits[n] = hits.get(n, 0) + c
SKIP_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".mp3", ".flac", ".wav", ".ogg", ".opus", ".m4a", ".mp4", ".webm", ".mkv",
            ".safetensors", ".pt", ".pth", ".bin", ".gguf", ".ckpt", ".npy", ".npz", ".onnx", ".h5", ".pkl"}
OVERLAP = 512; CHUNK = 8 << 20   # lead 81677: chunks <= 64 MiB, overlap >= 256 B, one file at a time

def _scan_stream(fh, hits, tally):
    tail = b""
    while True:
        b = fh.read(CHUNK)
        if not b: break
        buf = tail + b; lt = len(tail)
        _count(buf, lt, hits)
        tally[0] += len(b); tail = buf[-OVERLAP:]

def _scan_parquet(fh_or_path, hits, tally, skipped, name):
    import pyarrow.parquet as pq, pyarrow as pa
    path = fh_or_path
    with open(path, "rb") as f:
        pf = pq.ParquetFile(f)
        cols = [c.name for c in pf.schema_arrow if pa.types.is_string(c.type) or pa.types.is_large_string(c.type)]
        if not cols: skipped.append(name + " (parquet: no string columns)"); return
        for b in pf.iter_batches(batch_size=8, columns=cols):   # small batches + one value at a time keeps RSS small (books are MBs each)
            for col in b.columns:
                for v in col.to_pylist():
                    if v: _scan_stream(io.BytesIO(v.encode("utf-8", "ignore")), hits, tally)

def _scan_fileobj(fh, name, hits, tally, skipped, depth=0):
    low = name.lower()
    ext = os.path.splitext(low)[1]
    if ext in SKIP_EXT: skipped.append(name); return
    if low.endswith((".tar.gz", ".tgz", ".tar")) or ext == ".tar":
        mode = "r|gz" if low.endswith((".tar.gz", ".tgz")) else "r|"
        with tarfile.open(fileobj=fh, mode=mode) as tf:
            for m in tf:
                if not m.isfile(): continue
                ex = tf.extractfile(m)
                if ex is None: continue
                _scan_fileobj(ex, m.name, hits, tally, skipped, depth + 1)
    elif ext == ".gz":
        with gzip.GzipFile(fileobj=fh) as g: _scan_fileobj(g, name[:-3], hits, tally, skipped, depth + 1)
    elif ext == ".zst":
        import zstandard
        with zstandard.ZstdDecompressor().stream_reader(fh) as z: _scan_fileobj(z, name[:-4], hits, tally, skipped, depth + 1)
    elif ext == ".parquet":
        # members of archives are streams: spool to a temp file next to the scratch dir, then read
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, dir=os.environ.get("SECRET_SCAN_TMP", None), suffix=".parquet") as t:
            while True:
                b = fh.read(CHUNK)
                if not b: break
                t.write(b)
            tp = t.name
        try:
            try: _scan_parquet(tp, hits, tally, skipped, name)
            except Exception as e:   # not a valid parquet (e.g. a test fixture inside a repo tarball): scan its raw bytes instead of failing the whole file
                skipped.append(name + " (parquet unreadable: raw-byte scan)")
                with open(tp, "rb") as rf: _scan_stream(rf, hits, tally)
        finally: os.remove(tp)
    else:
        _scan_stream(fh, hits, tally)

def scan_path(path):
    hits = {}; tally = [0]; skipped = []
    name = os.path.basename(path)
    if name.lower().endswith(".parquet"): _scan_parquet(path, hits, tally, skipped, name)
    else:
        with open(path, "rb") as fh: _scan_fileobj(fh, name, hits, tally, skipped)
    hits = {k: v for k, v in hits.items() if v > 0}
    return {"hits": hits, "scanned_bytes": tally[0], "skipped": skipped}

PLACEHOLDER = "<REDACTED_CREDENTIAL>"
KEYBLOCK = re.compile(rb"(?s)-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----.{0,8000}?-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----")
def redact(text, counts=None):
    """Train-ready redaction (lead 81693): every credential-shaped span -> PLACEHOLDER. Returns the new text; per-pattern counts are added to `counts` (a dict). Values are never returned or logged."""
    b = text.encode("utf-8", "surrogatepass") if isinstance(text, str) else text
    low = None; changed = False
    def sub(n, rx):
        nonlocal b, changed
        k = 0
        def rep(m):
            nonlocal k; k += 1; return PLACEHOLDER.encode()
        b2 = rx.sub(rep, b)
        if k:
            b = b2; changed = True
            if counts is not None: counts[n] = counts.get(n, 0) + k
    if b"PRIVATE KEY" in b: sub("private_key_block", KEYBLOCK)
    for n, rx in PATTERNS.items():
        lits, ci = LITERALS[n]
        if ci:
            low = b.lower()
            if not any(l in low for l in lits): continue
        elif not any(l in b for l in lits): continue
        sub(n, rx)
    return b.decode("utf-8", "surrogatepass") if changed else text


import threading, tempfile, requests, time as _t
from concurrent.futures import ThreadPoolExecutor
from huggingface_hub import HfApi
REPO = "wordingone/ember-corpus"; OUTREPO = ("wordingone/" + HF_RAW_REPO); TOKEN = os.environ.get("HF_TOKEN")
SKIP_PREFIX = ("checkpoints/", "tokens/", "avir-cli/")
DONE = set(json.loads(os.environ.get("DONE_PATHS", "[]")))
api = HfApi(token=TOKEN); rev = api.dataset_info(REPO).sha
def order(p):
    for i, pre in enumerate(("objects/", "acquisition/heldout/", "sources/", "staging/", "catalog/", "acquisition/train/")):
        if p.startswith(pre): return i
    return 9
files = [(t.path, t.size) for t in api.list_repo_tree(REPO, repo_type="dataset", recursive=True) if hasattr(t, "size")]
todo = sorted([f for f in files if not f[0].startswith(SKIP_PREFIX) and f[0] not in DONE], key=lambda f: (order(f[0]), f[0]))
print(f"{len(files)} files at {rev[:8]}; {len(todo)} to scan; {len(DONE)} already done locally", flush=True)
lock = threading.Lock(); buf = []; nflush = [0]; ndone = [0]; t0 = _t.time()
def flush(final=False):
    with lock:
        if not buf or (len(buf) < 25 and not final): return
        nflush[0] += 1; name = f"audit/job/part-{nflush[0]:04d}.jsonl"; data = (chr(10).join(json.dumps(r) for r in buf) + chr(10)).encode(); buf.clear()
    if os.environ.get("JOB_DRY"): print("DRY flush", name, len(data), "bytes", flush=True); return
    hf_push.upload_file(api, path_or_fileobj=data, path_in_repo=name, repo_id=OUTREPO, repo_type="dataset", commit_message="secret audit job: results part (value-free)")
def scan_7z(path):
    import py7zr
    hits = {}; tally = [0]
    with py7zr.SevenZipFile(path) as z:
        for name, bio in z.readall().items(): _scan_fileobj(bio, name, hits, tally, [])
    return {"hits": {k: v for k, v in hits.items() if v > 0}, "scanned_bytes": tally[0], "skipped": []}
def scan_remote(p):
    url = f"https://huggingface.co/datasets/{REPO}/resolve/{rev}/{p}"; last = None
    for attempt in range(4):
        try:
            hits = {}; tally = [0]; skipped = []
            with requests.get(url, stream=True, timeout=(30, 120), headers={"User-Agent": "ember-audit-job/1.0"}) as r:
                r.raise_for_status(); r.raw.decode_content = False
                if p.lower().endswith(".7z"):
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".7z") as t:
                        for c in r.iter_content(8 << 20): t.write(c)
                    try: return scan_7z(t.name)
                    finally: os.remove(t.name)
                _scan_fileobj(r.raw, os.path.basename(p), hits, tally, skipped)
            return {"hits": {k: v for k, v in hits.items() if v > 0}, "scanned_bytes": tally[0], "skipped": skipped}
        except Exception as e: last = e; _t.sleep(5 * (attempt + 1))
    raise last
def do(item):
    p, sz = item; row = dict(path=p, size=sz, rev=rev[:8], ts=_t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime()), source="hfjob")
    try:
        r = scan_remote(p); row.update(status="scanned", hits=r["hits"], scanned_bytes=r["scanned_bytes"], skipped_n=len(r["skipped"]))
    except Exception as e: row.update(status="error", err=f"{type(e).__name__} {str(e)[:100]}", hits={}, scanned_bytes=0)
    with lock: buf.append(row); ndone[0] += 1
    if row["hits"]: print("HIT", p, row["hits"], flush=True)
    if ndone[0] % 10 == 0: print(f"{ndone[0]}/{len(todo)} files, {round(_t.time()-t0)}s", flush=True)
    flush()
with ThreadPoolExecutor(2) as ex: list(ex.map(do, todo))
flush(final=True); print("AUDIT JOB DONE", ndone[0], "files", round(_t.time() - t0), "s", flush=True)
