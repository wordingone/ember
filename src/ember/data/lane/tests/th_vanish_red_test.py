# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red test (lead 83073): TruffleHog 3.99.8 exits rc 0 with EMPTY stdout when a target file vanishes after the process started (Windows Defender quarantine of a scratch part), so th_gate._run, which read only rc and
stdout, let the part pass unscanned and the pack read CLEAN. stderr then carries a JSON error line and a "finished scanning" line whose bytes are short. _run now refuses (ThError, no retry) on
  a) any stderr JSON line with level "error"     b) a target missing, unreadable or of a different size than recorded just before launch     c) "finished scanning" bytes below the summed target sizes, or the line absent.
(Measured on TruffleHog 3.99.8: on clean text, binary, .gz and empty targets bytes >= the summed sizes, because chunks overlap; so bytes < sum is the strictest check that holds.)
Offline: th_stub (via TH_BIN) in modes vanish_err / vanish_gone / vanish_bytes / vanish, and a clean run that must not be refused. Each refusal has a ONE-LINE MUTANT (refusal patched out of th_gate's source) that the red must catch.
Run: python tests/th_vanish_red_test.py   (temp files under A: only)"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os, sys, tempfile, shutil, types
if not os.environ.get("TMP", "").replace("\\", "/").lower().startswith("a:/"):
    os.environ["TMP"] = os.environ["TEMP"] = "A:/data-scan/tmp-red"
os.makedirs(os.environ["TMP"], exist_ok=True); tempfile.tempdir = None
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
import th_gate, th_stub      # noqa

ok = True
WORK = tempfile.mkdtemp(prefix="thvan-")
assert WORK.replace("\\", "/").lower().startswith("a:/"), "temp files must be on A:"
STUB = th_stub.make_launcher(WORK); STUB_LOG = WORK + "/stub.log"; os.environ["TH_STUB_LOG"] = STUB_LOG
LINE = b"The quick brown fox jumps over the lazy dog, see https://example.com/page number %08d.\n"
_n = [0]


def chk(n, c):
    global ok
    ok = ok and bool(c); print(("PASS " if c else "FAIL ") + n, flush=True)


def targets(k=4):
    _n[0] += 1; d = tempfile.mkdtemp(prefix="t-", dir=WORK); fs = []
    for i in range(k):
        p = "%s/p%d.txt" % (d, i); open(p, "wb").write(b"".join(LINE % j for j in range(50 + 7 * i))); fs.append(p)
    return fs


def refuses(T, mode, needle=None):
    """True when _run over 4 fresh targets raises ThError (message containing needle) after exactly ONE stub invocation (a refusal is never retried into a pass)."""
    os.environ["TH_STUB_MODE"] = mode; T.TH = STUB; th_stub.clear(STUB_LOG)
    try: T._run(targets(), 60)
    except T.ThError as e:
        starts = [l for l in th_stub.read_lines(STUB_LOG) if l.startswith("start")]
        return (needle is None or needle in str(e)) and len(starts) == 1
    return False


def passes(T):
    os.environ["TH_STUB_MODE"] = "clean"; T.TH = STUB; th_stub.clear(STUB_LOG)
    return T._run(targets(), 60) == []


def a_err(T): return refuses(T, "vanish_err", "error")
def b_gone(T): return refuses(T, "vanish_gone", "changed")
def c_bytes(T): return refuses(T, "vanish_bytes", "bytes")


def c_absent(T):
    """the 'finished scanning' line missing altogether is a refusal: a stub copy that omits it"""
    src = open(os.path.join(HERE, "th_stub.py"), encoding="utf-8").read(); old = '    if mode != "rc2": print(json.dumps({"level": "info-0"'
    assert src.count(old) == 1; p = WORK + "/th_stub_nofin.py"; open(p, "w", encoding="utf-8").write(src.replace(old, '    if False: print(json.dumps({"level": "info-0"'))
    cmd = WORK + "/th_stub_nofin.cmd"; open(cmd, "w").write('@echo off\r\n"%s" "%s" %%*\r\n' % (sys.executable, p))
    os.environ["TH_STUB_MODE"] = "clean"; T.TH = cmd
    try: T._run(targets(), 60)
    except T.ThError as e: return "finished" in str(e)
    return False


def all_vanish(T): return refuses(T, "vanish")


def scan_files_vanish(T):
    """end to end through scan_files: a vanished plain target refuses the whole scan"""
    os.environ["TH_STUB_MODE"] = "vanish"; T.TH = STUB; T.SCRATCH = WORK + "/scratch"; T.BATCH_PARTS = 32; T.WORKERS = 2
    try: T.scan_files(targets())
    except T.ThError: return True
    return False


def setup(T):
    T.SCRATCH = WORK + "/scratch"; T.WORKERS = 4


def mutant(old, new, tag):
    src = open(os.path.join(HERE, "th_gate.py"), encoding="utf-8").read()
    assert src.count(old) == 1, "mutation site not unique/found: " + tag
    m = types.ModuleType("th_gate_mut_" + tag); m.__file__ = os.path.join(HERE, "th_gate.py"); sys.modules[m.__name__] = m
    exec(compile(src.replace(old, new), m.__file__, "exec"), m.__dict__); return m


def safe(f, *a):
    try: return bool(f(*a))
    except Exception as e:
        print("   (exception: %s %s)" % (type(e).__name__, str(e)[:100])); return False


setup(th_gate)
chk("a) stderr error line (stub vanish_err, files intact, bytes right): ThError naming the error, one attempt", safe(a_err, th_gate))
chk("b) a target gone after the start (stub vanish_gone, stderr silent, bytes right): ThError, one attempt", safe(b_gone, th_gate))
chk("c) 'finished scanning' bytes short of the summed sizes (stub vanish_bytes): ThError, one attempt", safe(c_bytes, th_gate))
chk("c) 'finished scanning' line absent: ThError", safe(c_absent, th_gate))
chk("all three at once (stub vanish): ThError, one attempt", safe(all_vanish, th_gate))
chk("end to end: scan_files over a batch whose part vanished raises ThError", safe(scan_files_vanish, th_gate))
chk("a clean stub run (finished line, bytes == sum) is NOT refused", safe(passes, th_gate))

# ---- mutants: each refusal patched out by ONE source edit; the matching red must then fail
MA = mutant('if _stderr_errors(err):', 'if False:', "a")
MB = mutant('if _changed(sizes):', 'if False:', "b")
MC = mutant('if fin is None or fin < sum(sizes.values()):', 'if False:', "c")
chk("mutant: error-line refusal removed => a) fails", not safe(a_err, MA))
chk("mutant: size/vanish refusal removed => b) fails", not safe(b_gone, MB))
chk("mutant: bytes refusal removed => c) fails", not safe(c_bytes, MC))
chk("mutant: bytes refusal removed => the absent-line case fails", not safe(c_absent, MC))
chk("un-mutated module still passes all four (the mutants differ by exactly one line)", safe(a_err, th_gate) and safe(b_gone, th_gate) and safe(c_bytes, th_gate) and safe(c_absent, th_gate))
shutil.rmtree(WORK, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
