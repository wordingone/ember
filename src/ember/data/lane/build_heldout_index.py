# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, M_ROOT
import os, sys, glob, json, io, gzip, time, numpy as np
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(__file__))
from common import gram_hashes
import zstandard, pyarrow.parquet as pq
C = (M_ROOT + "/data/corpus")
OUT = (LANE_ROOT + "/heldout-index/parts")
def files():
    f = []
    f += [("zst", p) for p in glob.glob(C + "/D-heldout-2/**/*.jsonl.zst", recursive=True)]
    f += [("gz", p) for p in glob.glob(C + "/E-heldout-*/**/*.json.gz", recursive=True)]
    f += [("pq", p) for p in glob.glob(C + "/I-heldout-1/**/*.parquet", recursive=True)]
    return sorted(f)
def texts(kind, p):
    if kind == "zst":
        with open(p, "rb") as fh:
            for line in io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(fh), encoding="utf-8"):
                yield json.loads(line)["text"]
    elif kind == "gz":
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            for line in fh:
                yield json.loads(line)["text"]
    else:
        pf = pq.ParquetFile(p)
        for b in pf.iter_batches(columns=["text"], batch_size=2000):
            for t in b.column(0).to_pylist():
                yield t
def work(a):
    kind, p = a
    name = kind + "-" + p.replace("\\", "/").replace(C + "/", "").replace("/", "_")
    out = os.path.join(OUT, name + ".npy")
    if os.path.exists(out):
        return name, -1
    parts = []; docs = 0
    for t in texts(kind, p):
        docs += 1
        h = gram_hashes(t)
        if h.size: parts.append(h)
    arr = np.unique(np.concatenate(parts)) if parts else np.empty(0, np.uint64)
    np.save(out + ".tmp.npy", arr); os.replace(out + ".tmp.npy", out)
    return name, docs
if __name__ == "__main__":
    fl = files(); print(len(fl), "files", flush=True); t = time.time()
    with Pool(6) as pool:
        for i, (n, d) in enumerate(pool.imap_unordered(work, fl)):
            print(i + 1, n, d, round(time.time() - t), "s", flush=True)
    print("MERGE", flush=True)
    arrs = [np.load(os.path.join(OUT, f)) for f in os.listdir(OUT) if f.endswith(".npy") and ".tmp" not in f]
    idx = np.unique(np.concatenate(arrs))
    np.save((LANE_ROOT + "/heldout-index/heldout-13gram-mod32.npy"), idx)
    print("DONE index size", idx.size, flush=True)
