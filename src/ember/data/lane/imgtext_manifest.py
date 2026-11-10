# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Build pack_media manifest for COCO or TextCaps (human captions). Usage: imgtext_manifest.py coco|textcaps ROOT OUT.jsonl
Drops captions whose eligible sentences (>=8 words) hit the heldout indexes (rule 4; reports counts). One row per IMAGE; `captions` holds every human caption
(pairs = sum of len(captions)); `caption` = first caption (pack_media key). Extra fields kept verbatim by pack_media."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import sys, os, re, json, time, collections, numpy as np, xxhash
KIND, ROOT, OUT = sys.argv[1:4]
IDX = [np.load(p, mmap_mode="r") for p in ((LANE_ROOT + "/heldout-index-full/heldout-sent-xxh64-full.npy"), (LANE_ROOT + "/heldout-index/wiki-heldout-2M.npy"), (LANE_ROOT + "/arxiv/heldout-pdf-sent-hashes.npy"))]
SPLIT = re.compile(r"((?<=[.!?])\s+|\n+)"); WS = re.compile(r"\s+")
def inidx(h):
    for a in IDX:
        i = int(np.searchsorted(a, h))
        if i < len(a) and int(a[i]) == h: return True
    return False
def hit(c):
    for s in SPLIT.split(c):
        n = WS.sub(" ", s.lower()).strip()
        if n.count(" ") >= 7 and inidx(xxhash.xxh64_intdigest(n)): return True
    return False
st = collections.Counter(); today = time.strftime("%Y-%m-%d"); rows = []
if KIND == "coco":
    fe = {json.loads(l)["file_name"]: json.loads(l) for l in open(ROOT + "/fetched.jsonl", encoding="utf-8")}
    for l in open(ROOT + "/coco-keep.jsonl", encoding="utf-8"):
        d = json.loads(l)
        if d["file_name"] not in fe: st["not_fetched"] += 1; continue
        caps = []
        for c in d["captions"]:
            if hit(c): st["caption_heldout_hit"] += 1
            else: caps.append(c)
        if not caps: st["no_caption_left"] += 1; continue
        rows.append(dict(path=(f"{ROOT}/images/{d['file_name']}" if os.path.exists(f"{ROOT}/images/{d['file_name']}") else f"A:/ember-stage/coco-images/{d['file_name']}"), caption=caps[0], captions=caps, licence=d["licence"], licence_url=d["licence_url"], author="Flickr user (see flickr_url)",
                         origin=d["flickr_url"], coco_url=d["coco_url"], coco_split=d["split"], fetch_date=today, content_date_max="2015-04-01", modality="image-text",
                         caption_author="human (Amazon Mechanical Turk; Chen et al. arXiv 1504.00325)", licence_note="per-image Flickr licence from COCO annotations (license field); annotations CC BY 4.0"))
        st["images"] += 1; st["pairs"] += len(caps)
else:
    d = json.load(open(ROOT + "/TextCaps_0.1_train.json", encoding="utf-8"))["data"]; by = collections.OrderedDict()
    for r in d: by.setdefault(r["image_id"], r)
    for iid, r in by.items():
        p = f"{ROOT}/images/{r['image_path']}"
        if not os.path.exists(p): p = f"A:/ember-stage/textcaps-images/{r['image_path']}"   # staging moved B->A (lead 81466)
        if not os.path.exists(p): st["not_fetched"] += 1; continue
        caps = []
        for c in r["reference_strs"]:
            if hit(c): st["caption_heldout_hit"] += 1
            else: caps.append(c)
        if not caps: st["no_caption_left"] += 1; continue
        rows.append(dict(path=p, caption=caps[0], captions=caps, licence="CC BY 2.0 (Open Images v4 image licence; TextCaps annotations CC BY 4.0)", licence_url="https://creativecommons.org/licenses/by/2.0/", author="Flickr user (Open Images)",
                         origin=r["flickr_original_url"], openimages_id=iid, fetch_date=today, content_date_max="2020-03-28", modality="image-text",
                         caption_author="human (TextCaps annotators; Sidorov et al. arXiv 2003.12462)", licence_note="per-image licence verified 2026-11-07: all 21,953 train images are CC BY 2.0 in Open Images train-images-boxable-with-rotation.csv (audit/licence-reads/RESULTS.md); annotations CC BY 4.0 (HF card, secondary)"))
        st["images"] += 1; st["pairs"] += len(caps)
with open(OUT, "w", encoding="utf-8") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(json.dumps(dict(st)))
