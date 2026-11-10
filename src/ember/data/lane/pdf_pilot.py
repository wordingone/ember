# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import M_ROOT
import os, sys, glob, random, json, re, time
from multiprocessing import Pool
import pypdf
from tokenizers import Tokenizer
SRC = sys.argv[1]; N = int(sys.argv[2]); OUT = sys.argv[3]
tk = Tokenizer.from_file((M_ROOT + "/custody-tokenizer-2c557/tokenizer-2c557.json"))
def stats(t):
    n = max(len(t), 1)
    alpha = sum(c.isalpha() for c in t) / n
    cid = t.count("(cid:") / n * 1000
    nonasc = sum(ord(c) > 127 for c in t) / n
    words = t.split()
    awl = sum(len(w) for w in words) / max(len(words), 1)
    lines = [l for l in t.split("\n") if l.strip()]
    dup = 1 - len(set(lines)) / max(len(lines), 1)
    return dict(chars=len(t), alpha=round(alpha, 3), cid_per_k=round(cid, 2), nonascii=round(nonasc, 3), avg_word_len=round(awl, 2), dup_line_frac=round(dup, 3))
def work(p):
    t0 = time.time()
    try:
        r = pypdf.PdfReader(p); pages = len(r.pages)
        txt = "\n".join((pg.extract_text() or "") for pg in r.pages[:60])
    except Exception as e:
        return dict(file=os.path.basename(p), err=str(e)[:80])
    txt = txt.encode("utf-8", "ignore").decode("utf-8", "ignore")
    s = stats(txt); s.update(file=os.path.basename(p), pages=min(pages, 60), secs=round(time.time() - t0, 1), bytes=os.path.getsize(p))
    # deterministic admit rule: enough text, mostly letters, low cid/garbage, plausible word length
    s["admit"] = bool(s["chars"] >= 2000 and s["alpha"] >= 0.55 and s["cid_per_k"] < 1 and 3 <= s["avg_word_len"] <= 8 and s["nonascii"] < 0.15)
    if s["admit"]:
        s["tokens"] = len(tk.encode(txt).ids)
    s["_text"] = txt[:1500] if len(txt) else ""
    return s
if __name__ == "__main__":
    files = sorted(glob.glob(SRC + "/*.pdf")); random.seed(7); random.shuffle(files); files = files[:N]
    with Pool(2) as pool: res = pool.map(work, files, chunksize=4)
    json.dump(res, open(OUT, "w"))
    ok = [r for r in res if "err" not in r]; adm = [r for r in ok if r["admit"]]
    print("pdfs", len(res), "errors", len(res) - len(ok), "admitted", len(adm), "tokens", sum(r.get("tokens", 0) for r in adm), "pdf_bytes", sum(r.get("bytes", 0) for r in ok))
