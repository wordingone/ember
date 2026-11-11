# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TruffleHog pre-upload gate (operator / lead 81934): HF scans every pushed file with TruffleHog, so our gate runs the SAME detector set before anything leaves the PC, FAIL-CLOSED
(missing binary, crash, timeout, unreadable file => refuse). Values are never logged: only detector name + count (+ file) reach any log/mail.
scan_files(paths) -> {"hits": {detector: n}, "files": {path: {detector: n}}}   raises ThError when the scanner could not run.
find_values(path) -> [raw secret strings] IN MEMORY ONLY, for th_redact (callers must not print/log them).
Prep: .zst / .parquet are expanded to plain text under SCRATCH (A:/data-scan/scratch, env TH_SCRATCH; TruffleHog does not decode them); .gz/.tar/.tar.gz/.zip go straight to its archive handlers.
Batching (coordinator rulings 82972/82974): the cost of a scan is TruffleHog PROCESS START (6.0 s/part one process per part, 1.19 s/part with one process over 8 parts, 0.61 over 32), not CPU, so parts are grouped
into batches of <= BATCH_PARTS parts and <= BATCH_MB MB, ONE process per batch, up to WORKERS (<= 4) batches in flight on CPUs 8-15. Every batch fails closed: a hit is attributed part -> source file through
the batch's owner map, and a hit whose file is not in the map is an ERROR, never "?".
Run:  python th_gate.py selftest | scan <path>"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, subprocess, time, tempfile, shutil, threading, queue

HERE = os.path.dirname(os.path.abspath(__file__))
TH = os.environ.get("TH_BIN", (LANE_ROOT + "/tools/trufflehog/trufflehog.exe"))
SCRATCH = os.environ.get("TH_SCRATCH", "A:/data-scan/scratch")      # scratch lives on A: (never B:): B: is the training run's disk
A_FLOOR_GIB = 20.0      # scratch writes wait while A: free < this + the bytes to be written
GATE_CAP_S = 6 * 3600   # bounded wait of the scratch gate; on expiry the scan FAILS CLOSED
GATE_POLL_S = 30
PART_MB = 8      # TruffleHog 3.99.8 dies silently (rc=1, mid-scan) on 63 MB parts 100% of the time and on 20 MB parts ~50%; 2 MB and 8 MB parts passed 16/16 (2026-11-10)
BATCH_PARTS = int(os.environ.get("TH_BATCH_PARTS", "32"))      # K: parts per TruffleHog process (measured 6.0 -> 0.61 s/part at K=32; 0.70 at K=128)
BATCH_MB = int(os.environ.get("TH_BATCH_MB", "256"))           # ... and at most this many MB per batch
WORKERS = min(4, int(os.environ.get("TH_WORKERS", "4")))       # TruffleHog processes at once (hard cap 4); also the cap on batches queued/in flight
MAX_ATTEMPTS = 8       # TruffleHog 3.99.8 exits rc=1 on ~half of runs (see _run); every attempt must fail before the batch is refused
CPUS = list(range(8, 16))      # lane work stays on CPUs 8-15 (best effort)
RESULTS = "verified,unverified,unknown,filtered_unverified"      # --no-verification: nothing is sent to any third party; HF reports unverified hits too
SKIP_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".mp3", ".flac", ".wav", ".ogg", ".opus", ".m4a", ".mp4", ".webm", ".mkv",
            ".safetensors", ".pt", ".pth", ".bin", ".gguf", ".ckpt", ".npy", ".npz", ".onnx", ".h5", ".pkl"}
REFUSALS = (LANE_ROOT + "/logs/secret-refusals.jsonl")


class ThError(Exception):
    pass


def _free_gib(path):
    """Free GiB of the drive that holds `path` (the scratch dir: A:, never B:)."""
    return shutil.disk_usage(path).free / 2**30


def _gate(what, need_bytes, d):
    """Scratch write gate: wait (bounded, poll GATE_POLL_S) while A: free - need < A_FLOOR_GIB; on cap expiry ThError (fail closed). It looks at the SCRATCH drive only and never at what a path holds."""
    sys.path.insert(0, HERE); import reserve_plan
    ok = reserve_plan.write_gate("th_gate scratch " + what, need_bytes, log=lambda m: print(m, file=sys.stderr, flush=True), cap_s=GATE_CAP_S, poll_s=GATE_POLL_S,
                                 free_gib=lambda: _free_gib(d), floor_fn=lambda: A_FLOOR_GIB)
    if not ok:
        raise ThError("scratch drive below the %.0f GiB reserve: scratch expansion not written" % A_FLOOR_GIB)


def _expand_iter(path, d, k, gate=None):
    """Yield, one at a time, the paths TruffleHog can read for `path` (parts written under scratch dir d). A .zst is STREAMED: a part is yielded as soon as it is closed, so the producer
    can hand it to a batch and block on the in-flight bound before the next part is written (scratch never holds more than the in-flight batches + one part). gate(need_bytes) is called before each write."""
    low = path.lower(); ext = os.path.splitext(low)[1]
    if ext in SKIP_EXT:
        return
    if ext == ".zst":
        import zstandard
        out = os.path.join(d, "%d-%s" % (k, os.path.basename(path)[:-4]))
        # TruffleHog 3.99.8 exits rc=1 with no output on a single decompressed file >= ~200 MB (20 MB slices of the same text pass): write line-aligned parts of <= PART_MB (2026-11-10, pes2o-00003-00005 final-00003 was 1.5 GB)
        n = 0; cur = None; size = 0; lim = int(PART_MB * (1 << 20)); cur_nm = None
        try:
            with open(path, "rb") as f:
                rd = zstandard.ZstdDecompressor().stream_reader(f); tail = b""
                while True:
                    buf = rd.read(min(8 << 20, lim))      # == 8 MB at the default PART_MB (tests shrink PART_MB)
                    if not buf: break
                    buf = tail + buf; cut = buf.rfind(bytes([10])) + 1
                    if cut == 0: tail = buf; continue
                    body, tail = buf[:cut], buf[cut:]
                    if cur is None or size + len(body) > lim:
                        if cur:
                            cur.close(); cur = None; yield cur_nm
                        if gate: gate(4 * (BATCH_MB << 20) + (256 << 20))
                        cur_nm = "%s.part%03d" % (out, n); n += 1; cur = open(cur_nm, "wb"); size = 0
                    cur.write(body); size += len(body)
                if tail:
                    if cur is None:
                        if gate: gate(4 * (BATCH_MB << 20) + (256 << 20))
                        cur_nm = out + ".part000"; n += 1; cur = open(cur_nm, "wb")
                    cur.write(tail)
                if cur:
                    cur.close(); cur = None; yield cur_nm
        finally:
            if cur: cur.close()
        return
    if ext == ".parquet":
        import pyarrow.parquet as pq, pyarrow as pa
        out = os.path.join(d, "%d-%s.txt" % (k, os.path.basename(path)))
        if gate: gate(4 * os.path.getsize(path) + (256 << 20))
        with open(path, "rb") as f, open(out, "wb") as o:
            pf = pq.ParquetFile(f)
            cols = [c.name for c in pf.schema_arrow if pa.types.is_string(c.type) or pa.types.is_large_string(c.type)]
            for b in pf.iter_batches(batch_size=8, columns=cols or None):
                for col in b.columns:
                    if pa.types.is_string(col.type) or pa.types.is_large_string(col.type):
                        for v in col.to_pylist():
                            if v:
                                o.write(v.encode("utf-8", "ignore") + b"\n")
        yield out
        return
    yield path            # plain text, .gz, .tar(.gz), .zip: TruffleHog handles them natively


def _expand(path, d, k):
    """-> list of paths TruffleHog can read, written under scratch dir d (whole-file form, no gate; kept for th_bisect and callers that want a list)"""
    return list(_expand_iter(path, d, k))


def _run(targets, timeout, tmpdir=None):
    """ONE TruffleHog process over all `targets` -> list of finding dicts. Fail-closed: a missing/unreadable target, a non-zero exit after MAX_ATTEMPTS, a timeout on every attempt, or a stdout line
    that starts with { but is not valid JSON raises ThError."""
    if not os.path.exists(TH):
        raise ThError("trufflehog binary missing: " + TH)
    targets = list(targets)
    for t in targets:      # a part that vanished or cannot be read is never "clean"
        try:
            if not os.path.isfile(t): raise OSError("not a file")
            with open(t, "rb") as fh: fh.read(1)
        except OSError:
            raise ThError("unreadable scan target: " + os.path.basename(t))
    env = dict(os.environ, TMP=tmpdir, TEMP=tmpdir) if tmpdir else None      # archive handlers' temp files stay on the scratch drive (never C:)
    size_mb = sum(os.path.getsize(t) for t in targets) // (1 << 20)
    out = b""; err = b""; rc = None; timeouts = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):      # TruffleHog 3.99.8 exits rc=1 on ~half of runs after "finished scanning path" (same 20 MB file: rc 0 1 1 0 1 0 ...; not load, not network, not flags; 2026-11-10): retry, alternate concurrency 2/1; still fail-closed
        cmd = [TH, "filesystem"] + targets + ["--json", "--no-update", "--no-verification", "--results=" + RESULTS, "--concurrency=%d" % (2 if attempt % 2 else 1)]
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=0x00004000, env=env)   # BELOW_NORMAL_PRIORITY_CLASS
        try:
            import psutil
            psutil.Process(p.pid).cpu_affinity(CPUS)
        except Exception:
            pass
        try:
            out, err = p.communicate(timeout=min(timeout, 240 + 3 * size_mb))
        except subprocess.TimeoutExpired:      # a hung run is retried like a crashed one
            p.kill(); p.communicate(); timeouts += 1; rc = None
            continue
        rc = p.returncode
        if rc == 0:
            break
    else:
        if rc is None:
            raise ThError("trufflehog timed out %d times" % timeouts)
        raise ThError("trufflehog rc=%s after %d tries: %s" % (rc, MAX_ATTEMPTS, err[-200:].decode("utf-8", "ignore")))
    rows = []
    for l in out.splitlines():
        l = l.strip()
        if not l.startswith(b"{"):
            continue
        try:
            j = json.loads(l)
        except Exception:
            raise ThError("trufflehog printed a broken JSON line (not parsed, so not trusted)")
        if "DetectorName" in j:
            rows.append(j)
    return rows


def _scan_batch(targets, owner, timeout, tmpdir=None):
    """One batch -> [(source_file, detector, raw)]. A hit whose file is not in `owner` (part path -> source file) is a ThError."""
    hits = []
    for j in _run(targets, timeout, tmpdir):
        src = ((j.get("SourceMetadata", {}).get("Data", {}) or {}).get("Filesystem", {}) or {}).get("file", "")
        o = owner.get(os.path.normcase(os.path.abspath(src))) if src else None
        if o is None:
            raise ThError("a finding came from a file outside the batch (%s): cannot be attributed" % (os.path.basename(src) if src else "no file"))
        hits.append((o, j["DetectorName"], j.get("Raw")))
    return hits


def scan_files(paths, timeout=3600, keep_values=False, stats=None):
    """Scan `paths`; `stats` (a dict, optional) is filled with K, workers, parts, batches, scan_s (numbers only, read back from this run)."""
    sys.path.insert(0, HERE); import scratch_dir      # owner-stamped: a killed scan's expansion is swept (lead 82361)
    t_start = time.time()
    try: scratch_dir.sweep(root=SCRATCH, log=os.path.join(os.path.dirname(os.path.abspath(SCRATCH)), "scratch-sweep.jsonl"))      # dead writers' stamped dirs on THIS scratch root; its receipts stay on A:
    except Exception: pass
    d = scratch_dir.make("th-", SCRATCH); res = {"hits": {}, "files": {}}; vals = []
    K = max(1, int(BATCH_PARTS)); nw = max(1, min(4, int(WORKERS))); maxb = int(BATCH_MB) << 20
    st = dict(K=K, workers=nw, parts=0, batches=0)
    q = queue.Queue(); inflight = threading.Semaphore(nw)      # at most nw batches queued or in flight: scratch on A: stays about nw * BATCH_MB
    abort = threading.Event(); errs = []; lk = threading.Lock()

    def worker():
        while True:
            b = q.get()
            if b is None:
                return
            targets, owner, scratch = b
            try:
                if not abort.is_set():
                    for o, det, raw in _scan_batch(targets, owner, timeout, d):
                        with lk:
                            res["hits"][det] = res["hits"].get(det, 0) + 1
                            f = res["files"].setdefault(o, {}); f[det] = f.get(det, 0) + 1
                            if keep_values and raw:
                                vals.append(raw)
            except ThError as e:
                with lk: errs.append(e)
                abort.set()
            except Exception as e:
                with lk: errs.append(ThError("scan worker failed: " + type(e).__name__))
                abort.set()
            finally:
                for t in scratch:
                    try: os.remove(t)
                    except OSError: pass
                inflight.release()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(nw)]
    for th in threads: th.start()
    cur_t = []; cur_o = {}; cur_s = []; cur_b = 0      # the batch being filled

    def flush():
        nonlocal cur_t, cur_o, cur_s, cur_b
        if not cur_t: return
        while not inflight.acquire(timeout=0.5):
            if abort.is_set(): return
        if abort.is_set():
            inflight.release(); return
        q.put((cur_t, cur_o, cur_s)); st["batches"] += 1
        cur_t = []; cur_o = {}; cur_s = []; cur_b = 0

    perr = None
    try:
        for k, p in enumerate(paths):      # ONE source file at a time is expanded (and streamed into batches): scratch holds at most the in-flight batches, never a whole pack (2026-11-10: expanding a whole pack first put 5-6 GB per concurrent scan on B:)
            if abort.is_set(): break
            try:
                for t in _expand_iter(p, d, k, gate=lambda need: _gate(os.path.basename(p), need, d)):
                    sz = os.path.getsize(t)
                    if cur_t and (len(cur_t) >= K or cur_b + sz > maxb):
                        flush()
                        if abort.is_set(): break
                    cur_t.append(t); cur_o[os.path.normcase(os.path.abspath(t))] = p; cur_b += sz; st["parts"] += 1       # owner: part path -> SOURCE pack file
                    if t != p: cur_s.append(t)
            except ThError: raise
            except Exception as e:
                raise ThError("could not read %s for scanning: %s" % (os.path.basename(p), type(e).__name__))
        if not abort.is_set(): flush()
    except BaseException as e:
        perr = e
        abort.set()
    finally:
        for _ in threads: q.put(None)
        for th in threads: th.join()
        for t in cur_s:      # a batch that was filled but never handed over
            try: os.remove(t)
            except OSError: pass
        shutil.rmtree(d, ignore_errors=True)
    if perr is not None:
        raise perr
    if errs:      # whole result is an error: no partial "clean"
        raise errs[0]
    if stats is not None:
        stats.update(st); stats["scan_s"] = round(time.time() - t_start, 3)
    if keep_values:
        res["_values"] = vals
    return res


def find_values(path):
    return scan_files([path], keep_values=True).get("_values", [])


def gate(paths, lane, rp, refusals=None):
    """True = clean. A hit or a scanner failure => False and a value-free refusal row (fail-closed)."""
    try:
        r = scan_files(paths); err = None
    except ThError as e:
        r = {"hits": {}, "files": {}}; err = str(e)[:200]
    if r["hits"] or err:
        with open(refusals or REFUSALS, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), lane=lane, hf_path=rp, scanner="trufflehog", hits=r["hits"], error=err)) + "\n")
        return False
    return True


def selftest():
    global TH, PART_MB, BATCH_PARTS
    sys.path.insert(0, HERE); import scratch_dir, zstandard
    d = scratch_dir.make("thself-", SCRATCH); ok = True; refp = os.path.join(d, "ref.jsonl")

    def chk(n, c):
        nonlocal ok
        print(("PASS " if c else "FAIL ") + n); ok = ok and bool(c)

    clean = b"The quick brown fox jumps over the lazy dog. See https://example.com/page for details.\n" * 500
    ftp = b"mirror at ftp://" + b"anonuser" + b":" + b"S3cretPass99" + b"@ftp.example-host.invalid/pub/file.txt\n"      # fixture only

    def w(n, data):
        p = os.path.join(d, n); open(p, "wb").write(data); return p

    chk("clean text passes", gate([w("c.txt", clean)], "selftest", "c.txt", refp) is True)
    g = gate([w("f.jsonl", clean + ftp + clean)], "selftest", "f.jsonl", refp)
    row = open(refp).read() if os.path.exists(refp) else ""
    chk("ftp://user:pass@ fixture refused (plain), refusal row holds no value", g is False and "S3cretPass99" not in row and "trufflehog" in row)
    zp = w("o.jsonl.zst", zstandard.ZstdCompressor().compress(clean + ftp))
    chk("ftp cred inside .jsonl.zst refused", gate([zp], "selftest", "o.jsonl.zst", refp) is False)
    import tarfile
    tp = os.path.join(d, "x.tar.gz")
    with tarfile.open(tp, "w:gz") as tf:
        tf.add(w("in.jsonl", clean + ftp), arcname="objects/in.jsonl")
    chk("ftp cred inside .tar.gz refused", gate([tp], "selftest", "x.tar.gz", refp) is False)
    import pyarrow as pa, pyarrow.parquet as pq
    pqp = os.path.join(d, "t.parquet"); pq.write_table(pa.table({"text": ["hello", "x " + ftp.decode()]}), pqp)
    chk("ftp cred inside parquet refused", gate([pqp], "selftest", "t.parquet", refp) is False)
    TH0 = TH; TH = "B:/nonexistent/trufflehog.exe"
    chk("missing scanner => refuse (fail-closed)", gate([w("c2.txt", clean)], "selftest", "c2.txt", refp) is False)
    TH = TH0
    # batching: a .zst cut into many small parts, the secret in the LAST part; K=4 -> several batches; attribution to the source file; one process per batch
    PART0, K0 = PART_MB, BATCH_PARTS
    try:
        PART_MB = 0.02; BATCH_PARTS = 4
        body = b"".join(b"line %06d The quick brown fox jumps over the lazy dog, see https://example.com/page.\n" % i for i in range(5000))
        zb = w("big.jsonl.zst", zstandard.ZstdCompressor().compress(body + ftp)); zc = w("bigclean.jsonl.zst", zstandard.ZstdCompressor().compress(body))
        st = {}; r = scan_files([zb], stats=st)
        chk("secret in the last part of a multi-batch .zst is refused and attributed to the source file", sum(r["hits"].values()) == 1 and list(r["files"]) == [zb] and st["batches"] >= 2 and st["batches"] == -(-st["parts"] // 4))
        calls = []; _run0 = globals()["_run"]
        globals()["_run"] = lambda targets, timeout, tmpdir=None: calls.append(len(targets)) or []
        try:
            st = {}; r = scan_files([zc], stats=st)
        finally:
            globals()["_run"] = _run0
        chk("clean multi-part .zst: TruffleHog processes started == batches (%d), not parts (%d)" % (st["batches"], st["parts"]), len(calls) == st["batches"] and st["batches"] < st["parts"] and not r["hits"])
        gone = os.path.join(d, "gone.txt"); open(gone, "wb").write(clean); os.remove(gone)
        try: _run([w("here.txt", clean), gone], 60); refused = False
        except ThError: refused = True
        chk("a batch with an unreadable (deleted) part is refused as a whole", refused)
    finally:
        PART_MB, BATCH_PARTS = PART0, K0
    shutil.rmtree(d, ignore_errors=True); print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        selftest()
    elif len(sys.argv) > 2 and sys.argv[1] == "scan":
        print(json.dumps(scan_files(sys.argv[2:])))
