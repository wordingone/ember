# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Audit probe: are the raw-private arXiv PDFs (pdf_sha256 in provenance-per-paper.jsonl) also inside ember-corpus acquisition/train/A-train-2 tars?
Streams one tar part (hf_hub_download to a temp dir under bulk/audit, deleted after), hashes each member, intersects with the raw-private PDF sha256 set."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_RAW_REPO, LANE_ROOT
import sys, os, tarfile, hashlib, json
from huggingface_hub import hf_hub_download
part = sys.argv[1]
prov = hf_hub_download(("wordingone/" + HF_RAW_REPO), "text/arxiv-pdf/provenance-per-paper.jsonl", repo_type="dataset")
pdfs = {}
for l in open(prov, encoding="utf-8"):
    r = json.loads(l); pdfs[r["pdf_sha256"]] = r["doc_id"]
d = (LANE_ROOT + "/bulk/audit"); os.makedirs(d, exist_ok=True)
p = hf_hub_download("wordingone/ember-corpus", f"acquisition/train/{part}", repo_type="dataset", local_dir=d)
n = hit = size_hit = 0; ext = {}
with tarfile.open(p, "r:gz") as tf:
    for m in tf:
        if not m.isfile(): continue
        n += 1; e = os.path.splitext(m.name)[1].lower(); ext[e] = ext.get(e, 0) + 1
        h = hashlib.sha256(); f = tf.extractfile(m)
        for b in iter(lambda: f.read(4 << 20), b""): h.update(b)
        if h.hexdigest() in pdfs: hit += 1; size_hit += m.size
print(json.dumps(dict(part=part, members=n, ext=dict(sorted(ext.items(), key=lambda x: -x[1])[:6]), members_identical_to_raw_private_arxiv_pdfs=hit, bytes=size_hit, raw_private_pdfs=len(pdfs))))
os.remove(p)
