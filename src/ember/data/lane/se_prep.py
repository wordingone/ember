# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Stack Exchange 2022-10-05 dump site (.7z) -> Q&A docs. Deterministic; human votes only (no model).
Usage: se_prep.py SITE.7z OUT.jsonl.zst [MINSCORE=1]
Doc = title + question + answers (score >= MINSCORE), best first. Questions need score >= MINSCORE and >=1 kept answer."""
import sys, os, re, io, json, time, shutil, hashlib
import py7zr, zstandard
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
SRC, OUT = sys.argv[1], sys.argv[2]
MINSCORE = int(sys.argv[3]) if len(sys.argv) > 3 else 1
site = os.path.basename(SRC)[:-3]
TMP = os.path.join(os.path.dirname(os.path.abspath(OUT)), "tmp-" + site)
WALL = "2022-10-31"
def html2txt(h):
    s = BeautifulSoup(h, "lxml")
    for pre in s.find_all("pre"):
        pre.replace_with("\n```\n" + pre.get_text() + "\n```\n")
    for li in s.find_all("li"):
        li.insert_before("\n- ")
    for br in s.find_all(["p", "br", "blockquote", "h1", "h2", "h3", "ul", "ol"]):
        br.insert_after("\n")
    t = s.get_text()
    return re.sub(r"\n{3,}", "\n\n", t).strip()
def main():
    t0 = time.time()
    os.makedirs(TMP, exist_ok=True)
    with py7zr.SevenZipFile(SRC) as z:
        z.extract(path=TMP, targets=["Posts.xml"])
    px = os.path.join(TMP, "Posts.xml")
    qs = {}; ans = {}
    st = dict(site=site, rows=0, q=0, a=0, post_wall=0)
    for ev, el in ET.iterparse(px, events=("end",)):
        if el.tag != "row": continue
        a = el.attrib; st["rows"] += 1
        if a.get("CreationDate", "")[:10] > WALL: st["post_wall"] += 1; el.clear(); continue
        t = a.get("PostTypeId"); sc = int(a.get("Score", 0))
        if t == "1" and sc >= MINSCORE:
            qs[a["Id"]] = dict(title=a.get("Title", ""), body=a.get("Body", ""), score=sc, date=a["CreationDate"][:10], tags=a.get("Tags", ""))
            st["q"] += 1
        elif t == "2" and sc >= MINSCORE:
            ans.setdefault(a["ParentId"], []).append((sc, a.get("Body", ""))); st["a"] += 1
        el.clear()
    shutil.rmtree(TMP)
    kept = 0; byt = 0
    cctx = zstandard.ZstdCompressor(level=6)
    with open(OUT, "wb") as fo, cctx.stream_writer(fo) as w:
        for qid, q in qs.items():
            al = sorted(ans.get(qid, []), key=lambda x: -x[0])
            if not al: continue
            parts = ["Question: " + q["title"], html2txt(q["body"])] + ["Answer:\n" + html2txt(b) for _, b in al]
            text = "\n\n".join(parts)
            rec = dict(id=f"se-{site}-{qid}", text=text, date=q["date"], origin="born-digital", license="CC-BY-SA-4.0 (SE ToS; CC BY-SA 2.5/3.0/4.0 by post date)", src="archive.org/stackexchange_20221005", site=site, q_score=q["score"], n_answers=len(al))
            w.write((json.dumps(rec, ensure_ascii=False) + "\n").encode()); kept += 1; byt += len(text.encode())
    st.update(docs=kept, bytes=byt, secs=round(time.time() - t0)); print(json.dumps(st))
main()
