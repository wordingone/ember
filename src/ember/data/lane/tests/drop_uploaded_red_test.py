# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green test for drop_uploaded.drop_pack: a set's local shards/objects are removed only when the server holds the same bytes, a receipt row exists BEFORE each remove, and nothing else is touched.
Runs under a throwaway dir; the server is an injected dict."""
import os, sys, json, hashlib, tempfile, shutil
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import drop_uploaded as D
ok = True


def chk(n, c):
    global ok
    ok = ok and bool(c); print(("PASS " if c else "FAIL ") + n)


R = tempfile.mkdtemp(prefix="du-red-"); L = R + "/packed/p1"; RC = R + "/receipts.jsonl"
try:
    for s in ("shards", "objects"): os.makedirs(f"{L}/{s}")
    def mk(rel, data): open(f"{L}/{rel}", "wb").write(data); return hashlib.sha256(data).hexdigest()
    sa = mk("shards/a.bin", b"A" * 100); sb = mk("shards/b.bin", b"B" * 100); sc = mk("shards/c.bin", b"C" * 100); sd = mk("shards/d.bin", b"D" * 100); se = mk("objects/e.zst", b"E" * 100); sl = mk("shards/linked.bin", b"L" * 100)
    for keep in ("docs-index.jsonl.zst", "ledger.jsonl", "receipt.json", "intake.json", "source-manifest.jsonl"): open(f"{L}/{keep}", "w").write("keep")
    os.link(f"{L}/shards/linked.bin", R + "/union-link.bin")
    srv = {"text/p1/shards/a.bin": (100, sa), "text/p1/shards/b.bin": (101, sb), "text/p1/shards/c.bin": (100, "0" * 64), "text/p1/objects/e.zst": (100, se), "text/p1/shards/linked.bin": (100, sl)}   # d.bin absent on server
    seen = []
    def rm(p):
        chk("RED receipt row for %s exists BEFORE the remove" % os.path.basename(p), any(json.loads(l)["path"].endswith(os.path.basename(p)) for l in open(RC)))
        seen.append(p); os.remove(p)
    dry = D.drop_pack(L, "r", "text/p1", srv=srv, go=False, receipt=RC, remove=rm)
    chk("GREEN dry run removes nothing and writes no receipt", all(os.path.exists(f"{L}/{x}") for x in ("shards/a.bin", "objects/e.zst")) and not os.path.exists(RC) and dry["dropped_files"] == 2)
    res = D.drop_pack(L, "r", "text/p1", srv=srv, go=True, receipt=RC, remove=rm)
    chk("GREEN matching shard + object removed", not os.path.exists(f"{L}/shards/a.bin") and not os.path.exists(f"{L}/objects/e.zst") and res["dropped_files"] == 2 and res["dropped_bytes"] == 200)
    chk("RED size mismatch (101 vs 100) kept", os.path.exists(f"{L}/shards/b.bin"))
    chk("RED sha mismatch kept", os.path.exists(f"{L}/shards/c.bin"))
    chk("RED not on the server kept", os.path.exists(f"{L}/shards/d.bin"))
    chk("RED hard-linked file (in the training catalog union) kept", os.path.exists(f"{L}/shards/linked.bin") and os.path.exists(R + "/union-link.bin"))
    chk("GREEN index/ledger/receipt/intake/source-manifest never touched", all(open(f"{L}/{k}").read() == "keep" for k in ("docs-index.jsonl.zst", "ledger.jsonl", "receipt.json", "intake.json", "source-manifest.jsonl")))
    chk("GREEN the kept list names the four reasons", sorted(w for _, w in res["kept"]) == sorted(["no server copy of equal size", "sha mismatch", "no server copy of equal size", "nlink>1 (in the training catalog union)"]))
    chk("GREEN receipt rows carry the ack and the server sha", all("lead 82379" in json.loads(l)["ack"] and len(json.loads(l)["sha256"]) == 64 for l in open(RC)))
    src = open(os.path.join(HERE, "loops", "tick.py"), encoding="utf-8").read()
    chk("GREEN tick.py upload() calls drop_uploaded for a set the moment it is VERIFIED", "drop_uploaded" in src and "VERIFIED" in src)
finally:
    shutil.rmtree(R, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
