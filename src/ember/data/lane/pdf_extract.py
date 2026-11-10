# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Pre-wall arXiv PDFs -> text via pypdf (deterministic, Tier A per lead 81151). NFKC. Admit rule as pilot. Usage: pdf_extract.py OUT.jsonl.zst [WORKERS=3] [LIMIT]"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, M_ROOT
import sys, os, json, re, time, unicodedata, zstandard
from multiprocessing import Pool
import pypdf
from tokenizers import Tokenizer
OUT = sys.argv[1]; NW = int(sys.argv[2]) if len(sys.argv) > 2 else 3; LIMIT = int(sys.argv[3]) if len(sys.argv) > 3 else 10**9
tk = Tokenizer.from_file((M_ROOT + "/custody-tokenizer-2c557/tokenizer-2c557.json"))
def stats(t):
    n = max(len(t), 1); words = t.split()
    return dict(chars=len(t), alpha=sum(c.isalpha() for c in t) / n, cid=t.count("(cid:") / n * 1000,
                nonasc=sum(ord(c) > 127 for c in t) / n, awl=sum(len(w) for w in words) / max(len(words), 1))
def work(a):
    aid, v, p, created, updated = a
    try:
        r = pypdf.PdfReader(p); pages = len(r.pages)
        txt = "\n".join((pg.extract_text() or "") for pg in r.pages[:300])
    except Exception as e:
        return dict(aid=aid, err=str(e)[:80])
    txt = unicodedata.normalize("NFKC", txt.encode("utf-8", "ignore").decode("utf-8", "ignore"))
    txt = re.sub(r"[ \t]+\n", "\n", txt); txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
    s = stats(txt)
    ok = s["chars"] >= 2000 and s["alpha"] >= 0.55 and s["cid"] < 1 and 3 <= s["awl"] <= 8 and s["nonasc"] < 0.15
    if not ok: return dict(aid=aid, rejected=True, chars=s["chars"])
    return dict(id="arxiv-" + aid.replace("/", "_") + f"v{v}", arxiv_id=aid, version=v, created=created, updated=updated, pages=pages, text=txt,
                tokens=len(tk.encode(txt).ids), origin="born-digital (pypdf deterministic extraction)", license="arXiv non-exclusive distribution (private twin only)",
                src="arxiv.org PDF, catalog admitted object")
if __name__ == "__main__":
    lst = json.load(open((LANE_ROOT + "/audit/pdf-prewall-list.json")))[:LIMIT]
    st = dict(pdfs=len(lst), err=0, rejected=0, kept=0, tokens=0, chars=0); t0 = time.time()
    cctx = zstandard.ZstdCompressor(level=6)
    with Pool(NW) as pool, open(OUT, "wb") as fo, cctx.stream_writer(fo) as w:
        for i, r in enumerate(pool.imap(work, lst, chunksize=4)):
            if "err" in r: st["err"] += 1
            elif r.get("rejected"): st["rejected"] += 1
            else:
                st["kept"] += 1; st["tokens"] += r["tokens"]; st["chars"] += len(r["text"])
                w.write((json.dumps(r, ensure_ascii=False) + "\n").encode())
            if i % 500 == 0: print(i, st, round(time.time() - t0), flush=True)
    st["secs"] = round(time.time() - t0); print("FINAL", json.dumps(st), flush=True)
