# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red for PR 2467 review r1 note 6 (build_heldout_index_addon.py, overlap_addon_sweep.py): python tests/addon_index_red_test.py
 1) a write-gate refusal inside a pool worker is an ordinary exception (WriteGateRefused), not SystemExit (SystemExit kills the worker and the pool waits forever); main() stops, exits non-zero, and returns in bounded time
 2) every set in SETS gets a row in addon-counts.json; a set with no files is a zero row (files: 0)
 3) the sweep's resume key includes the index identity (size + mtime_ns): rows from another index, or with no index_id, are stale and their packs are swept again
 4) a pack with a receipt and no object files gets a zero row (files: 0); a pack with no receipt (still being packed) gets nothing
Temp lane only (EMBER_LANE_ROOT / EMBER_M_ROOT are pointed at a temp dir before import); thread pools stand in for process pools so the stubbed write gate applies. Prints ALL PASS."""
import os, sys, json, tempfile, shutil, threading, time
TMP = tempfile.mkdtemp(prefix="addon-red-")
os.environ["EMBER_LANE_ROOT"] = TMP + "/lane"; os.environ["EMBER_M_ROOT"] = TMP + "/m"
for _k, _v in (("EMBER_SEAT_LEAD", "lead"), ("EMBER_SEAT_TRAIN", "train"), ("EMBER_SEAT_DATA", "data"), ("EMBER_HF_RAW_REPO", "x/raw-private"), ("EMBER_HF_TRAIN_REPO", "x/train-private")): os.environ.setdefault(_k, _v)
for d in ("lane/logs", "lane/packed", "lane/heldout-index-full/addon", "m/data/corpus"): os.makedirs(TMP + "/" + d)
HERE = os.path.dirname(os.path.abspath(__file__)); LANE = os.path.dirname(HERE)
sys.path.insert(0, LANE)
from multiprocessing.pool import ThreadPool
import numpy as np
import reserve_plan
import build_heldout_index_addon as bia
import overlap_addon_sweep as sw

ok = True; nfail = 0
def chk(msg, cond):
    global ok, nfail
    print(("PASS " if cond else "FAIL ") + msg); ok = ok and bool(cond); nfail += (not cond)

SENT = "the quick brown fox jumps over the lazy dog while the cat watches quietly from the old wooden fence. "


def corpus(sets_with_files):
    c = TMP + "/m/data/corpus"
    for s in bia.SETS:
        shutil.rmtree(c + "/" + s, ignore_errors=True); os.makedirs(c + "/" + s)
    for s in sets_with_files: open(c + "/%s/doc.txt" % s, "w").write(SENT * 3)
    shutil.rmtree(bia.OUT, ignore_errors=True); os.makedirs(bia.PARTS)


def run_main(timeout=25):
    """bia.main() on a thread pool, in a thread of its own so a hang is a FAIL, not a stuck test. -> (finished, exit code or None)"""
    res = {}
    def target():
        try: bia.main(); res["code"] = 0
        except SystemExit as e: res["code"] = e.code
        except BaseException as e: res["code"] = "%s: %s" % (type(e).__name__, e)
    t = threading.Thread(target=target, daemon=True); t.start(); t.join(timeout)
    return (not t.is_alive()), res.get("code")


try:
    bia.Pool = ThreadPool
    bia.C = TMP + "/m/data/corpus"; bia.OUT = TMP + "/lane/heldout-index-full/addon"; bia.PARTS = bia.OUT + "/parts"
    real_gate = reserve_plan.write_gate
    # 1) refusal in a worker
    reserve_plan.write_gate = lambda *a, **k: False
    corpus(["A-heldout-2"])
    unit = ("A-heldout-2", "files", [bia.C + "/A-heldout-2/doc.txt"])
    try: bia.work(unit); exc = None
    except BaseException as e: exc = e
    chk("1) work() on a write-gate refusal raises an ordinary Exception (%s), not SystemExit" % (type(exc).__name__,), isinstance(exc, Exception) and type(exc).__name__ == "WriteGateRefused" if hasattr(bia, "WriteGateRefused") else False)
    fin, code = run_main()
    chk("1) main() returns in bounded time on a worker refusal (no hang)", fin)
    chk("1) main() exits non-zero with the refusal text (%r)" % (str(code)[:60],), fin and isinstance(code, str) and "write_gate refused" in code)
    # 2) zero rows
    reserve_plan.write_gate = lambda *a, **k: True
    corpus(["A-heldout-2"])
    fin, code = run_main()
    cf = bia.OUT + "/addon-counts.json"
    sets = json.load(open(cf))["sets"] if os.path.isfile(cf) else {}
    chk("2) main() finished OK (code %r)" % (code,), fin and code == 0)
    chk("2) every set has a row (%s)" % sorted(sets), sorted(sets) == sorted(bia.SETS))
    chk("2) a set with no files is a zero row: files 0, files_read 0", all(sets.get(s, {}).get("files") == 0 and sets[s]["files_read"] == 0 for s in ("B-heldout-1", "F-heldout-1", "H-heldout-1") if s in sets) and "B-heldout-1" in sets)
    chk("2) the set with a file counts it (files 1)", sets.get("A-heldout-2", {}).get("files") == 1)
    reserve_plan.write_gate = real_gate

    # 3) resume key = pack name + index identity
    np.save(sw.IDXF, np.arange(10, dtype=np.uint64)); id1 = sw.index_identity()
    rows = {"p1": dict(index_id=id1, docs_total=5), "p2": dict(index_id="999-1"), "p3": dict(docs_total=1)}
    kept, stale = sw.fresh_rows(rows, id1)
    chk("3) rows for this index kept; rows from another index or without index_id are stale", sorted(kept) == ["p1"] and sorted(stale) == ["p2", "p3"])
    np.save(sw.IDXF, np.arange(11, dtype=np.uint64)); id2 = sw.index_identity()
    chk("3) a rebuilt index (different size) has a different identity", id1 != id2)
    kept2, stale2 = sw.fresh_rows(rows, id2)
    chk("3) after the rebuild no old row is kept (p1 is stale too)", kept2 == {} and sorted(stale2) == ["p1", "p2", "p3"])
    t0 = os.stat(sw.IDXF); os.utime(sw.IDXF, ns=(t0.st_atime_ns, t0.st_mtime_ns + 5_000_000_000)); id3 = sw.index_identity()
    chk("3) a rebuilt index of the same size but a new mtime has a different identity", id3 != id2)

    # 4) zero row for a pack with no files
    P = TMP + "/lane/packed"
    for n, receipt, objs in (("with_objs", True, True), ("empty_pack", True, False), ("unfinished", False, False)):
        os.makedirs(P + "/%s/objects" % n)
        if receipt: open(P + "/%s/receipt.json" % n, "w").write("{}")
        if objs: open(P + "/%s/objects/o0.jsonl.zst" % n, "wb").write(b"x")
    dirs = [P + "/" + n for n in ("empty_pack", "unfinished", "with_objs")]
    todo, zero = sw.plan(dirs, {}, None, id3)
    chk("4) pack with objects is swept, empty pack gets a zero row (files: 0), unfinished pack (no receipt) gets nothing", [os.path.basename(d) for d in todo] == ["with_objs"] and list(zero) == ["empty_pack"] and zero["empty_pack"]["files"] == 0 and zero["empty_pack"]["index_id"] == id3)
    todo2, zero2 = sw.plan(dirs, {"with_objs": {}, "empty_pack": zero["empty_pack"]}, None, id3)
    chk("4) packs that already have a row for this index are not redone", todo2 == [] and zero2 == {})
    todo3, zero3 = sw.plan(dirs, {}, ["with_objs"], id3)
    chk("4) --only limits both the sweep and the zero rows", [os.path.basename(d) for d in todo3] == ["with_objs"] and zero3 == {})
finally:
    print("ALL PASS" if ok else "FAILED (%d checks failed)" % nfail)
    sys.stdout.flush()
    shutil.rmtree(TMP, ignore_errors=True)
    os._exit(0 if ok else 1)
