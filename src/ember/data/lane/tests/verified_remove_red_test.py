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

# ruled, no-copy path
MAN = T + "/m/manifest.jsonl"
g1 = mk(R + "/g/1.zst", b"x" * 3000); g2 = mk(R + "/g/2.zst", b"y" * 3000); g3 = mk(R + "/g/3.zst", b"z" * 3000)
try:
    V.ruled_manifest([g1], MAN, ruling="", note="n", roots=[R]); raised = False
except ValueError:
    raised = True
check("RED a no-copy delete without a ruling id is refused", raised and not os.path.exists(MAN))
mrows, refused = V.ruled_manifest([g1, g2, g3, fo], MAN, ruling="lead 99999", note="regenerable intermediate", roots=[R])
check("GREEN manifest holds 3 rows (path, size, sha256, mtime, inode, ruling), the outside path is refused", len(mrows) == 3 and len(refused) == 1 and all(m["ruling"] == "lead 99999" and m["sha256"] for m in mrows) and len(open(MAN).read().splitlines()) == 3)
open(g2, "ab").write(b"!")
os.remove(g3); open(g3, "wb").write(b"z" * 3000)
seen2 = {}
def spy2(p):
    seen2.setdefault("man", len(open(MAN).read().splitlines())); seen2.setdefault("rc", open(RC).read()); os.remove(p)
res = [V.remove_ruled(m, roots=[R], receipt=RC, remove=spy2) for m in mrows]
check("RED a file appended to after the manifest is kept (stale manifest row)", (not res[1]["ok"]) and os.path.exists(g2))
check("RED a file replaced by a new inode after the manifest is kept", (not res[2]["ok"]) and os.path.exists(g3))
check("GREEN the untouched file is removed; the full manifest and its receipt row were on disk first", res[0]["ok"] and not os.path.exists(g1) and seen2["man"] == 3 and g1.replace("\\", "/") in seen2["rc"])
check("the ruled receipt is labelled ruled-no-copy, never server-verified", rows()[-1]["kind"] == "ruled-no-copy-remove" and "no server or local copy was compared" in rows()[-1]["compared"])
bad_rows = [dict(mrows[0], kind="server-verified"), dict(mrows[0], ruling=""), dict(mrows[0], sha256="")]
check("RED a row of the wrong kind / without ruling / without sha256 is refused", all(not V.remove_ruled(b, roots=[R], receipt=RC)["ok"] for b in bad_rows))

# dry run: every check runs, nothing is written or removed
fd = mk(R + "/dry/d.bin", D); n_rc = len(rows())
r = V.remove_verified(fd, "r", "x/d", reader=reader_for({("r", "x/d"): (len(D), sha(D))}), dry=True, **KW)
check("GREEN dry run on a verified file: ok but the file stays and no receipt row is written", r["ok"] and r.get("dry") and os.path.exists(fd) and len(rows()) == n_rc)
r = V.remove_verified(fd, "r", "x/d", reader=reader_for({("r", "x/d"): (len(D), sha(bytes(bad)))}), dry=True, **KW)
check("RED dry run still refuses a same-size corrupt upload", (not r["ok"]) and os.path.exists(fd))
shutil.rmtree(T, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
