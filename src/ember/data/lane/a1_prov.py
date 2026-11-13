# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Per-row provenance sidecar for ember a1-v5 image-text manifest (training 81312). Deterministic: dataset-level facts + manifest fields + DOCCI split/example_id."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, M_ROOT
import json, hashlib, collections
M = (M_ROOT + "/ember-data/custody/a1-v5-manifest/combined-train-manifest-v5-no-arxivqa.jsonl"); OUT = (LANE_ROOT + "/audit/a1-v5-provenance.jsonl")
DS = {
 "pd12m-full-train-0": dict(origin="https://huggingface.co/datasets/Spawning/PD12M (pd12m-full); paper https://arxiv.org/abs/2410.23144", image_date="unknown (public-domain images, many pre-2022; per-image date not recorded)", caption_date="2024-10-30", caption_author="model", caption_model="Florence-2-large", date_basis="paper arXiv 2410.23144 (Oct 2024); captions generated for the release", date_verified=True),
 "docci": dict(origin="https://google.github.io/docci/ ; https://arxiv.org/abs/2404.19753", image_date="2022-10..2023-11 (DOCCI-AAR range per paper; annotated-15k photo dates not recorded)", caption_date="2024-04-30", caption_author="human", caption_model=None, date_basis="paper submitted 2024-04-30; annotation year not found", date_verified=True),
 "iconqa": dict(origin="https://iconqa.github.io/ ; https://arxiv.org/abs/2110.13214 ; HF mirror nimapourjafar/mm_iconqa", image_date="2021-10-25", caption_date="2021-10-25", caption_author="human (crowd/curated question text)", caption_model=None, date_basis="paper arXiv 2110.13214 (from memory, unverified)", date_verified=False),
 "scienceqa": dict(origin="https://scienceqa.github.io/ ; https://arxiv.org/abs/2209.09513", image_date="2022-09-20", caption_date="2022-09-20", caption_author="human (K-12 curriculum question text)", caption_model=None, date_basis="paper arXiv 2209.09513 (from memory, unverified)", date_verified=False),
 "ai2d": dict(origin="https://allenai.org/data/diagrams ; https://arxiv.org/abs/1603.07396", image_date="2016-03-24", caption_date="2016-03-24", caption_author="human", caption_model=None, date_basis="paper arXiv 1603.07396 (from memory, unverified)", date_verified=False),
 "a-okvqa": dict(origin="https://allenai.org/project/a-okvqa ; https://arxiv.org/abs/2206.01718 ; images MS-COCO (Flickr)", image_date="<=2014 (COCO)", caption_date="2022-06-03", caption_author="human (crowd)", caption_model=None, date_basis="paper arXiv 2206.01718; COCO 2014 (from memory, unverified)", date_verified=False),
 "m3exam-english": dict(origin="https://github.com/DAMO-NLP-SG/M3Exam ; https://arxiv.org/abs/2306.05179", image_date="2023-06-08", caption_date="2023-06-08", caption_author="human (exam authors)", caption_model=None, date_basis="paper arXiv 2306.05179 (from memory, unverified); EVAL benchmark", date_verified=False, eval_set=True),
 "mmbench-dev-scienceqa": dict(origin="https://github.com/open-compass/MMBench ; https://arxiv.org/abs/2307.06281", image_date="2023-07-12", caption_date="2023-07-12", caption_author="human", caption_model=None, date_basis="paper arXiv 2307.06281 (from memory, unverified); EVAL benchmark dev split", date_verified=False, eval_set=True),
}
docci = {}
for l in open((M_ROOT + "/ember-data/custody/docci-train/pairs-index.jsonl"), encoding="utf-8"):
    d = json.loads(l); docci[d["image_sha256"]] = (d["example_id"], d["split"])
cnt = collections.Counter(); n = 0
with open(OUT, "w", encoding="utf-8") as fo:
    for i, l in enumerate(open(M, encoding="utf-8")):
        d = json.loads(l); p = DS[d["dataset_id"]]
        r = dict(row_index=i, object_sha256=d["object_sha256"], dataset_id=d["dataset_id"], licence=d["licence"], origin=p["origin"], image_date=p["image_date"], caption_date=p["caption_date"],
                 caption_author=p["caption_author"], caption_model=p["caption_model"], date_basis=p["date_basis"], date_verified=p["date_verified"], content_date_max=p["caption_date"], eval_set=bool(p.get("eval_set")))
        if d["dataset_id"] == "docci": r["docci_example_id"], r["docci_split"] = docci[d["object_sha256"]]
        r["verdict"] = "FAIL" if (p["caption_author"] == "model" or r["eval_set"] or d["dataset_id"] == "docci") else ("CONDITIONAL_NC" if "NC" in d["licence"] else "PASS")
        cnt[(d["dataset_id"], r["verdict"])] += 1; n += 1
        fo.write(json.dumps(r, ensure_ascii=False) + "\n")
print(n); [print(v, k) for k, v in sorted(cnt.items())]
print(hashlib.sha256(open(OUT, "rb").read()).hexdigest())
