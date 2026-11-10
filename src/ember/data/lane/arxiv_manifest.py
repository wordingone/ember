# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Per-paper provenance manifest for the arXiv batch: pdf path, sha256, bytes, license (from corpus fetch manifests), OAI dates."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import M_ROOT
import os, re, json, io, glob, hashlib, zstandard
IN = "arxiv/train-final.jsonl.zst"; OUT = "packed/arxiv-pdf-prewall/provenance-per-paper.jsonl"
lst = {(a, v): (p, c, u) for a, v, p, c, u in json.load(open("audit/pdf-prewall-list.json"))}
lic = {}; mrows = 0; fetch = {}
for mp in glob.glob((M_ROOT + "/data/corpus/**/manifest.jsonl"), recursive=True):
    for line in open(mp, encoding="utf-8-sig", errors="ignore"):
        try: r = json.loads(line)
        except Exception: continue
        mrows += 1; b = r.get("human_provenance_basis") or ""
        for m in re.finditer(r"((?:\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})v\d+)=(https?://[^\s(;,]+)", b):
            lic[m.group(1)] = m.group(2)
            fetch[m.group(1)] = r.get("fetched_ts")
n = 0; haslic = 0
with open(OUT, "w", encoding="utf-8") as fo:
    for line in io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(open(IN, "rb")), encoding="utf-8"):
        d = json.loads(line); key = (d["arxiv_id"], d["version"]); p, c, u = lst[key]
        h = hashlib.sha256(open(p, "rb").read()).hexdigest(); k = f'{d["arxiv_id"]}v{d["version"]}'
        L = lic.get(k)
        if L: haslic += 1
        fo.write(json.dumps(dict(doc_id=d["id"], arxiv_id=d["arxiv_id"], version=d["version"], url=f'https://arxiv.org/pdf/{k}', pdf_sha256=h, pdf_bytes=os.path.getsize(p), pdf_local=p.replace("\\", "/"),
                                 fetched_ts=fetch.get(k), license_url=L, oai_created=c, oai_updated=u, tokens=d["tokens"])) + "\n"); n += 1
print(dict(papers=n, with_license_url=haslic, manifest_rows=mrows, license_map=len(lic)))
