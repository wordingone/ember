# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Sentence-level overlap of a docs jsonl.zst against ALL arXiv PDFs found in heldout-named corpus dirs (lead 81194 item 1).
Usage: heldout_pdf_overlap.py IN.jsonl.zst OUT.jsonl.zst HASHES_OUT.npy [WORKERS=4]
1) walk heldout dirs, pypdf-extract every PDF (deterministic, NFKC, same as pdf_extract.py but NO admit rule: every sentence counts as heldout),
2) hash eligible sentences (same segmenter as scrub.py), save sorted unique uint64 array (reusable as an extra heldout index),
3) scrub IN: drop doc if >25% eligible sentences hit, else remove hit sentences, drop <120 words. Prints stats."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import M_ROOT
import sys, os, re, io, json, time, unicodedata
import numpy as np, xxhash, zstandard, pypdf
from multiprocessing import Pool
from tokenizers import Tokenizer
IN, OUT, HOUT = sys.argv[1], sys.argv[2], sys.argv[3]; NW = int(sys.argv[4]) if len(sys.argv) > 4 else 4
SPLIT = re.compile(r"((?<=[.!?])\s+|\n+)"); WS = re.compile(r"\s+"); MINW = 8
def seg_hash(seg):
    n = WS.sub(" ", seg.lower()).strip()
    return None if n.count(" ") < MINW - 1 else xxhash.xxh64_intdigest(n)
def pdf_hashes(p):
    try:
        r = pypdf.PdfReader(p); txt = "\n".join((pg.extract_text() or "") for pg in r.pages[:300])
    except Exception: return None
    txt = unicodedata.normalize("NFKC", txt.encode("utf-8", "ignore").decode("utf-8", "ignore"))
    txt = re.sub(r"[ \t]+\n", "\n", txt); txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
    hs = [seg_hash(s) for s in SPLIT.split(txt)[0::2]]
    return np.array([h for h in hs if h is not None], dtype=np.uint64)
def main():
    t0 = time.time(); files = []
    roots = [(M_ROOT + "/data/corpus"), (M_ROOT + "/ember-data/objects"), (M_ROOT + "/ember-data/raw"), (M_ROOT + "/ember-data/recovered-20260805"), (M_ROOT + "/ember-data/catalog-train-cache"), (M_ROOT + "/ember-data/custody")]
    for r in roots:
        for dp, _, fs in os.walk(r):
            if "heldout" in dp.lower().replace("\\", "/"):
                files += [os.path.join(dp, f) for f in fs if f.lower().endswith(".pdf")]
    print("heldout pdfs", len(files), flush=True)
    arrs = []; bad = 0
    with Pool(NW) as pool:
        for i, a in enumerate(pool.imap_unordered(pdf_hashes, files, chunksize=8)):
            if a is None: bad += 1
            else: arrs.append(a)
            if i % 1000 == 0: print(i, bad, round(time.time() - t0), flush=True)
    H = np.unique(np.concatenate(arrs)); np.save(HOUT, H); print("heldout sentence hashes", H.size, "unreadable", bad, flush=True)
    tk = Tokenizer.from_file((M_ROOT + "/custody-tokenizer-2c557/tokenizer-2c557.json"))
    st = dict(docs_in=0, docs_dropped=0, docs_kept=0, docs_scrubbed=0, sent_elig=0, sent_hit=0, tok_in_dropped=0, tok_removed=0, tok_out=0, too_short=0)
    cctx = zstandard.ZstdCompressor(level=6)
    with open(IN, "rb") as f, open(OUT, "wb") as fo, cctx.stream_writer(fo) as w:
        for line in io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(f), encoding="utf-8"):
            d = json.loads(line); st["docs_in"] += 1
            parts = SPLIT.split(d["text"]); segs = parts[0::2]; seps = parts[1::2] + [""]
            hs = [seg_hash(s) for s in segs]; el = [i for i, h in enumerate(hs) if h is not None]
            a = np.array([hs[i] for i in el], dtype=np.uint64)
            if a.size:
                pos = np.searchsorted(H, a); pos[pos >= H.size] = H.size - 1; fl = H[pos] == a
            else: fl = np.zeros(0, bool)
            hit = {el[j] for j in range(len(el)) if fl[j]}
            st["sent_elig"] += len(el); st["sent_hit"] += len(hit)
            if el and len(hit) / len(el) > 0.25:
                st["docs_dropped"] += 1; st["tok_in_dropped"] += d["tokens"]; continue
            if hit:
                st["docs_scrubbed"] += 1; st["tok_removed"] += sum(len(tk.encode(segs[i]).ids) for i in hit)
                t = "".join(s + sp for i, (s, sp) in enumerate(zip(segs, seps)) if i not in hit).strip()
            else: t = d["text"]
            if len(t.split()) < 120: st["too_short"] += 1; continue
            d["text"] = t; d["tokens"] = len(tk.encode(t).ids); st["docs_kept"] += 1; st["tok_out"] += d["tokens"]
            w.write((json.dumps(d, ensure_ascii=False) + "\n").encode())
    st["secs"] = round(time.time() - t0); print(json.dumps(st))
if __name__ == "__main__": main()
