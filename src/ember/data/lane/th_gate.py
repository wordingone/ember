# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TruffleHog pre-upload gate (operator / lead 81934): HF scans every pushed file with TruffleHog, so our gate runs the SAME detector set before anything leaves the PC, FAIL-CLOSED
(missing binary, crash, timeout, unreadable file => refuse). Values are never logged: only detector name + count (+ file) reach any log/mail.
scan_files(paths) -> {"hits": {detector: n}, "files": {path: {detector: n}}}   raises ThError when the scanner could not run.
find_values(path) -> [raw secret strings] IN MEMORY ONLY, for th_redact (callers must not print/log them).
Prep: .zst / .parquet are expanded to plain text in <lane-root>/scratch (TruffleHog does not decode them); .gz/.tar/.tar.gz/.zip go straight to its archive handlers.
Run:  python th_gate.py selftest | scan <path>"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, subprocess, time, tempfile, shutil

TH = os.environ.get("TH_BIN", (LANE_ROOT + "/tools/trufflehog/trufflehog.exe"))
SCRATCH = (LANE_ROOT + "/scratch"); os.makedirs(SCRATCH, exist_ok=True)
PART_MB = 8      # TruffleHog 3.99.8 dies silently (rc=1, mid-scan) on 63 MB parts 100% of the time and on 20 MB parts ~50%; 2 MB and 8 MB parts passed 16/16 (2026-11-10)
RESULTS = "verified,unverified,unknown,filtered_unverified"      # --no-verification: nothing is sent to any third party; HF reports unverified hits too
SKIP_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".mp3", ".flac", ".wav", ".ogg", ".opus", ".m4a", ".mp4", ".webm", ".mkv",
            ".safetensors", ".pt", ".pth", ".bin", ".gguf", ".ckpt", ".npy", ".npz", ".onnx", ".h5", ".pkl"}
REFUSALS = (LANE_ROOT + "/logs/secret-refusals.jsonl")


class ThError(Exception):
    pass


def _expand(path, d, k):
    """-> list of paths TruffleHog can read, written under scratch dir d"""
    low = path.lower(); ext = os.path.splitext(low)[1]
    if ext in SKIP_EXT:
        return []
    if ext == ".zst":
        import zstandard
        out = os.path.join(d, "%d-%s" % (k, os.path.basename(path)[:-4]))
        # TruffleHog 3.99.8 exits rc=1 with no output on a single decompressed file >= ~200 MB (20 MB slices of the same text pass): write line-aligned parts of <= PART_MB (2026-11-10, pes2o-00003-00005 final-00003 was 1.5 GB)
        parts = []; cur = None; size = 0; lim = PART_MB << 20
        with open(path, "rb") as f:
            rd = zstandard.ZstdDecompressor().stream_reader(f); tail = b""
            while True:
                buf = rd.read(8 << 20)
                if not buf: break
                buf = tail + buf; cut = buf.rfind(bytes([10])) + 1
                if cut == 0: tail = buf; continue
                body, tail = buf[:cut], buf[cut:]
                if cur is None or size + len(body) > lim:
                    if cur: cur.close()
                    nm = "%s.part%03d" % (out, len(parts)); parts.append(nm); cur = open(nm, "wb"); size = 0
                cur.write(body); size += len(body)
            if tail:
                if cur is None: nm = out + ".part000"; parts.append(nm); cur = open(nm, "wb")
                cur.write(tail)
            if cur: cur.close()
        return parts
    if ext == ".parquet":
        import pyarrow.parquet as pq, pyarrow as pa
        out = os.path.join(d, "%d-%s.txt" % (k, os.path.basename(path)))
        with open(path, "rb") as f, open(out, "wb") as o:
            pf = pq.ParquetFile(f)
            cols = [c.name for c in pf.schema_arrow if pa.types.is_string(c.type) or pa.types.is_large_string(c.type)]
            for b in pf.iter_batches(batch_size=8, columns=cols or None):
                for col in b.columns:
                    if pa.types.is_string(col.type) or pa.types.is_large_string(col.type):
                        for v in col.to_pylist():
                            if v:
                                o.write(v.encode("utf-8", "ignore") + b"\n")
        return [out]
    return [path]            # plain text, .gz, .tar(.gz), .zip: TruffleHog handles them natively


def _run(targets, timeout):
    if not os.path.exists(TH):
        raise ThError("trufflehog binary missing: " + TH)
    for attempt in range(1, 21):      # TruffleHog 3.99.8 exits rc=1 on ~half of runs after "finished scanning path" (same 20 MB file: rc 0 1 1 0 1 0 ...; not load, not network, not flags; 2026-11-10): retry up to 8x, alternate concurrency 2/1; still fail-closed
        cmd = [TH, "filesystem"] + list(targets) + ["--json", "--no-update", "--no-verification", "--results=" + RESULTS, "--concurrency=%d" % (2 if attempt % 2 else 1)]
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=0x00004000)   # BELOW_NORMAL_PRIORITY_CLASS
        try:
            import psutil
            psutil.Process(p.pid).cpu_affinity(list(range(16, 24)))      # lane work stays on CCD1 (CPUs 16-23)
        except Exception:
            pass
        try:
            out, err = p.communicate(timeout=min(timeout, 240 + 3 * sum(os.path.getsize(t) for t in targets if os.path.exists(t)) // (1 << 20)))
        except subprocess.TimeoutExpired:      # a hung run is retried like a crashed one
            p.kill(); p.communicate()
            if attempt == 20: raise ThError("trufflehog timed out 20 times")
            continue
        if p.returncode == 0:
            break
        if attempt == 20:
            raise ThError("trufflehog rc=%s after 20 tries: %s" % (p.returncode, err[-200:].decode("utf-8", "ignore")))
    rows = []
    for l in out.splitlines():
        l = l.strip()
        if not l.startswith(b"{"):
            continue
        try:
            j = json.loads(l)
        except Exception:
            continue
        if "DetectorName" in j:
            rows.append(j)
    return rows


def scan_files(paths, timeout=3600, keep_values=False):
    sys.path.insert(0, (LANE_ROOT + "/scripts")); import scratch_dir      # owner-stamped: a killed scan's expansion is swept by the tick (lead 82361)
    d = scratch_dir.make("th-", SCRATCH); res = {"hits": {}, "files": {}}; vals = []
    try:
        for k, p in enumerate(paths):      # one path at a time: expand -> scan -> delete its parts, so scratch holds at most ONE file's expansion (2026-11-10: expanding a whole pack first put 5-6 GB per concurrent scan on B:)
            try:
                sys.path.insert(0, (LANE_ROOT + "/scripts")); import reserve_plan      # lead 82324: scratch expansion waits on the B: floor (wait, don't write)
                if not reserve_plan.write_gate("th_gate scratch", 4 * os.path.getsize(p) + (256 << 20), floor_fn=reserve_plan.scan_floor_gib): raise ThError("B: below the reserve floor: scratch expansion not written")
                ex = _expand(p, d, k)
            except ThError: raise
            except Exception as e:
                raise ThError("could not read %s for scanning: %s" % (os.path.basename(p), type(e).__name__))
            owner = {os.path.normcase(os.path.abspath(t)): p for t in ex}
            for t in ex:      # one TruffleHog process per part: a silent crash costs one small part
                for j in _run([t], timeout):
                    src = ((j.get("SourceMetadata", {}).get("Data", {}) or {}).get("Filesystem", {}) or {}).get("file", "")
                    o = owner.get(os.path.normcase(os.path.abspath(src)), p) if src else "?"
                    det = j["DetectorName"]; res["hits"][det] = res["hits"].get(det, 0) + 1
                    f = res["files"].setdefault(o, {}); f[det] = f.get(det, 0) + 1
                    if keep_values and j.get("Raw"):
                        vals.append(j["Raw"])
                if t != p:
                    try: os.remove(t)
                    except OSError: pass
        if keep_values:
            res["_values"] = vals
        return res
    finally:
        shutil.rmtree(d, ignore_errors=True)


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
    global TH
    sys.path.insert(0, (LANE_ROOT + "/scripts")); import scratch_dir
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
    import zstandard
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
    shutil.rmtree(d, ignore_errors=True); print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        selftest()
    elif len(sys.argv) > 2 and sys.argv[1] == "scan":
        print(json.dumps(scan_files(sys.argv[2:])))
