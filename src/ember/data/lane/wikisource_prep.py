# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""enwikisource 2022-05-01 pages-articles.xml.bz2 -> docs jsonl.zst. Deterministic, no model.
Usage: wikisource_prep.py DUMP.bz2 OUT.jsonl.zst [LIMIT_PAGES]
Docs: (A) ns104 'Page:' pages with <pagequality level> >= 3 (proofread / validated by humans), grouped per Index file and joined in page-number order -> one doc per work;
      (B) ns0 non-redirect pages without a <pages ...> transclusion tag and >= 200 words (human-typed text).
Level 3/4 text is machine OCR corrected by human proofreaders: field quality_basis marks it 'ocr-human-proofread' (lead ruling pending on Tier A vs B); ns0 typed text is 'human-typed'.
Strips <noinclude> (headers/footers), templates, links, tags. Min doc 120 words."""
import sys, re, bz2, io, json, html, time, collections
import xml.etree.ElementTree as ET
import zstandard
SRC, OUT = sys.argv[1], sys.argv[2]; LIM = int(sys.argv[3]) if len(sys.argv) > 3 else 10**12
PQ = re.compile(r'<pagequality\s+level="(\d)"', re.I)
def clean(t):
    t = re.sub(r"<noinclude>.*?</noinclude>", " ", t, flags=re.S | re.I); t = re.sub(r"<pagequality[^>]*/>|<section\s[^>]*/>|<!--.*?-->", " ", t, flags=re.S)
    t = re.sub(r"<ref[^>]*/>|<ref.*?</ref>", " ", t, flags=re.S | re.I)
    for _ in range(5): t = re.sub(r"\{\{[^{}]*\}\}", " ", t)
    t = re.sub(r"\{\|.*?\|\}", " ", t, flags=re.S)
    t = re.sub(r"\[\[(?:File|Image|Category):[^\]]*\]\]", " ", t, flags=re.I); t = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", t); t = re.sub(r"\[\[([^\]]*)\]\]", r"\1", t)
    t = re.sub(r"\[https?://\S+\s+([^\]]*)\]|\[https?://\S+\]", r"\1", t); t = re.sub(r"<[^>]+>|'{2,}|^[=*#:;]+", " ", t, flags=re.M)
    return re.sub(r"[ \t\r\f\v]+", " ", html.unescape(t)).strip()
idx = collections.defaultdict(dict)   # index -> page_no -> (text, ts)
ns0 = []; st = collections.Counter(); n = 0
def ln(e): return e.tag.rsplit("}", 1)[-1]
with bz2.open(SRC, "rb") as f:
    for ev, el in ET.iterparse(f, events=("end",)):
        if ln(el) != "page": continue
        n += 1
        if n > LIM: break
        title = ns = redirect = None; text = ts = None
        for c in el:
            t = ln(c)
            if t == "title": title = c.text
            elif t == "ns": ns = c.text
            elif t == "redirect": redirect = True
            elif t == "revision":
                for r in c:
                    if ln(r) == "text": text = r.text or ""
                    elif ln(r) == "timestamp": ts = r.text
        if redirect or text is None: el.clear(); continue
        if ns == "104" and title and title.startswith("Page:"):
            m = PQ.search(text)
            if m and int(m.group(1)) >= 3:
                mm = re.match(r"Page:(.+)/(\d+)$", title)
                if mm: idx[mm.group(1)][int(mm.group(2))] = (clean(text), ts, int(m.group(1)))
                else: st["page_noindex"] += 1
            else: st["page_lowquality"] += 1
        elif ns == "0" and title:
            if re.search(r"<pages\s", text, re.I): st["ns0_transclusion"] += 1
            else:
                c2 = clean(text)
                if len(c2.split()) >= 200: ns0.append(dict(id="wsmain-" + str(len(ns0)), title=title, text=c2, ts=ts, pages=1, quality_basis="human-typed"))
                else: st["ns0_short"] += 1
        el.clear()
        if n % 200000 == 0: print(n, dict(st), len(idx), len(ns0), flush=True)
cctx = zstandard.ZstdCompressor(level=6); kept = 0; toks = 0
with open(OUT, "wb") as fo, cctx.stream_writer(fo) as w:
    for name, pg in sorted(idx.items()):
        nums = sorted(pg); text = "\n\n".join(pg[k][0] for k in nums if pg[k][0]).strip()
        if len(text.split()) < 120: st["index_short"] += 1; continue
        d = dict(id="wsidx-" + re.sub(r"\W+", "_", name)[:80], title=name, text=text, ts=max(pg[k][1] for k in nums), pages=len(nums), quality_min=min(pg[k][2] for k in nums), quality_basis="ocr-human-proofread")
        w.write((json.dumps(d, ensure_ascii=False) + "\n").encode()); kept += 1
    for d in ns0:
        if len(d["text"].split()) >= 120: w.write((json.dumps(d, ensure_ascii=False) + "\n").encode()); kept += 1
st["docs"] = kept; st["index_docs"] = len(idx); st["ns0_docs"] = len(ns0); st["pages_scanned"] = n
print(json.dumps(dict(st)))
