# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Secret-scan gate for PUBLIC uploads (lead 81676). Counts credential-shaped spans; NEVER prints or logs a matched value.
scan_path(path) -> {"hits": {pattern_name: count}, "scanned_bytes": n, "skipped": [...]}   (empty hits = clean)
Handles: plain text/jsonl/json/csv/md, .gz, .zst, .tar / .tar.gz / .tgz (recursive, nested archives too), .parquet (every string column).
Binary media (image/audio/video) and model-weight files are skipped (listed in "skipped") since credential strings in them are not text.
CLI: python secret_scan.py selftest | scan <path>        gate(path, lane, rp) -> True if clean; on a hit logs a value-free refusal row."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, re, io, gzip, json, time, tarfile

PATTERNS = {
    "mongodb_uri": re.compile(rb"mongodb(?:\+srv)?://[^\s:/@\"'<>]{1,64}:[^\s@/\"'<>]{1,128}@"),
    "db_uri_with_password": re.compile(rb"\b(?:postgres(?:ql)?|mysql|mariadb|redis|rediss|amqps?)://[^\s:/@\"'<>]{1,64}:[^\s@/\"'<>]{1,128}@"),
    "aws_access_key": re.compile(rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "private_key_block": re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----"),
    "github_token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})\b"),
    "slack_token": re.compile(rb"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
    "generic_api_key_assignment": re.compile(rb"(?i)\bapi[_-]?key[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{20,}"),
    # operator 2026-11-09 (HF alert: ftp cred in pubmed objects): ANY scheme://user:pass@host. Scheme and host stay, only the credential becomes the placeholder.
    "scheme_userpass_uri": re.compile(rb"(?<=://)[^\s:/@\"'<>\[\]()]{1,64}:[^\s@/\"'<>\[\]()]{1,128}(?=@[A-Za-z0-9\[])"),
}
LITERALS = {   # every match of the pattern must contain one of these (lowercase=True: compared against buf.lower())
    "mongodb_uri": ([b"mongodb"], False), "db_uri_with_password": ([b"://"], False), "aws_access_key": ([b"AKIA", b"ASIA"], False),
    "private_key_block": ([b"PRIVATE KEY"], False), "github_token": ([b"ghp_", b"gho_", b"ghu_", b"ghs_", b"ghr_", b"github_pat_"], False),
    "slack_token": ([b"xox"], False), "generic_api_key_assignment": ([b"api"], True), "scheme_userpass_uri": ([b"://"], False),
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

REFUSALS = (LANE_ROOT + "/logs/secret-refusals.jsonl")
def gate(path, lane, rp):
    """True = clean. On a hit: value-free refusal row, returns False (caller must NOT upload)."""
    r = scan_path(path)
    if r["hits"]:
        with open(REFUSALS, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), lane=lane, hf_path=rp, local=os.path.basename(path), hits=r["hits"])) + "\n")
        return False
    if os.environ.get("SECRET_SCAN_NO_TH") == "1": return True      # selftest of the regex layer only; production never sets this
    import th_gate      # operator / lead 81934: HF scans with TruffleHog, so we run it too, pre-upload, FAIL-CLOSED (a hit or a scanner error => refuse)
    return th_gate.gate([path], lane, rp)

def selftest():
    os.environ["SECRET_SCAN_NO_TH"] = "1"
    import tempfile, subprocess, shutil
    d = tempfile.mkdtemp(); ok = True
    def chk(n, cond):
        nonlocal ok; print(("PASS " if cond else "FAIL ") + n); ok &= bool(cond)
    fake_mongo = b"conn = 'mongodb+srv://" + b"fakeuser:fakepass123" + b"@cluster0.example.invalid/db'\n"      # fixture built by concatenation so a repo secret scan does not flag this file
    fake_aws = b"key=" + b"AKIA" + b"ABCDEFGHIJKLMNOP" + b"\n"
    clean = b"The quick brown fox. mongodb is a database. user@example.com\n" * 1000
    def w(name, data):
        p = os.path.join(d, name); open(p, "wb").write(data); return p
    chk("clean text passes", scan_path(w("c.txt", clean))["hits"] == {})
    chk("planted mongodb URI refused (plain)", scan_path(w("m.jsonl", clean + fake_mongo + clean))["hits"].get("mongodb_uri") == 1)
    chk("planted AWS key refused", scan_path(w("a.txt", fake_aws))["hits"].get("aws_access_key") == 1)
    fake_ftp = b"mirror ftp://" + b"anonuser:S3cretPass99" + b"@ftp.example-host.invalid/pub/\n"
    chk("planted ftp://user:pass@ refused (operator 2026-11-09 HF alert class)", scan_path(w("f.txt", clean + fake_ftp))["hits"].get("scheme_userpass_uri") == 1)
    chk("ftp credential redacted, scheme+host kept", redact(fake_ftp.decode()).startswith("mirror ftp://" + PLACEHOLDER + "@ftp.example-host.invalid"))
    # tar.gz containing a jsonl with the secret (the shape HF flagged)
    inner = w("inner.jsonl", clean + fake_mongo)
    tgz = os.path.join(d, "x.tar.gz")
    with tarfile.open(tgz, "w:gz") as tf: tf.add(inner, arcname="objects/a.jsonl"); tf.add(w("clean2.txt", clean), arcname="objects/b.txt")
    chk("planted URI inside .tar.gz refused", scan_path(tgz)["hits"].get("mongodb_uri") == 1)
    # zstd member inside a plain tar
    import zstandard
    zp = os.path.join(d, "o.jsonl.zst"); open(zp, "wb").write(zstandard.ZstdCompressor().compress(clean + fake_mongo))
    tp = os.path.join(d, "y.tar")
    with tarfile.open(tp, "w") as tf: tf.add(zp, arcname="o.jsonl.zst")
    chk("planted URI inside zstd inside .tar refused", scan_path(tp)["hits"].get("mongodb_uri") == 1)
    # parquet string column
    import pyarrow as pa, pyarrow.parquet as pq
    pq_ = os.path.join(d, "t.parquet"); pq.write_table(pa.table({"text": ["hello", "x " + fake_mongo.decode()], "n": [1, 2]}), pq_)
    chk("planted URI in parquet text refused", scan_path(pq_)["hits"].get("mongodb_uri") == 1)
    # straddling a chunk boundary must be found exactly once
    global CHUNK
    old = CHUNK; CHUNK = 1000
    pad = b"x" * (1000 - 20)
    chk("URI straddling a chunk boundary counted once", scan_path(w("s.txt", pad + fake_mongo + b"y" * 3000))["hits"].get("mongodb_uri") == 1)
    CHUNK = old
    # images skipped, not scanned
    r = scan_path(w("i.jpg", fake_mongo)); chk("binary media skipped", r["hits"] == {} and r["skipped"] == ["i.jpg"])
    # gate: refusal row holds no value
    global REFUSALS
    REFUSALS = os.path.join(d, "ref.jsonl"); g = gate(w("g.txt", fake_mongo), "test", "sources/x/g.txt")
    row = open(REFUSALS).read()
    chk("gate refuses and log row contains no secret value", g is False and b"fakepass123" not in row.encode() and "mongodb_uri" in row)
    chk("gate passes clean", gate(w("g2.txt", clean), "test", "x") is True)
    shutil.rmtree(d, ignore_errors=True)
    print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest": selftest()
    elif len(sys.argv) > 2 and sys.argv[1] == "scan": print(json.dumps(scan_path(sys.argv[2])))
