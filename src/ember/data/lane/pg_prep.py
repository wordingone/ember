# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Common Pile project_gutenberg shard -> Tier A docs filtered by PG catalog Issued date (<=2022-10-31) and language.
Usage: pg_prep.py SHARD.jsonl.gz OUT.jsonl.zst [LIMIT]   (human-transcribed, public domain; no model used)"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import sys, gzip, json, csv, time, hashlib, zstandard
SRC, OUT = sys.argv[1], sys.argv[2]
LIMIT = int(sys.argv[3]) if len(sys.argv) > 3 else 10**12
WALL = "2022-10-31"
cat = {r["Text#"]: r for r in csv.DictReader(open((LANE_ROOT + "/pg/pg_catalog.csv"), encoding="utf-8"))}
st = dict(docs_in=0, not_in_catalog=0, post_wall=0, not_text=0, non_en=0, kept=0, bytes=0)
cctx = zstandard.ZstdCompressor(level=6)
t0 = time.time()
with gzip.open(SRC, "rt", encoding="utf-8") as f, open(OUT, "wb") as fo, cctx.stream_writer(fo) as w:
    for line in f:
        if st["docs_in"] >= LIMIT: break
        d = json.loads(line); st["docs_in"] += 1
        r = cat.get(d["id"])
        if r is None: st["not_in_catalog"] += 1; continue
        if r["Type"] != "Text": st["not_text"] += 1; continue
        if r["Issued"] > WALL: st["post_wall"] += 1; continue
        if r["Language"] != "en": st["non_en"] += 1; continue
        t = d["text"].replace("\r\n", "\n").strip()
        if t.endswith("***"): t = t[:-3].rstrip()
        rec = dict(id="pg-" + d["id"], title=r["Title"], issued=r["Issued"], text=t, origin="human-transcribed", license="Public Domain (US)",
                   src="common-pile/project_gutenberg@01dc90a5", url=f"https://www.gutenberg.org/ebooks/{d['id']}")
        w.write((json.dumps(rec, ensure_ascii=False) + "\n").encode()); st["kept"] += 1; st["bytes"] += len(t.encode())
st["secs"] = round(time.time() - t0); print(json.dumps(st))
