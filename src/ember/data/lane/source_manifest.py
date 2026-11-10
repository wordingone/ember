# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""source_manifest.py PACKDIR PROV.jsonl ORIGIN LICENSE FETCH_DATE CONTENT_DATE_MAX [MODALITY=text] : one row per object (training 81172 b).
PROV.jsonl rows: doc_id, raw_sha256 (or pdf_sha256), optional fetched_ts/license_url. raw_set_sha256 = sha256 of the sorted newline-joined raw-file shas of the docs in the object."""
import sys, os, io, json, hashlib, zstandard
PK, PROV, ORIGIN, LIC, FETCH, CDM = sys.argv[1:7]; MOD = sys.argv[7] if len(sys.argv) > 7 else "text"  # CDM = latest content date the object can contain (training 81228, C1 date check)
prov = {}
for l in open(PROV, encoding="utf-8"):
    d = json.loads(l); prov[d["doc_id"]] = d
rec = json.load(open(os.path.join(PK, "receipt.json")))
byobj = {}
for line in io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(open(os.path.join(PK, "docs-index.jsonl.zst"), "rb")), encoding="utf-8"):
    d = json.loads(line); byobj.setdefault(d["object_index"], []).append(d["id"])
def sha(p):
    h = hashlib.sha256()
    for b in iter(lambda: open(p, "rb").read(), b""): h.update(b); break
    return h.hexdigest()
rows = []
for o in rec["objects"]:
    ids = byobj[o["index"]]; raws = sorted((prov[i].get("raw_sha256") or prov[i].get("pdf_sha256")) for i in ids)
    lics = sorted({prov[i].get("license_url") or LIC for i in ids}); fts = sorted(x for x in {prov[i].get("fetched_ts") for i in ids} if x)
    rows.append(dict(object_sha256=o["sha256"], object_name=o["name"], object_index=o["index"], docs=len(ids), tokens=o["token_end"] - o["token_start"], origin=ORIGIN, licence=lics, fetch_date=(fts[0] + ".." + fts[-1]) if fts else FETCH,
                     raw_file_count=len(raws), raw_set_sha256=hashlib.sha256("\n".join(raws).encode()).hexdigest(), dataset_id=rec["dataset_id"], content_date_max=CDM, modality=MOD))
with open(os.path.join(PK, "source-manifest.jsonl"), "w") as f:
    for r in rows: f.write(json.dumps(r) + "\n")
dp = os.path.join(PK, "docs-index.jsonl.zst")
h = hashlib.sha256(open(dp, "rb").read()).hexdigest()
print(json.dumps(dict(objects=len(rows), docs_index_sha256=h, ledger_sha256=hashlib.sha256(open(os.path.join(PK, "ledger.jsonl"), "rb").read()).hexdigest())))
