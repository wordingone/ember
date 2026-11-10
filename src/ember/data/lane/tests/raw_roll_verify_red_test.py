# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green for raw_roll.roll after #2454 (hf_push / upload_refuse stubbed, fake server injected as `reader`, tmp tree): the local copy is deleted only when the server entry read back NOW has equal size AND an LFS sha256
equal to the local sha256. Same-size corrupt upload, an entry without an LFS sha256 (the old size-only fallback), a missing entry, a second hard-link name, a file outside the allowed root and a failed receipt write all KEEP the file;
the receipt row is on disk before each remove. The roll() signature and return keys that librivox_pilot.py / se_drive.py use (ok, local, path, bytes) are unchanged.
Run: python scripts/tests/raw_roll_verify_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import os, sys, json, shutil, hashlib, tempfile, types, importlib.util
HERE = os.path.dirname(os.path.abspath(__file__)); SC = os.path.dirname(HERE)
sys.path.insert(0, SC)
ok = True
def check(label, cond):
    global ok
    ok &= bool(cond); print("PASS" if cond else "FAIL", label)
calls = []
HP = types.ModuleType("hf_push"); HP.create_commit = lambda api, **kw: (calls.append(kw["commit_message"]) or types.SimpleNamespace(oid="c0ffee")); HP.check_path = lambda p: None
UR = types.ModuleType("upload_refuse"); UR.check = lambda p: None
sys.modules["hf_push"] = HP; sys.modules["upload_refuse"] = UR
spec = importlib.util.spec_from_file_location("raw_roll_under_test", SC + "/raw_roll.py"); RR = importlib.util.module_from_spec(spec); spec.loader.exec_module(RR)
SCR = (LANE_ROOT + "/scratch"); os.makedirs(SCR, exist_ok=True)
T = tempfile.mkdtemp(dir=SCR, prefix="rr-test-").replace("\\", "/"); sha = lambda b: hashlib.sha256(b).hexdigest()
RR.ROOT = T + "/lanedir"; os.makedirs(T + "/lanedir"); os.makedirs(T + "/elsewhere"); RC = T + "/rc/receipts.jsonl"
def mk(p, b): os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "wb").write(b); return p
D = {n: os.urandom(3000) + n.encode() for n in "abcdefg"}
F = {n: mk(f"{T}/lanedir/raw/{n}.mp3", D[n]) for n in "abcdeg"}; F["f"] = mk(f"{T}/elsewhere/f.mp3", D["f"])
bad = bytearray(D["b"]); bad[1] ^= 1
SRV = {"audio/a": (len(D["a"]), sha(D["a"])), "audio/b": (len(D["b"]), sha(bytes(bad))), "audio/c": (len(D["c"]), None), "audio/e": (len(D["e"]), sha(D["e"])), "audio/f": (len(D["f"]), sha(D["f"])), "audio/g": (len(D["g"]), sha(D["g"]))}
hl = T + "/lanedir/second-name.mp3"; os.link(F["e"], hl)
seen = []
def spy(p): seen.append((p, open(RC).read())); os.remove(p)
res = RR.roll([(F[n], "audio/" + n) for n in "abcdef"], reader=lambda repo, hp: SRV.get(hp), remove=spy, receipt=RC)
by = {os.path.basename(r["local"])[0]: r for r in res}
check("the commit funnel was called once (upload unchanged)", len(calls) == 1)
check("GREEN a (equal size + LFS sha256 on the server) is deleted, ok=True", by["a"]["ok"] and not os.path.exists(F["a"]))
check("RED b (same-size corrupt upload): kept, ok=False", (not by["b"]["ok"]) and os.path.exists(F["b"]) and "sha256 mismatch" in by["b"]["why"])
check("RED c (server entry with equal size and no LFS sha256: the old size-only acceptance): kept", (not by["c"]["ok"]) and os.path.exists(F["c"]) and "no LFS sha256" in by["c"]["why"])
check("RED d (no server entry): kept", (not by["d"]["ok"]) and os.path.exists(F["d"]))
check("RED e (a second hard-link name exists): kept", (not by["e"]["ok"]) and os.path.exists(F["e"]))
check("RED f (outside the allowed root): kept even with a matching server entry", (not by["f"]["ok"]) and os.path.exists(F["f"]))
check("the receipt row for a was on disk when the remove ran and carries both hashes + the commit", len(seen) == 1 and json.loads(seen[0][1].splitlines()[0])["local_sha256"] == sha(D["a"]) == json.loads(seen[0][1].splitlines()[0])["server_sha256"] and json.loads(seen[0][1].splitlines()[0])["commit"] == "c0ffee")
check("return keys used by the callers are intact", set(by["a"]) >= {"ok", "local", "path", "bytes", "repo", "commit"} and by["a"]["bytes"] == len(D["a"]))
os.makedirs(T + "/rc-dir", exist_ok=True)
r2 = RR.roll([(F["g"], "audio/g")], reader=lambda repo, hp: SRV.get(hp), receipt=T + "/rc-dir", remove=lambda p: seen.append("CALLED"))
check("RED the receipt cannot be written: file kept and remove not called", (not r2[0]["ok"]) and os.path.exists(F["g"]) and "CALLED" not in seen)
def down(repo, hp): raise VRX("503")
VRX = __import__("verified_remove").ServerUnreadable
r3 = RR.roll([(F["g"], "audio/g")], reader=down, receipt=RC)
check("RED server unreadable after the commit: kept", (not r3[0]["ok"]) and os.path.exists(F["g"]))
import ast
src = open(SC + "/raw_roll.py", encoding="utf-8").read()
check("source: raw_roll.py no longer calls os.remove itself", "os.remove" not in {ast.unparse(n.func) for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)})
shutil.rmtree(T, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
