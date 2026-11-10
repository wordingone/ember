# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Add-on to the frozen full held-out hash index (#2449, #1947): the held-out sets build_heldout_index_full.py never read.
The full index covers D-heldout-2, E-heldout-*, I-heldout-1 only. This builds the same signature (common.gram_hashes with HS_SAMP=1: xxh64 of every normalized sentence/line of >= MINW words) for the text content of
A-heldout-2, B-heldout-1, F-heldout-1 and H-heldout-1 (C-heldout-1 and J-heldout-1 hold one binary each: listed, not text-indexed here).
Skips metadata only: _manifests/, manifest.jsonl, .gitattributes. Text rule for loose and tarred files: not larger than 8 MiB and no NUL byte in the first 8 KiB; decoded utf-8 with errors ignored. JSON/JSONL contribute every string value; parquet every string column.
Out: heldout-index-full/addon/heldout-sent-xxh64-full-addon-ABFH.npy (sorted unique uint64), heldout-index-full/addon/addon-counts.json (per set: files read, files skipped as binary or too large, hashes), parts/ kept for audit.
Read-only on the corpus. CPU only: 4 worker processes. Usage: python scripts/build_heldout_index_addon.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, M_ROOT
import os, sys, io, json, glob, time, tarfile, hashlib
os.environ["HS_SAMP"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from multiprocessing import Pool
from common import gram_hashes
C = (M_ROOT + "/data/corpus"); OUT = (LANE_ROOT + "/heldout-index-full/addon"); PARTS = OUT + "/parts"
MAXB = 8 << 20; SKIP_DIRS = {"_manifests"}; SKIP_FILES = {"manifest.jsonl", ".gitattributes"}
SETS = ["A-heldout-2", "B-heldout-1", "F-heldout-1", "H-heldout-1"]
def strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values(): yield from strings(v)
    elif isinstance(o, list):
        for v in o: yield from strings(v)
def texts_of(name, data):
    """-> list of text strings from one file's bytes, or None when the file is binary / too large"""
    if len(data) > MAXB or b"\x00" in data[:8192]: return None
    s = data.decode("utf-8", errors="ignore"); low = name.lower()
    if low.endswith(".json"):
        try: return list(strings(json.loads(s)))
        except Exception: return [s]
    if low.endswith(".jsonl"):
        out = []
        for line in s.splitlines():
            try: out += list(strings(json.loads(line)))
            except Exception: out.append(line)
        return out
    return [s]
def parquet_texts(p):
    import pyarrow.parquet as pq
    pf = pq.ParquetFile(p); cols = [f.name for f in pf.schema_arrow if str(f.type) in ("string", "large_string")]
    for b in pf.iter_batches(columns=cols, batch_size=2000):
        for c in b.columns:
            for t in c.to_pylist():
                if t: yield t
def work(unit):
    sset, kind, path = unit; parts = []; read = skipped = 0
    def add(ts):
        for t in ts:
            h = gram_hashes(t)
            if h.size: parts.append(h)
    if kind == "files":
        for p in path:
            if p.endswith(".parquet"):
                add(parquet_texts(p)); read += 1; continue
            d = open(p, "rb").read(); t = texts_of(p, d)
            if t is None: skipped += 1
            else: add(t); read += 1
    else:   # tar.gz
        with tarfile.open(path, "r:gz") as tf:
            for m in tf:
                if not m.isfile(): continue
                if m.size > MAXB: skipped += 1; continue
                t = texts_of(m.name, tf.extractfile(m).read())
                if t is None: skipped += 1
                else: add(t); read += 1
    arr = np.unique(np.concatenate(parts)) if parts else np.empty(0, np.uint64)
    tag = sset + "-" + (os.path.basename(path) if kind == "tar" else hashlib.sha1("|".join(path).encode()).hexdigest()[:10])
    out = os.path.join(PARTS, tag + ".npy")
    import reserve_plan
    if not reserve_plan.write_gate("build_heldout_index_addon.py part", int(arr.nbytes) + (64 << 20)): sys.exit("write_gate refused: B: below the reserve floor for the whole gate cap: build_heldout_index_addon.py part not writing")      # lead 82324 / 82669
    with open(out + ".tmp.npy", "wb") as _pf: np.lib.format.write_array(_pf, arr)      # same bytes as np.save, in a form the write-gate lint can see
    os.replace(out + ".tmp.npy", out)
    return sset, tag, read, skipped, int(arr.size)
def units():
    u = []
    for s in SETS:
        root = C + "/" + s
        if s == "H-heldout-1":
            u += [(s, "tar", p) for p in sorted(glob.glob(root + "/*.tar.gz"))]
            continue
        fl = []
        for dp, dn, fn in os.walk(root):
            dn[:] = [d for d in dn if d not in SKIP_DIRS]
            fl += [os.path.join(dp, f).replace("\\", "/") for f in fn if f not in SKIP_FILES]
        fl.sort()
        for i in range(0, len(fl), 200): u.append((s, "files", fl[i:i + 200]))
    return u
if __name__ == "__main__":
    os.makedirs(PARTS, exist_ok=True); us = units(); print(len(us), "units", flush=True); t0 = time.time(); stats = {}
    with Pool(4) as pool:
        for i, (s, tag, read, skipped, n) in enumerate(pool.imap_unordered(work, us)):
            st = stats.setdefault(s, dict(files_read=0, files_skipped_binary_or_large=0, part_hashes=0)); st["files_read"] += read; st["files_skipped_binary_or_large"] += skipped; st["part_hashes"] += n
            if i % 20 == 0: print(i + 1, "/", len(us), tag, read, skipped, n, round(time.time() - t0), "s", flush=True)
    fs = [os.path.join(PARTS, f) for f in os.listdir(PARTS) if f.endswith(".npy") and ".tmp" not in f]
    big = np.concatenate([np.load(f) for f in fs]) if fs else np.empty(0, np.uint64); big.sort()
    idx = big[np.concatenate([[True], big[1:] != big[:-1]])] if big.size else big
    dst = OUT + "/heldout-sent-xxh64-full-addon-ABFH.npy"
    import reserve_plan
    if not reserve_plan.write_gate("build_heldout_index_addon.py index", int(idx.nbytes) + (64 << 20)): sys.exit("write_gate refused: B: below the reserve floor for the whole gate cap: build_heldout_index_addon.py index not writing")      # lead 82324 / 82669
    with open(dst, "wb") as _pf: np.lib.format.write_array(_pf, idx)      # same bytes as np.save, in a form the write-gate lint can see
    json.dump(dict(sets=stats, unique_hashes=int(idx.size), not_text_indexed=["C-heldout-1 (one binary)", "J-heldout-1 (one binary)"], hash="common.gram_hashes, HS_SAMP=1", max_file_bytes=MAXB), open(OUT + "/addon-counts.json", "w"), indent=1)
    print("DONE", idx.size, stats, round(time.time() - t0), "s", flush=True)
