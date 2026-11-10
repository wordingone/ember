# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""COCO Captions 2014 -> licence-filtered image list + manifest (lead 81317/81321). Deterministic, no model.
Usage: coco_prep.py BASE   (BASE/annotations_trainval2014.zip must exist)
Keep only images with a per-image Flickr licence in KEEP (4 CC-BY, 5 CC-BY-SA, 7 no-known-copyright-restrictions, 8 US-gov work); NC/ND dropped
(resizing/cropping is a modification). Captions: human (AMT), collected 2014-15 (arXiv 1504.00325). Annotations CC-BY 4.0.
Outputs: BASE/coco-keep.jsonl (one row per kept image: file_name, coco_url, flickr_url, license id/name, captions[5+], split) and BASE/prep-stats.json.
A later step downloads images, scrubs captions vs the heldout index, then writes manifest.jsonl for pack_media.py."""
import sys, json, zipfile, collections
BASE = sys.argv[1]
LIC = {1: "CC BY-NC-SA 2.0", 2: "CC BY-NC 2.0", 3: "CC BY-NC-ND 2.0", 4: "CC BY 2.0", 5: "CC BY-SA 2.0", 6: "CC BY-ND 2.0", 7: "No known copyright restrictions (Flickr Commons)", 8: "United States Government Work"}
LICURL = {4: "https://creativecommons.org/licenses/by/2.0/", 5: "https://creativecommons.org/licenses/by-sa/2.0/", 7: "https://www.flickr.com/commons/usage/", 8: "http://www.usa.gov/copyright.shtml"}
KEEP = {4, 5, 7, 8}
z = zipfile.ZipFile(BASE + "/annotations_trainval2014.zip"); st = collections.Counter(); rows = []
for split in ("train", "val"):
    d = json.load(z.open(f"annotations/captions_{split}2014.json"))
    caps = collections.defaultdict(list)
    for a in d["annotations"]: caps[a["image_id"]].append((a["id"], " ".join(a["caption"].split())))
    for im in d["images"]:
        st[f"{split}_images"] += 1; st[f"lic{im['license']}"] += 1
        if im["license"] not in KEEP: st["dropped_licence"] += 1; continue
        cs = [c for _, c in sorted(caps[im["id"]])]
        if not cs: st["no_caption"] += 1; continue
        rows.append(dict(coco_id=im["id"], split=split, file_name=im["file_name"], coco_url=im["coco_url"], flickr_url=im["flickr_url"], date_captured=im["date_captured"],
                         licence=LIC[im["license"]], licence_id=im["license"], licence_url=LICURL[im["license"]], captions=cs))
        st["kept_images"] += 1; st["kept_pairs"] += len(cs)
with open(BASE + "/coco-keep.jsonl", "w", encoding="utf-8") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
json.dump(dict(st), open(BASE + "/prep-stats.json", "w"), indent=1); print(json.dumps(dict(st), indent=1))
