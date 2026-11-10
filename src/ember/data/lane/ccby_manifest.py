# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Build the pack_media manifest for commoncatalog-cc-by (Flickr/YFCC CC-BY photos; HUMAN text only: title + description; BLIP-2 captions are dropped per lead).
Usage: ccby_manifest.py IN1.parquet [IN2 ...] --out OUTDIR      -> OUTDIR/images/<sha256>.jpg + OUTDIR/manifest.jsonl + OUTDIR/stats.json
Rules: licence url must be creativecommons.org/licenses/by/ (plain CC-BY; no -nc/-nd/-sa); dateuploaded (epoch) <= 2022-10-31; human text (title+description, HTML stripped, url-decoded) >= 8 words;
caption sentences (>=8 words) hitting the heldout indexes are dropped (rule 4); duplicate image sha256 dropped. Nothing model-made. Selftest: ccby_manifest.py selftest"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import sys, os, re, io, json, time, html, collections, urllib.parse
import numpy as np, xxhash
WALL_EPOCH = 1667174400   # 2022-11-01T00:00:00Z exclusive
IDXP = ((LANE_ROOT + "/heldout-index-full/heldout-sent-xxh64-full.npy"), (LANE_ROOT + "/heldout-index/wiki-heldout-2M.npy"), (LANE_ROOT + "/arxiv/heldout-pdf-sent-hashes.npy"))
SPLIT = re.compile(r"((?<=[.!?])\s+|\n+)"); WS = re.compile(r"\s+"); TAG = re.compile(r"<[^>]+>")
_IDX = None
def idx():
    global _IDX
    if _IDX is None: _IDX = [np.load(p, mmap_mode="r") for p in IDXP if os.path.exists(p)]
    return _IDX
def hit(c):
    for s in SPLIT.split(c):
        n = WS.sub(" ", s.lower()).strip()
        if n.count(" ") >= 7:
            h = xxhash.xxh64_intdigest(n)
            for a in idx():
                i = int(np.searchsorted(a, h))
                if i < len(a) and int(a[i]) == h: return True
    return False
def clean(s): return WS.sub(" ", TAG.sub(" ", html.unescape(urllib.parse.unquote_plus(s or "")))).strip()
def human_text(r):
    t, d = clean(r.get("title")), clean(r.get("description") or r.get("caption"))
    return (t + ". " + d).strip(". ") if d and d.lower() != t.lower() else t
def row_ok(r, st):
    if not re.search(r"creativecommons\.org/licenses/by/", r.get("licenseurl") or ""): st["licence"] += 1; return None
    try: up = int(r.get("dateuploaded") or 0)
    except ValueError: up = 0
    if not up or up >= WALL_EPOCH: st["post_wall_or_undated"] += 1; return None
    txt = human_text(r)
    if len(txt.split()) < 8: st["short_text"] += 1; return None
    if hit(txt): st["heldout_hit"] += 1; return None
    return txt, up
def main(files, out):
    import pyarrow.parquet as pq
    os.makedirs(out + "/images", exist_ok=True); st = collections.Counter(); seen = set(); today = time.strftime("%Y-%m-%d")
    with open(out + "/manifest.jsonl", "w", encoding="utf-8") as mf:
        for f in files:
            pf = pq.ParquetFile(f)
            for b in pf.iter_batches(batch_size=64):
                for r in b.to_pylist():
                    st["rows"] += 1; ok = row_ok(r, st)
                    if not ok: continue
                    sha = r["sha256"]
                    if sha in seen: st["dup_sha"] += 1; continue
                    seen.add(sha); jb = r["jpg"]; jb = jb["bytes"] if isinstance(jb, dict) else jb
                    if not jb: st["no_image"] += 1; continue
                    p = f"{out}/images/{sha}.jpg"; open(p, "wb").write(jb)
                    mf.write(json.dumps(dict(path=p, caption=ok[0], licence="CC-BY (Flickr per-photo licence)", licence_url=r["licenseurl"], origin=r.get("pageurl"), author=r.get("unickname"), fetch_date=today,
                        content_date_max=time.strftime("%Y-%m-%d", time.gmtime(ok[1])), modality="image-text", caption_author="human (Flickr uploader title/description)", sha256=sha), ensure_ascii=False) + "\n"); st["kept"] += 1
    json.dump(dict(st), open(out + "/stats.json", "w")); print(dict(st))
def selftest():
    ok = True
    def chk(n, c):
        nonlocal ok; print(("PASS " if c else "FAIL ") + n); ok = ok and bool(c)
    st = collections.Counter(); base = dict(licenseurl="http://creativecommons.org/licenses/by/2.0/", dateuploaded="1143398479", title="Lake+Erie+Gulls+and+Freighter", description="Gulls+fill+the+skies+over+the+stern+of+the+massive+freighter+on+a+cold+morning")
    chk("plain CC-BY pre-wall kept", row_ok(base, st) is not None)
    chk("by-nc refused", row_ok(dict(base, licenseurl="http://creativecommons.org/licenses/by-nc/2.0/"), st) is None and st["licence"] == 1)
    chk("post-wall upload refused", row_ok(dict(base, dateuploaded="1700000000"), st) is None and st["post_wall_or_undated"] == 1)
    chk("short text refused", row_ok(dict(base, title="a+b", description=""), st) is None and st["short_text"] == 1)
    print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]: selftest()
    a = sys.argv[1:]; o = a[a.index("--out") + 1]; main([x for x in a if x.endswith(".parquet")], o)
