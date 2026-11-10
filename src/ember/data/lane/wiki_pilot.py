# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Wikipedia dump part -> plain text docs (Tier A, born-digital). Deterministic; no learned models."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, M_ROOT
import sys, os, bz2, re, json, io, time, hashlib
import xml.etree.ElementTree as ET
import mwparserfromhell as mw, zstandard, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import gram_hashes, overlap
IDX = np.load((LANE_ROOT + '/heldout-index/heldout-sent-xxh64-s4.npy'), mmap_mode='r')
from tokenizers import Tokenizer
SRC, OUT = sys.argv[1], sys.argv[2]
LIMIT = int(sys.argv[3]) if len(sys.argv) > 3 else 10**9
tk = Tokenizer.from_file((M_ROOT + "/custody-tokenizer-2c557/tokenizer-2c557.json"))
TAIL = re.compile(r"\n==\s*(See also|References|External links|Further reading|Notes|Bibliography|Sources)\s*==.*", re.S | re.I)
def clean(wt):
    code = mw.parse(wt)
    txt = code.strip_code(normalize=True, collapse=True)
    txt = TAIL.sub("", "\n" + txt).strip()
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    txt = re.sub(r"^(Category|File|Image):.*$", "", txt, flags=re.M)
    return txt.strip()
def main():
    t0 = time.time(); st = dict(pages=0, redirect=0, non_main=0, short=0, kept=0, bytes=0, tokens=0, hs=0, hits=0, docs_hit=0)
    cctx = zstandard.ZstdCompressor(level=6)
    with bz2.open(SRC, "rb") as f, open(OUT, "wb") as fo, cctx.stream_writer(fo) as w:
        ns = None; title = None; rid = None; text = None; redirect = False; ts = None
        for ev, el in ET.iterparse(f, events=("end",)):
            tag = el.tag.rsplit("}", 1)[-1]
            if tag == "title": title = el.text
            elif tag == "ns": ns = el.text
            elif tag == "id" and rid is None: rid = el.text
            elif tag == "timestamp": ts = el.text
            elif tag == "redirect": redirect = True
            elif tag == "text": text = el.text or ""
            elif tag == "page":
                st["pages"] += 1
                if redirect: st["redirect"] += 1
                elif ns != "0": st["non_main"] += 1
                else:
                    c = clean(text)
                    if len(c.split()) < 120: st["short"] += 1
                    else:
                        n = len(tk.encode(c).ids)
                        hh = gram_hashes(c); ov = overlap(IDX, hh); st['hs'] += int(hh.size); st['hits'] += ov; st['docs_hit'] += int(ov > 0)
                        rec = dict(id=rid, title=title, ts=ts, text=c, sha=hashlib.sha256(c.encode()).hexdigest()[:16], origin="born-digital", license="CC-BY-SA-3.0+GFDL", src="enwiki-20220501")
                        w.write((json.dumps(rec, ensure_ascii=False) + "\n").encode())
                        st["kept"] += 1; st["bytes"] += len(c.encode()); st["tokens"] += n
                ns = title = rid = text = ts = None; redirect = False; el.clear()
                if st["pages"] >= LIMIT: break
    st["secs"] = round(time.time() - t0)
    print(json.dumps(st))
main()
