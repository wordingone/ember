# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green for verified_remove.py (#2454): a delete rests on a fresh server read-back + a fresh local hash, the receipt is on disk before the remove, and a stale marker, a same-size corrupt upload,
a size-only server entry, an unreadable server, a hard link, a path outside the root (also through a junction) and a failed receipt write all KEEP the file. Tmp tree only; no network, no real delete outside it.
Run: python scripts/tests/verified_remove_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import os, sys, json, shutil, hashlib, tempfile, subprocess, types
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import verified_remove as V
ok = True


def check(label, cond):
    global ok
    ok &= bool(cond); print("PASS" if cond else "FAIL", label)


SCR = (LANE_ROOT + "/scratch"); os.makedirs(SCR, exist_ok=True)
T = tempfile.mkdtemp(dir=SCR, prefix="vr-test-"); R = T + "/root"; O = T + "/outside"; os.makedirs(R); os.makedirs(O); RC = T + "/rc/receipts.jsonl"
sha = lambda b: hashlib.sha256(b).hexdigest()


def mk(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(data)
    return path


def rows():
    return [json.loads(l) for l in open(RC)] if os.path.exists(RC) else []


def reader_for(table):
    return lambda repo, hp: table.get((repo, hp))


KW = dict(roots=[R], receipt=RC, authority="test")
D = b"A" * 5000
f1 = mk(R + "/a/f1.bin", D)
seen = {}
def rem_spy(p):
    seen["rc"] = open(RC).read() if os.path.exists(RC) else ""
    seen["p"] = p
    os.remove(p)
r = V.remove_verified(f1, "r", "x/f1", reader=reader_for({("r", "x/f1"): (len(D), sha(D))}), remove=rem_spy, **KW)
check("GREEN matching server size+LFS sha256: removed", r["ok"] and r["bytes"] == len(D) and not os.path.exists(f1))
check("GREEN the receipt row was on disk when remove ran, and it records the compared values", f1.replace("\\", "/") in seen["rc"] and rows()[-1]["server_sha256"] == sha(D) and rows()[-1]["local_sha256"] == sha(D) and rows()[-1]["kind"] == "server-verified")

f2 = mk(R + "/a/f2.bin", D)
r = V.remove_verified(f2, "r", "x/f2", reader=reader_for({}), **KW)
check("RED no server entry (a marker or log claiming 'verified' is not an input): kept", (not r["ok"]) and os.path.exists(f2) and "no server entry" in r["why"])
mk(R + "/a/f2.bin.verified", b"VERIFIED on HF (stale marker)")
r = V.remove_verified(f2, "r", "x/f2", reader=reader_for({}), **KW)
check("RED a stale 'verified' marker next to the file changes nothing: kept", (not r["ok"]) and os.path.exists(f2))

bad = bytearray(D); bad[100] ^= 1
r = V.remove_verified(f2, "r", "x/f2", reader=reader_for({("r", "x/f2"): (len(D), sha(bytes(bad)))}), **KW)
check("RED same-size corrupt upload (server sha256 differs): kept", (not r["ok"]) and os.path.exists(f2) and "sha256 mismatch" in r["why"])
r = V.remove_verified(f2, "r", "x/f2", reader=reader_for({("r", "x/f2"): (len(D), None)}), **KW)
check("RED server entry with equal size but no LFS sha256 (the size-only hole): kept", (not r["ok"]) and os.path.exists(f2) and "no LFS sha256" in r["why"])
r = V.remove_verified(f2, "r", "x/f2", reader=reader_for({("r", "x/f2"): (len(D) + 1, sha(D))}), **KW)
check("RED server size differs: kept", (not r["ok"]) and os.path.exists(f2))
def unreadable(repo, hp): raise V.ServerUnreadable("timeout")
r = V.remove_verified(f2, "r", "x/f2", reader=unreadable, **KW)
check("RED server unreadable (network error is not 'absent' and not 'fine'): kept", (not r["ok"]) and os.path.exists(f2) and "unreadable" in r["why"])

ln = R + "/a/f2.link"; os.link(f2, ln)
r = V.remove_verified(f2, "r", "x/f2", reader=reader_for({("r", "x/f2"): (len(D), sha(D))}), **KW)
check("RED a second hard-link name exists (nlink 2): kept", (not r["ok"]) and os.path.exists(f2) and "nlink" in r["why"])
os.remove(ln)

fo = mk(O + "/o.bin", D)
r = V.remove_verified(fo, "r", "x/o", reader=reader_for({("r", "x/o"): (len(D), sha(D))}), **KW)
check("RED path outside every allowed root: kept", (not r["ok"]) and os.path.exists(fo))
J = R + "/junc"
p = subprocess.run(["cmd", "/c", "mklink", "/J", J.replace("/", "\\"), O.replace("/", "\\")], capture_output=True, text=True)
check("setup: a real junction root/junc -> outside was created", os.path.isdir(J))
if os.path.isdir(J):
    r = V.remove_verified(J + "/o.bin", "r", "x/o", reader=reader_for({("r", "x/o"): (len(D), sha(D))}), **KW)
    check("RED a file reached through a junction that points outside the root: kept", (not r["ok"]) and os.path.exists(fo))
    os.rmdir(J)                                   # removes the junction only, not the target

f3 = mk(R + "/b/f3.bin", D)
badrc = T + "/rc-is-a-dir"; os.makedirs(badrc)
called = []
r = V.remove_verified(f3, "r", "x/f3", reader=reader_for({("r", "x/f3"): (len(D), sha(D))}), roots=[R], receipt=badrc, authority="t", remove=lambda p: called.append(p))
check("RED the receipt cannot be written: the file is kept and remove is never called", (not r["ok"]) and os.path.exists(f3) and not called and "receipt" in r["why"])

orig = V.sha256_file
def touch_while_hashing(p):
    h = orig(p); os.utime(p, (1, 1)); return h
V.sha256_file = touch_while_hashing
r = V.remove_verified(f3, "r", "x/f3", reader=reader_for({("r", "x/f3"): (len(D), sha(D))}), **KW)
V.sha256_file = orig
check("RED the file changed (mtime) while it was hashed: kept", (not r["ok"]) and os.path.exists(f3) and "changed" in r["why"])

# the Hub reader: folder / not found / error mapping, on a stub HfApi
class RepoFile:
    def __init__(s, size, lfs): s.size = size; s.lfs = lfs
class RepoFolder: pass
class EntryNotFoundError(Exception): pass
def stub(result):
    class Api:
        def get_paths_info(self, repo, paths, repo_type="dataset", expand=True):
            if isinstance(result, Exception): raise result
            return result
    sys.modules["huggingface_hub"] = types.SimpleNamespace(HfApi=Api)
    return V.hub_reader()
check("hub_reader: LFS file -> (size, sha256)", stub([RepoFile(7, {"sha256": "ab" * 32})])("r", "p") == (7, "ab" * 32))
check("hub_reader: non-LFS file -> (size, None)", stub([RepoFile(7, None)])("r", "p") == (7, None))
check("hub_reader: a folder is not a file -> None", stub([RepoFolder()])("r", "p") is None)
check("hub_reader: empty answer / EntryNotFound -> None", stub([])("r", "p") is None and stub(EntryNotFoundError("x"))("r", "p") is None)
try:
    stub(RuntimeError("503"))("r", "p"); raised = False
except V.ServerUnreadable:
    raised = True
check("hub_reader: any other error -> ServerUnreadable (never 'absent')", raised)

# local duplicate path
A = mk(R + "/d/a.bin", D); B = mk(T + "/other/a.bin", D)
KD = dict(roots=[R], other_roots=[T + "/other"], receipt=RC, authority="t")
r = V.remove_dup(A, B, **KD)
check("GREEN identical duplicate outside the set: removed, receipt row names both hashes", r["ok"] and not os.path.exists(A) and os.path.exists(B) and rows()[-1]["kind"] == "local-duplicate" and rows()[-1]["duplicate_sha256"] == sha(D))
A = mk(R + "/d/a.bin", D); bd = bytearray(D); bd[7] ^= 1; mk(B, bytes(bd))
r = V.remove_dup(A, B, **KD)
check("RED same-size duplicate with different content: kept", (not r["ok"]) and os.path.exists(A))
os.remove(B)
r = V.remove_dup(A, B, **KD)
check("RED duplicate missing: kept", (not r["ok"]) and os.path.exists(A))
Bh = T + "/other/hard.bin"; os.makedirs(T + "/other", exist_ok=True)
r = V.remove_dup(A, A, roots=[R], other_roots=[R], receipt=RC, authority="t")
check("RED the 'duplicate' is the file itself: kept", (not r["ok"]) and os.path.exists(A))
mk(B, D)
r = V.remove_dup(A, B, roots=[R], other_roots=[T + "/elsewhere"], receipt=RC, authority="t")
check("RED duplicate outside the allowed duplicate roots: kept", (not r["ok"]) and os.path.exists(A))

# ruled, no-copy path (#2459 F1: a ruling id that is a mail id + a PIN on the plan the lead ruled on)
MAN = T + "/m/manifest.jsonl"
g1 = mk(R + "/g/1.zst", b"x" * 3000); g2 = mk(R + "/g/2.zst", b"y" * 3000); g3 = mk(R + "/g/3.zst", b"z" * 3000)
for badruling in ("", "x", "ok", "lead", "lead 8", "approved"):
    try:
        V.ruled_manifest([g1], MAN, ruling=badruling, note="n", roots=[R], pin="a" * 64); raised = False
    except ValueError:
        raised = True
    check("RED a no-copy delete with ruling %r (not a mail id) is refused" % badruling, raised and not os.path.exists(MAN))
check("ruling_ok accepts 'lead 82451', '82499' and 'lead 82379 (ack of 82377)'", V.ruling_ok("lead 82451") and V.ruling_ok("82499") and V.ruling_ok("lead 82379 (ack of 82377)"))
PLAN3 = V.plan_sha([g1, g2, g3])
check("plan_sha is order independent and names a missing path", PLAN3 == V.plan_sha([g3, g1, g2]) and V.plan_sha([g1]) != V.plan_sha([g1, T + "/nope"]) and len(PLAN3) == 64)
r0, f0 = V.ruled_manifest([g1, g2, g3], MAN, ruling="lead 99999", note="n", roots=[R])
check("RED no pin: NO_PIN, nothing hashed, no manifest written", r0 == [] and f0 and f0[0][1].startswith("NO_PIN") and not os.path.exists(MAN))
r0, f0 = V.ruled_manifest([g1, g2, g3], MAN, ruling="lead 99999", note="n", roots=[R], pin="0" * 64)
check("RED a pin that is not the plan found now: PIN_MISMATCH, nothing written", r0 == [] and f0 and f0[0][1].startswith("PIN_MISMATCH") and not os.path.exists(MAN))
extra = mk(R + "/g/extra.zst", b"e" * 3000)
r0, f0 = V.ruled_manifest([g1, g2, g3, extra], MAN, ruling="lead 99999", note="n", roots=[R], pin=PLAN3)
check("RED a file added after the ruling (the _wiki_del case): the plan differs, PIN_MISMATCH, nothing written", r0 == [] and f0 and f0[0][1].startswith("PIN_MISMATCH") and not os.path.exists(MAN))
os.remove(extra)
PLAN4 = V.plan_sha([g1, g2, g3, fo])
mrows, refused = V.ruled_manifest([g1, g2, g3, fo], MAN, ruling="lead 99999", note="regenerable intermediate", roots=[R], pin=PLAN4)
check("GREEN manifest holds 3 rows (path, size, sha256, mtime, inode, ruling, plan pin), the outside path is refused", len(mrows) == 3 and len(refused) == 1 and all(m["ruling"] == "lead 99999" and m["sha256"] and m["plan_sha256"] == PLAN4 for m in mrows) and len(open(MAN).read().splitlines()) == 3)
open(g2, "ab").write(b"!")
os.remove(g3); open(g3, "wb").write(b"z" * 3000)
seen2 = {}
def spy2(p):
    seen2.setdefault("man", len(open(MAN).read().splitlines())); seen2.setdefault("rc", open(RC).read()); os.remove(p)
res = [V.remove_ruled(m, roots=[R], receipt=RC, remove=spy2) for m in mrows]
check("RED a file appended to after the manifest is kept (stale manifest row)", (not res[1]["ok"]) and os.path.exists(g2))
check("RED a file replaced by a new inode after the manifest is kept", (not res[2]["ok"]) and os.path.exists(g3))
check("GREEN the untouched file is removed; the full manifest and its receipt row were on disk first", res[0]["ok"] and not os.path.exists(g1) and seen2["man"] == 3 and g1.replace("\\", "/") in seen2["rc"])
check("the ruled receipt is labelled ruled-no-copy, never server-verified, and carries the plan pin", rows()[-1]["kind"] == "ruled-no-copy-remove" and "no server or local copy was compared" in rows()[-1]["compared"] and rows()[-1]["plan_sha256"] == PLAN4)
bad_rows = [dict(mrows[0], kind="server-verified"), dict(mrows[0], ruling=""), dict(mrows[0], ruling="x"), dict(mrows[0], sha256="")]
check("RED a row of the wrong kind / without a mail-id ruling / without sha256 is refused", all(not V.remove_ruled(b, roots=[R], receipt=RC)["ok"] for b in bad_rows))
h1 = mk(R + "/h/1.zst", b"h" * 3000)
hrows, _ = V.ruled_manifest([h1], T + "/m/h.jsonl", ruling="lead 99999", note="n", roots=[R], pin=V.plan_sha([h1]))
unp = V.remove_ruled(dict(hrows[0], plan_sha256=None, pinned_by=None), roots=[R], receipt=RC)
check("RED F1 a manifest row with no pin is refused (UNPINNED), the file stays", (not unp["ok"]) and "UNPINNED" in unp["why"] and os.path.exists(h1))
nrows, _ = V.ruled_manifest([h1], T + "/m/h2.jsonl", ruling="lead 99999", note="n", roots=[R], pinned_by="expect-dirs sha256 abc")
check("GREEN a named pin (pinned_by) is accepted and recorded in the row", len(nrows) == 1 and nrows[0]["pinned_by"] == "expect-dirs sha256 abc" and nrows[0]["plan_sha256"] is None and V.remove_ruled(nrows[0], roots=[R], receipt=RC)["ok"] and not os.path.exists(h1))
check("pins_from_argv: NAME=SHA and a bare SHA", V.pins_from_argv(["--go", "--manifest-sha256", "pg=AB", "--manifest-sha256", "CD"]) == {"pg": "ab", "": "cd"})

# F3: the file is replaced after the hash and the receipt fsync, before the remove (same size, same mtime, new inode)
orig_rcp = V._receipt
def swapper(path_):
    def f(rc, row):
        orig_rcp(rc, row)
        st = os.stat(path_); os.remove(path_); open(path_, "wb").write(b"B" * st.st_size); os.utime(path_, ns=(st.st_atime_ns, st.st_mtime_ns))
    return f
f4 = mk(R + "/t/f4.bin", D); called = []
V._receipt = swapper(f4)
r = V.remove_verified(f4, "r", "x/f4", reader=reader_for({("r", "x/f4"): (len(D), sha(D))}), remove=lambda p: called.append(p), **KW)
V._receipt = orig_rcp
check("RED F3 server path: file replaced after the receipt (same size+mtime, new inode): kept, remove never called, an -aborted row is written", (not r["ok"]) and os.path.exists(f4) and not called and "changed after verification" in r["why"] and rows()[-1]["kind"] == "server-verified-aborted")
a4 = mk(R + "/t/a4.bin", D); b4 = mk(T + "/other/b4.bin", D); called = []
V._receipt = swapper(a4)
r = V.remove_dup(a4, b4, remove=lambda p: called.append(p), **KD)
V._receipt = orig_rcp
check("RED F3 duplicate path: file replaced after the receipt: kept, remove never called", (not r["ok"]) and os.path.exists(a4) and not called and rows()[-1]["kind"] == "local-duplicate-aborted")
k4 = mk(R + "/t/k4.bin", b"k" * 3000); krow, _ = V.ruled_manifest([k4], T + "/m/k.jsonl", ruling="lead 99999", note="n", roots=[R], pin=V.plan_sha([k4])); called = []
V._receipt = swapper(k4)
r = V.remove_ruled(krow[0], roots=[R], receipt=RC, remove=lambda p: called.append(p))
V._receipt = orig_rcp
check("RED F3 ruled path: file replaced after the receipt: kept, remove never called", (not r["ok"]) and os.path.exists(k4) and not called and rows()[-1]["kind"] == "ruled-no-copy-remove-aborted")

# F4: a locked or vanished file while hashing is a named refusal, never a traceback
f5 = mk(R + "/t/f5.bin", D); orig_sha = V.sha256_file
def locked(p): raise PermissionError(13, "locked")
V.sha256_file = locked
try:
    r = V.remove_verified(f5, "r", "x/f5", reader=reader_for({("r", "x/f5"): (len(D), sha(D))}), **KW); exc = None
except Exception as e:
    r = None; exc = e
V.sha256_file = orig_sha
check("RED F4 a locked file (sha256 raises PermissionError): refused with 'hash failed: PermissionError', no exception, file kept", exc is None and r and (not r["ok"]) and r["why"] == "hash failed: PermissionError" and os.path.exists(f5))
def vanishes(p):
    h = orig_sha(p); os.remove(p); return h
V.sha256_file = vanishes
try:
    r = V.remove_verified(f5, "r", "x/f5", reader=reader_for({("r", "x/f5"): (len(D), sha(D))}), **KW); exc = None
except Exception as e:
    r = None; exc = e
V.sha256_file = orig_sha
check("RED F4 the file vanishes while it is hashed: 'stat failed after hashing: FileNotFoundError', no exception", exc is None and r and (not r["ok"]) and r["why"] == "stat failed after hashing: FileNotFoundError")
f5 = mk(R + "/t/f5.bin", D); f6 = mk(R + "/t/f6.bin", D)
V.sha256_file = locked
try:
    r2 = V.remove_dup(f5, f6, roots=[R], other_roots=[R], receipt=RC, authority="t"); exc = None
except Exception as e:
    r2 = None; exc = e
try:
    rm, rf = V.ruled_manifest([f5], T + "/m/f5.jsonl", ruling="lead 99999", note="n", roots=[R], pin=V.plan_sha([f5])); exc2 = None
except Exception as e:
    rm = rf = None; exc2 = e
V.sha256_file = orig_sha
check("RED F4 the duplicate and ruled paths also name a locked file instead of raising", exc is None and r2 and (not r2["ok"]) and "hash failed" in r2["why"] and exc2 is None and rm == [] and rf and "hash failed: PermissionError" in rf[0][1])

# dry run: every check runs, nothing is written or removed
fd = mk(R + "/dry/d.bin", D); n_rc = len(rows())
r = V.remove_verified(fd, "r", "x/d", reader=reader_for({("r", "x/d"): (len(D), sha(D))}), dry=True, **KW)
check("GREEN dry run on a verified file: ok but the file stays and no receipt row is written", r["ok"] and r.get("dry") and os.path.exists(fd) and len(rows()) == n_rc)
r = V.remove_verified(fd, "r", "x/d", reader=reader_for({("r", "x/d"): (len(D), sha(bytes(bad)))}), dry=True, **KW)
check("RED dry run still refuses a same-size corrupt upload", (not r["ok"]) and os.path.exists(fd))
shutil.rmtree(T, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
