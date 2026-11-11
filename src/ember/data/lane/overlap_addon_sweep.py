# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#2449 / #1947: every packed/<name> vs the ADD-ON held-out index (A-heldout-2, B-heldout-1, F-heldout-1, H-heldout-1; build_heldout_index_addon.py), unsampled (HS_SAMP=1, the same signature as the full index).
Code/GitHub packs (name contains github or stack) are read exhaustively; every other pack by a deterministic stride sample of up to SWEEP_DOCS docs (default 200000). A doc is a hit when at least one of its sentence hashes is in the index; hits are named (first 20).
CPU-only, read-only, 4 worker processes (one pack each). Receipt (resumable per pack AND per index): logs/overlap-addon-sweep-20261110.json.
Every row carries index_id = index file size + mtime_ns; a row from another index (or with none) is stale: it is dropped and its pack swept again, so a rebuilt index never keeps old rows.
A pack with a receipt but no object files gets a zero row (files: 0), never no row.
Usage: python scripts/overlap_addon_sweep.py [--only NAME ...]"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, glob, time
os.environ["HS_SAMP"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, overlap_gate as G
from common import gram_hashes, overlap
from multiprocessing import Pool
OUT = (LANE_ROOT + "/logs/overlap-addon-sweep-20261110.json"); CAP = int(os.environ.get("SWEEP_DOCS", "200000"))
IDXF = (LANE_ROOT + "/heldout-index-full/addon/heldout-sent-xxh64-full-addon-ABFH.npy")
def index_identity(path=IDXF):
    """size + mtime_ns of the add-on index file: the resume key's second half (a rebuilt index changes it)."""
    st = os.stat(path); return "%d-%d" % (st.st_size, st.st_mtime_ns)
def zero_row(idx_id):
    return dict(files=0, docs_total=0, docs_checked=0, stride=1, exhaustive=False, docs_heldout_hit=0, hits=[], secs=0, index_id=idx_id)
def fresh_rows(res, idx_id):
    """-> (rows for THIS index, names of stale rows). A row from another index, or without index_id, is not evidence about this one."""
    kept = {k: v for k, v in res.items() if isinstance(v, dict) and v.get("index_id") == idx_id}
    return kept, [k for k in res if k not in kept]
def plan(dirs, res, only, idx_id):
    """-> (todo dirs, zero rows {name: row}). `res` must already hold only rows for this index. A pack is skipped when it has a row, is not in --only, or has no receipt (still being packed)."""
    todo = []; zero = {}
    for d in dirs:
        name = os.path.basename(d)
        if name in res or (only and name not in only) or not os.path.exists(d + "/receipt.json"): continue
        if glob.glob(d + "/objects/*.jsonl.zst"): todo.append(d)
        else: zero[name] = zero_row(idx_id)
    return todo, zero
def one(d):
    name = os.path.basename(d); t0 = time.time(); idx = np.load(IDXF, mmap_mode="r")
    exhaustive = any(k in name for k in ("github", "stack")); total = sum(1 for _ in G.iter_objects(d)); stride = 1 if exhaustive else max(1, total // CAP)
    n = hh = 0; hits = []
    for i, r in enumerate(G.iter_objects(d)):
        if i % stride: continue
        n += 1; o = overlap(idx, gram_hashes(r["text"]))
        if o: hh += 1; hits.append((G.ns_key(name, r["id"]), int(o)))
    return name, dict(files=len(glob.glob(d + "/objects/*.jsonl.zst")), docs_total=total, docs_checked=n, stride=stride, exhaustive=exhaustive, docs_heldout_hit=hh, hits=sorted(hits, key=lambda x: -x[1])[:20], secs=round(time.time() - t0))
def write_receipt(res):
    """temp + os.replace: a crash never leaves a half-written receipt (a torn file would restart the whole sweep)."""
    with open(OUT + ".tmp", "w") as f: json.dump(res, f, indent=1)
    os.replace(OUT + ".tmp", OUT)
def main():
    only = sys.argv[sys.argv.index("--only") + 1:] if "--only" in sys.argv else None
    idx_id = index_identity()
    res = json.load(open(OUT)) if os.path.exists(OUT) else {}
    res, stale = fresh_rows(res, idx_id)      # rows from another index (or from before index_id existed) are dropped and their packs swept again
    dirs = [d.replace(chr(92), "/").rstrip("/") for d in sorted(glob.glob((LANE_ROOT + "/packed/*/")))]
    packs, zero = plan(dirs, res, only, idx_id); res.update(zero)
    print(len(packs), "packs to sweep;", len(zero), "zero rows (no object files);", len(stale), "stale rows dropped (index changed)", flush=True)
    if zero or stale: write_receipt(res)
    with Pool(4) as pool:
        for name, r in pool.imap_unordered(one, packs):
            r["index_id"] = idx_id; res[name] = r; write_receipt(res); print(name, r["docs_total"], r["docs_checked"], r["docs_heldout_hit"], r["secs"], "s", flush=True)
    print("SWEEP DONE", len(res), "packs; heldout-hit docs", sum(v["docs_heldout_hit"] for v in res.values()), flush=True)


if __name__ == "__main__":
    main()
