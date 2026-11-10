# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green for ckpt_backup.delete_refuted (#2454): the local delete of a refuted child's weights after the HF upload is decided by a server entry read back NOW (size + LFS sha256) and a local hash computed NOW, not by the upload-time
comparison or any marker. Same-size corrupt upload, no LFS sha256 (the old size-only fallback), missing entry, unreadable server, second hard-link name, a path outside the child dir: all keep the file. Receipt row is on disk before each remove.
Importing the module has no side effects (affinity / mail patch / argv loop moved into main()). Tmp tree, stubbed deps, fake server.
Run: python scripts/tests/ckpt_backup_verify_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import os, sys, json, ast, shutil, hashlib, tempfile, types, importlib.util
HERE = os.path.dirname(os.path.abspath(__file__)); SC = os.path.dirname(HERE)
sys.path.insert(0, SC)
ok = True


def check(label, cond):
    global ok
    ok &= bool(cond); print("PASS" if cond else "FAIL", label)


for name, mod in (("hf_cap", types.ModuleType("hf_cap")), ("mb_send", types.ModuleType("mb_send")), ("ckpt_children", types.ModuleType("ckpt_children"))):
    sys.modules[name] = mod
sys.modules["mb_send"].send = lambda *a, **k: None; sys.modules["hf_cap"].check = lambda *a, **k: True; sys.modules["ckpt_children"].CH = {}
spec = importlib.util.spec_from_file_location("ckpt_backup_under_test", SC + "/ckpt_backup.py"); CB = importlib.util.module_from_spec(spec)
import psutil
aff0 = psutil.Process().cpu_affinity(); spec.loader.exec_module(CB)
check("importing ckpt_backup changes nothing (CPU affinity untouched, no argv loop ran)", psutil.Process().cpu_affinity() == aff0 and hasattr(CB, "main") and hasattr(CB, "_setup"))
tree = ast.parse(open(SC + "/ckpt_backup.py", encoding="utf-8").read())
top_calls = [n for n in tree.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) and ast.unparse(n.value.func) != "sys.path.insert"]
check("no top-level statement calls anything that runs the backup (only definitions and constants at module level)", not top_calls and not [n for n in tree.body if isinstance(n, ast.For)])

SCR = (LANE_ROOT + "/scratch"); os.makedirs(SCR, exist_ok=True)
T = tempfile.mkdtemp(dir=SCR, prefix="ckb-test-").replace("\\", "/"); MB = 1 << 20; sha = lambda b: hashlib.sha256(b).hexdigest()
D = T + "/child"; REPO = CB.REPO; DEST = "checkpoints/abcd1234-HX"
data = {n: os.urandom(MB + 7) + n.encode() for n in ("w1", "w2", "w3", "w4", "w5", "w6")}
files = {}
for n, b in data.items():
    p = f"{D}/objects/{n}.pt"; os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "wb").write(b); files[f"objects/{n}.pt"] = (p, len(b))
small = f"{D}/checkpoint-manifest.json"; open(small, "w").write("{}"); files["checkpoint-manifest.json"] = (small, 2)
corrupt = bytearray(data["w2"]); corrupt[9] ^= 1
SRV = {f"{DEST}/objects/w1.pt": (len(data["w1"]), sha(data["w1"])),
       f"{DEST}/objects/w2.pt": (len(data["w2"]), sha(bytes(corrupt))),
       f"{DEST}/objects/w3.pt": (len(data["w3"]), None),
       f"{DEST}/objects/w5.pt": (len(data["w5"]), sha(data["w5"]))}
hl = T + "/second-name.pt"; os.link(files["objects/w5.pt"][0], hl)
RC = T + "/rc.jsonl"; MAN = T + "/man.jsonl"; seen = []
def spy(p):
    seen.append((p, open(RC).read() if os.path.exists(RC) else "")); os.remove(p)
freed, kept, nrows = CB.delete_refuted("HX", "abcd1234", D, files, {}, DEST, reader=lambda repo, hp: SRV.get(hp), remove=spy, receipt=RC, man=MAN)
left = sorted(os.listdir(D + "/objects"))
check("GREEN w1 (server size + LFS sha256 equal, read back now): deleted", "w1.pt" not in left and freed == len(data["w1"]))
check("RED w2 (same size, server sha256 differs: corrupt upload): kept", "w2.pt" in left)
check("RED w3 (server entry has equal size but no LFS sha256: the old size-only fallback): kept", "w3.pt" in left)
check("RED w4 (no server entry): kept", "w4.pt" in left)
check("RED w5 (second hard-link name exists): kept", "w5.pt" in left and os.path.exists(hl))
check("RED w6 (no server entry, not uploaded): kept; exactly 5 of 6 weights kept with reasons", "w6.pt" in left and len(kept) == 5 and nrows == 6)
check("the small manifest file is never a candidate (< 1 MiB stays local)", os.path.exists(small))
check("the receipt row for w1 was on disk when the remove ran, with both hashes", len(seen) == 1 and f"{D}/objects/w1.pt" in seen[0][1] and json.loads(seen[0][1].splitlines()[0])["server_sha256"] == sha(data["w1"]))
plan = [json.loads(l) for l in open(MAN)]
check("plan rows (all 6 weights) were written to the manifest", len(plan) == 6 and all(r["kind"] == "server-verify" for r in plan))

outside = T + "/outside.pt"; open(outside, "wb").write(data["w1"])
files2 = {"objects/o.pt": (outside, len(data["w1"]))}
f2, k2, n2 = CB.delete_refuted("HX", "abcd1234", D, files2, {}, DEST, reader=lambda repo, hp: (len(data["w1"]), sha(data["w1"])), receipt=RC, man=MAN)
check("RED a file outside the child dir is refused even when the server matches", os.path.exists(outside) and f2 == 0 and "outside" in k2[0][1])
def down(repo, hp): raise __import__("verified_remove").ServerUnreadable("503")
p4 = files["objects/w4.pt"]; f3, k3, n3 = CB.delete_refuted("HX", "abcd1234", D, {"objects/w4.pt": p4}, {}, DEST, reader=down, receipt=RC, man=MAN)
check("RED server unreadable: kept", os.path.exists(p4[0]) and f3 == 0 and "unreadable" in k3[0][1])
src = open(SC + "/ckpt_backup.py", encoding="utf-8").read()
check("source: no bare os.remove call remains in ckpt_backup.py", "os.remove(" not in src.replace("remove=os.remove", ""))
shutil.rmtree(T, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
