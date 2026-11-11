# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red test for the batched, parallel, off-B: TruffleHog pack scan (coordinator rulings 82972/82974/82979). Offline; real TruffleHog where a detector verdict matters, a stub (th_stub, via TH_BIN) where the
process count / exit code / output matters. Scratch and temp files live on A: only (TMP/TEMP are pointed at A: here). Run: python tests/th_batch_red_test.py   (TH_RED_REAL_EQUIV=0 skips the real-pack equivalence red, about 10 min)
a) secret in the LAST part of a 32-part batch refused + attributed to the source file     b) same in the first part, in a part of the second batch, in the 2nd of 3 source files
c) unreadable part refuses the whole batch     d) stub rc=2 refuses after 8 attempts; broken JSON refuses; a finding from a file outside the batch refuses; a flake that clears is retried to clean
e) 3 batches clean, TruffleHog processes == batches     f) scratch gate reads A:, waits, fails closed at the cap     g) scan lock     h2) equivalence vs the old per-part form on a real pack     h) mutants"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import os, sys, json, time, shutil, tempfile, threading, subprocess, types, importlib
if not os.environ.get("TMP", "").replace("\\", "/").lower().startswith("a:/"):
    os.environ["TMP"] = os.environ["TEMP"] = "A:/data-scan/tmp-red"
os.makedirs(os.environ["TMP"], exist_ok=True); tempfile.tempdir = None
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)      # the lane scripts dir (this red sits in tests/)
import scratch_dir, reserve_plan, th_gate, th_stub, psutil      # noqa  (preloaded so the reference form below imports THESE copies, not the live ones)

ok = True
WORK = tempfile.mkdtemp(prefix="thred-")
assert WORK.replace("\\", "/").lower().startswith("a:/"), "scratch/temp must be on A:"
os.environ["TH_SCRATCH"] = WORK + "/scratch"; th_gate.SCRATCH = WORK + "/scratch"
STUB = th_stub.make_launcher(WORK); STUB_LOG = WORK + "/stub.log"
os.environ["TH_STUB_LOG"] = STUB_LOG
REAL_TH = th_gate.TH
LINE = b"line %06d The quick brown fox jumps over the lazy dog, see https://example.com/page.\n"
FTP = b"mirror at ftp://" + b"anonuser" + b":" + b"S3cretPass99" + b"@ftp.example-host.invalid/pub/file.txt\n"      # fixture only


def chk(n, c):
    global ok
    ok = ok and bool(c); print(("PASS " if c else "FAIL ") + n, flush=True)


def setup(T, K=32, part_mb=0.02, th=None, mode=None):
    T.SCRATCH = WORK + "/scratch"; T.PART_MB = part_mb; T.BATCH_PARTS = K; T.WORKERS = 4; T.GATE_CAP_S = 6 * 3600; T.GATE_POLL_S = 30; T.TH = th or REAL_TH
    if mode:
        os.environ["TH_STUB_MODE"] = mode
    th_stub.clear(STUB_LOG)


def stub_events():
    ev = [l.split() for l in th_stub.read_lines(STUB_LOG)]
    return [(float(e[1]), int(e[2])) for e in ev if e[0] == "start"], [float(e[1]) for e in ev if e[0] == "end"]


_seq = [0]


def make_zst(name, nparts, plant=None):
    """A .zst of exactly `nparts` parts at PART_MB=0.02. plant: None | 'first' | 'last' | ('part', j): replaces one line by the ftp fixture. -> (path, index of the part holding the fixture or None)"""
    th_gate.PART_MB = 0.02; d = tempfile.mkdtemp(prefix="mk-", dir=WORK); import zstandard

    os.makedirs(d + "/x", exist_ok=True)

    def count(n):
        p = d + "/c.zst"; open(p, "wb").write(zstandard.ZstdCompressor().compress(b"".join(LINE % i for i in range(n))))
        parts = list(th_gate._expand_iter(p, d + "/x", 0))
        for t in parts: os.remove(t)
        return len(parts)
    lo, hi = 1, nparts * 400
    while lo < hi:
        mid = (lo + hi) // 2
        if count(mid) >= nparts: hi = mid
        else: lo = mid + 1
    n = lo + 100
    lines = [LINE % i for i in range(n)]
    at = {None: None, "first": 0, "last": n - 1}.get(plant) if not isinstance(plant, tuple) else int(n * (plant[1] + 0.5) / nparts)
    if at is not None: lines[at] = FTP
    _seq[0] += 1; path = "%s/%s-%d.jsonl.zst" % (WORK, name, _seq[0]); open(path, "wb").write(zstandard.ZstdCompressor().compress(b"".join(lines)))
    dd = tempfile.mkdtemp(prefix="mx-", dir=WORK); parts = list(th_gate._expand_iter(path, dd, 0))
    assert len(parts) == nparts, (len(parts), nparts)
    idx = None
    for i, pp in enumerate(parts):
        if b"S3cretPass99" in open(pp, "rb").read(): idx = i
    shutil.rmtree(d, ignore_errors=True); shutil.rmtree(dd, ignore_errors=True)
    return path, idx


def safe(f, *a):
    try: return bool(f(*a))
    except Exception as e:
        print("   (exception: %s %s)" % (type(e).__name__, str(e)[:100])); return False


def hit_ok(T, path, nparts, batches, K=32):
    setup(T, K=K); st = {}; r = T.scan_files([path], stats=st)
    return sum(r["hits"].values()) == 1 and list(r["files"]) == [path] and sum(r["files"][path].values()) == 1 and st["parts"] == nparts and st["batches"] == batches


# ---------------------------------------------------------------- a) / b)
def chk_a(T):
    p, i = make_zst("a-last", 32, "last"); return i == 31 and hit_ok(T, p, 32, 1)


def chk_b_first(T):
    p, i = make_zst("b-first", 32, "first"); return i == 0 and hit_ok(T, p, 32, 1)


def chk_b_second_batch(T):
    p, i = make_zst("b-second", 70, ("part", 40)); return i is not None and 32 <= i < 64 and hit_ok(T, p, 70, 3)


def chk_b_second_file(T):
    c1, _ = make_zst("b-clean1", 20); p, i = make_zst("b-mid", 20, "last"); c2, _ = make_zst("b-clean2", 20)      # 60 parts over 3 source files; the batches straddle the file borders
    setup(T, K=32); st = {}; r = T.scan_files([c1, p, c2], stats=st)
    return sum(r["hits"].values()) == 1 and list(r["files"]) == [p] and st["parts"] == 60 and st["batches"] == 2


chk("a) secret in the LAST part of a 32-part batch: refused and attributed to the right source file", safe(chk_a, th_gate))
chk("b) the same with the secret in the FIRST part", safe(chk_b_first, th_gate))
chk("b) the same with the secret in a part of the SECOND batch (70 parts -> 3 batches)", safe(chk_b_second_batch, th_gate))
chk("b) secret in the 2nd of 3 source files whose parts share batches: attributed to that file only", safe(chk_b_second_file, th_gate))


# ---------------------------------------------------------------- c)
def chk_c(T):
    setup(T, K=8); z, _ = make_zst("c", 12); real = T._expand_iter; fired = []

    def deleting(path, d, k, gate=None):
        for n, t in enumerate(real(path, d, k, gate)):
            yield t
            if n == 3 and not fired: os.remove(t); fired.append(t)      # one part vanishes after it was handed to its batch, before the scan
    T._expand_iter = deleting
    try:
        try: T.scan_files([z]); return False
        except T.ThError as e: return bool(fired) and "unreadable" in str(e)
    finally:
        T._expand_iter = real


chk("c) a batch with one unreadable (deleted before the scan) part refuses the whole scan (ThError)", safe(chk_c, th_gate))


# ---------------------------------------------------------------- d)
def chk_d_rc2(T):
    setup(T, K=32, th=STUB, mode="rc2"); z, _ = make_zst("d", 10)
    try: T.scan_files([z]); return False
    except T.ThError as e: return len(stub_events()[0]) == 8 and "rc=2" in str(e) and "8 tries" in str(e)


def chk_d_broken(T):
    setup(T, K=32, th=STUB, mode="broken"); z, _ = make_zst("d", 10)
    try: T.scan_files([z]); return False
    except T.ThError as e: return "broken JSON" in str(e)


def chk_d_foreign(T):
    setup(T, K=32, th=STUB, mode="foreign"); z, _ = make_zst("d", 10)
    try: T.scan_files([z]); return False
    except T.ThError as e: return "outside the batch" in str(e)


def chk_d_flake(T):
    setup(T, K=32, th=STUB, mode="flake3"); z, _ = make_zst("d", 10); r = T.scan_files([z])
    return r["hits"] == {} and len(stub_events()[0]) == 4


chk("d) a TruffleHog stub that exits 2 every time refuses (ThError) after exactly 8 attempts", safe(chk_d_rc2, th_gate))
chk("d) a stub that prints a broken JSON line refuses", safe(chk_d_broken, th_gate))
chk("d) a finding whose file is not in the batch's owner map is an ERROR (never attributed to '?')", safe(chk_d_foreign, th_gate))
chk("d) a stub that fails 3 times then succeeds is retried to a clean verdict (4 attempts)", safe(chk_d_flake, th_gate))


# ---------------------------------------------------------------- e)
def chk_e(T):
    setup(T, K=4, th=STUB, mode="clean"); z, _ = make_zst("e", 10); st = {}; r = T.scan_files([z], stats=st)
    starts, _ = stub_events()
    return not r["hits"] and st["parts"] == 10 and st["batches"] == 3 and len(starts) == 3 and sorted(n for _, n in starts) == [2, 4, 4]


def chk_e_real(T):
    setup(T, K=4); z, _ = make_zst("e", 10); st = {}; r = T.scan_files([z], stats=st); return not r["hits"] and st["batches"] == 3


chk("e) clean text over 3 batches (10 parts, K=4): clean, and TruffleHog processes started == batches (3), not parts (10)", safe(chk_e, th_gate))
chk("e) the same with the real TruffleHog: clean", safe(chk_e_real, th_gate))


def chk_workers(T):
    setup(T, K=2, th=STUB, mode="sleep"); os.environ["TH_STUB_SLEEP"] = "0.5"; z, _ = make_zst("w", 20); peak = [0]; stop = threading.Event()

    def watch():
        while not stop.is_set():
            n = sum(len(fs) for _, _, fs in os.walk(WORK + "/scratch")); peak[0] = max(peak[0], n); time.sleep(0.01)
    th = threading.Thread(target=watch); th.start()
    try: st = {}; T.scan_files([z], stats=st)
    finally: stop.set(); th.join(); os.environ["TH_STUB_SLEEP"] = "2"
    starts, ends = stub_events(); ev = sorted([(s, 1) for s, _ in starts] + [(e, -1) for e in ends]); cur = mx = 0
    for _, dlt in ev:
        cur += dlt; mx = max(mx, cur)
    left = sum(len(fs) for _, _, fs in os.walk(WORK + "/scratch") if True)
    print("   10 batches: peak concurrent TruffleHog processes %d, peak files in scratch %d (bound 4*K+K+2 = 12 + stamp)" % (mx, peak[0]))
    return st["batches"] == 10 and 2 <= mx <= 4 and peak[0] <= 4 * 2 + 2 + 2 + 1 and left == 0


chk("i) at most 4 TruffleHog processes at once (and more than 1), scratch bounded by the in-flight batches, nothing left behind", safe(chk_workers, th_gate))


# ---------------------------------------------------------------- f)
def chk_f(T):
    res = []
    z, _ = make_zst("f", 6); need_gib = (4 * (T.BATCH_MB << 20) + (256 << 20)) / 2**30
    # waits then fails closed at the cap when A: free < 20 GiB + need
    setup(T, K=32, th=STUB, mode="clean"); T.GATE_CAP_S = 2; T.GATE_POLL_S = 0.5; T._free_gib = lambda path: 10.0; t0 = time.time()
    try: T.scan_files([z]); res.append(False)
    except T.ThError as e: res.append(time.time() - t0 >= 1.9 and "reserve" in str(e))
    # exactly at the boundary: 20 + need - 0.1 waits (refuses at the cap); 20 + need proceeds
    T._free_gib = lambda path: 20 + need_gib - 0.1
    try: T.scan_files([z]); res.append(False)
    except T.ThError: res.append(True)
    T._free_gib = lambda path: 20 + need_gib + 0.1; st = {}; T.scan_files([z], stats=st); res.append(st["parts"] == 6)
    # free rises while waiting: it waits (>= 1 poll), then proceeds
    t1 = time.time(); T.GATE_CAP_S = 30; T._free_gib = lambda path: 10.0 if time.time() - t1 < 1.2 else 100.0; st = {}; T.scan_files([z], stats=st); res.append(time.time() - t1 >= 1.0 and st["parts"] == 6)
    return all(res)


def chk_f_path():
    """the real gate reads the SCRATCH drive (A:), never B:"""
    T = th_gate; setup(T, K=32, th=STUB, mode="clean"); z, _ = make_zst("f2", 3); seen = []; real = shutil.disk_usage
    shutil.disk_usage = lambda p: (seen.append(os.path.abspath(str(p))) or real(p))
    try: T.scan_files([z])
    finally: shutil.disk_usage = real
    drives = {os.path.splitdrive(s)[0].lower() for s in seen}
    print("   gate looked at:", sorted(drives), len(seen), "calls")
    return seen and drives == {"a:"}


safe_f = safe(chk_f, th_gate)
th_gate._free_gib = lambda path: shutil.disk_usage(path).free / 2**30       # restore the real reader (chk_f replaced it)
chk("f) scratch gate: A: free < 20 GiB + need => waits, then fails closed at the cap; at 20 GiB + need it proceeds; a rise while waiting lets it proceed", safe_f)
chk("f) the real gate reads A: (the scratch drive), never B:", safe(chk_f_path))
th_gate._free_gib = lambda path: shutil.disk_usage(path).free / 2**30

# ---------------------------------------------------------------- g)
p = subprocess.run([sys.executable, os.path.join(HERE, "th_pack_scan.py"), "selftest"], capture_output=True, text=True, timeout=600, env=dict(os.environ))
print("   " + p.stdout.strip().replace("\n", "\n   "))
chk("g) scan lock: two concurrent callers run one after the other; a stale lock is taken over (th_pack_scan selftest ALL PASS)", p.returncode == 0 and "ALL PASS" in p.stdout)


# ---------------------------------------------------------------- h2) equivalence vs the OLD per-part form
def old_form(files):
    rp = sys.modules["reserve_plan"]; orig = rp.write_gate
    rp.write_gate = lambda *a, **k: True      # the reference writes its scratch to A: (SCRATCH below); its own B: floor gate is bypassed so it never reads/waits on B:
    try:
        import th_gate_ref as O
        sys.path.insert(0, HERE)      # th_gate_ref put the live scripts dir first on sys.path
        O.SCRATCH = WORK + "/scratch-ref"; O.TH = REAL_TH
        t0 = time.time(); r = O.scan_files(files); return r, time.time() - t0
    finally:
        rp.write_gate = orig


def new_form(files):
    setup(th_gate, K=32, part_mb=8); st = {}; t0 = time.time(); r = th_gate.scan_files(files, stats=st); return r, time.time() - t0, st


def triples(r):
    return sorted((det, os.path.normcase(f), n) for f, ds in r["files"].items() for det, n in ds.items())


def equivalence(files, label):
    ro, to = old_form(files); rn, tn, st = new_form(files)
    so, sn = triples(ro), triples(rn)
    print("   [%s] OLD per-part form: %.1f s, hits %s" % (label, to, json.dumps(ro["hits"], sort_keys=True)))
    for t in so: print("      old", t[0], os.path.basename(t[1]), t[2])
    print("   [%s] NEW batched form:  %.1f s (K=%d, %d parts, %d batches), hits %s" % (label, tn, st["K"], st["parts"], st["batches"], json.dumps(rn["hits"], sort_keys=True)))
    for t in sn: print("      new", t[0], os.path.basename(t[1]), t[2])
    return so == sn and ro["hits"] == rn["hits"] and len(so) > 0, (to, tn, st)


def synthetic_equiv():
    th_gate.PART_MB = 8; d = tempfile.mkdtemp(prefix="eq-", dir=WORK); import zstandard
    fs = []
    for i in range(4):
        body = b"".join(LINE % j for j in range(20000)) if i != 2 else b"".join(LINE % j for j in range(10000)) + FTP + b"".join(LINE % j for j in range(10000))
        p = "%s/f%d.jsonl.zst" % (d, i); open(p, "wb").write(zstandard.ZstdCompressor().compress(body)); fs.append(p)
    q = d + "/plain.txt"; open(q, "wb").write(FTP + LINE % 1); fs.append(q)
    return equivalence(fs, "synthetic")[0]


chk("h2) equivalence on a synthetic pack (4 .zst + 1 plain, secrets in two files): old per-part form and new batch form give identical hit sets", safe(synthetic_equiv))

PACK = (LANE_ROOT + "/packed/pre1929-00003-00005")
if os.environ.get("TH_RED_REAL_EQUIV", "1") != "0" and os.path.isdir(PACK):
    obj = lambda n: PACK + "/objects/pre1929-00003-00005-%04d.jsonl.zst" % n
    small = [PACK + "/" + n for n in ("docs-index.jsonl.zst", "domain.json", "intake.json", "ledger.jsonl", "receipt.json", "source-manifest.jsonl")]
    shards = sorted(os.listdir(PACK + "/shards"))[:12]      # skipped by SKIP_EXT (.bin): they count as files of the pack but scan nothing in either form
    files = [obj(1), obj(14), obj(0), obj(2)] + small + [PACK + "/shards/" + s for s in shards]
    print("   real pack: %d files (4 .zst objects incl. the two named hit files 0001/0014, %d small, %d shard .bin skipped by both forms); old record: Noticeable 1 in 0001, Wit 1 in 0014" % (len(files), len(small), len(shards)))
    good, (to, tn, st) = equivalence(files, "real pre1929-00003-00005")
    chk("h2) EQUIVALENCE on the real pack with hits: old per-part form == new batch form (same detector, same source file, same count)", good)
    print("   speed on the real files: old %.1f s, new %.1f s => %.1fx" % (to, tn, to / tn if tn else 0))
else:
    print("   (real-pack equivalence skipped: TH_RED_REAL_EQUIV=0 or pack absent)")


# ---------------------------------------------------------------- h) mutants
def mutant(old, new, tag):
    src = open(os.path.join(HERE, "th_gate.py"), encoding="utf-8").read()
    assert src.count(old) == 1, "mutation site not unique/found: " + tag
    m = types.ModuleType("th_gate_mut_" + tag); m.__file__ = os.path.join(HERE, "th_gate.py"); sys.modules[m.__name__] = m
    exec(compile(src.replace(old, new), m.__file__, "exec"), m.__dict__); return m


M1 = mutant("K = max(1, int(BATCH_PARTS))", "K = 1", "k1")
M2 = mutant("cur_o[os.path.normcase(os.path.abspath(t))] = p; ", "", "noowner")
M3 = mutant("        rc = p.returncode\n        if rc == 0:", "        rc = p.returncode\n        if True:", "norc")
chk("h) mutant: batch size forced to 1 makes e) fail (processes == parts, not batches)", not safe(chk_e, M1))
chk("h) mutant: attribution map emptied makes a) fail", not safe(chk_a, M2) and not safe(chk_b_first, M2))
chk("h) mutant: rc check removed makes d) fail", not safe(chk_d_rc2, M3))
chk("h) un-mutated module still passes the same checks (the mutants differ by exactly one line)", safe(chk_e, th_gate) and safe(chk_a, th_gate) and safe(chk_d_rc2, th_gate))

left = [e for e in os.listdir(WORK + "/scratch")] if os.path.isdir(WORK + "/scratch") else []
chk("no scratch directory left behind by any scan", not left)
shutil.rmtree(WORK, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
