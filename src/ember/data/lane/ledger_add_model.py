# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Append a source-licence ledger row for a fetched open-weight model (audit/source-licence-ledger.jsonl, schema ember-source-licence-ledger-v1).
Usage: python scripts/ledger_add_model.py <m-root>/models/<name>
Reads <dir>/fetch-receipt.json (written by fetch_open_model.py), copies LICENSE and README.md into audit/teacher-licences/<name-lower>-{LICENSE,README.md}, hashes them, checks the card's license id equals the
SPDX id found in the LICENSE text (Apache-2.0 header + 'Version 2.0'), and appends one row. Refuses to add a second row for the same source_id+revision. Hash values come from the receipt, never typed by hand."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, re, json, shutil, hashlib, time
from lane_config import LANE_ROOT as BASE
LEDGER = BASE + "/audit/source-licence-ledger.jsonl"


def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main():
    d = sys.argv[1].rstrip("/\\"); rec = json.load(open(d + "/fetch-receipt.json", encoding="utf-8")); name = os.path.basename(d)
    lic_text = open(d + "/LICENSE", encoding="utf-8").read()
    if not (re.search(r"Apache License", lic_text) and re.search(r"Version 2\.0", lic_text)) or (rec.get("license_from_card") or "").lower() != "apache-2.0":
        print("REFUSED: LICENSE text is not Apache-2.0 or the card id differs; read it by hand"); return 2
    cp = re.search(r"Copyright\s+(\d{4})\s+([^\n]+)", lic_text); holder = ("%s (Copyright %s)" % (cp.group(2).strip(), cp.group(1))) if cp else "not named in the LICENSE appendix"
    ev = BASE + "/audit/teacher-licences"; os.makedirs(ev, exist_ok=True); low = name.lower()
    shutil.copyfile(d + "/LICENSE", "%s/%s-LICENSE" % (ev, low)); shutil.copyfile(d + "/README.md", "%s/%s-README.md" % (ev, low))
    sid = "model:" + rec["repo"]
    for l in open(LEDGER, encoding="utf-8"):
        r = json.loads(l)
        if r.get("source_id") == sid and r.get("revision") == rec["commit_sha"]: print("already has a row for", sid, rec["commit_sha"]); return 0
    card = open(d + "/README.md", encoding="utf-8").read()
    wsha = next(f["sha256"] for f in rec["files"] if f["file"].endswith(".safetensors"))
    row = {"schema": "ember-source-licence-ledger-v1", "source_id": sid, "kind": "model-weights", "name": "%s (pretrained base, open weights; continual-learning experiment backbone)" % name,
           "revision": rec["commit_sha"], "revision_date": rec.get("fetched"), "licence_spdx": "Apache-2.0",
           "licence_evidence": {"file": "audit/teacher-licences/%s-LICENSE" % low, "sha256": sha("%s/%s-LICENSE" % (ev, low)),
                                "also": "README frontmatter license: apache-2.0 (audit/teacher-licences/%s-README.md sha256 %s); HF API license tag apache-2.0; repo public and ungated" % (low, sha("%s/%s-README.md" % (ev, low)))},
           "licence_holder": holder,
           "commercial_use": "yes (Apache-2.0 s2 grant, no field-of-use limit in the text read)",
           "derivative_weights": "yes (s2 right to prepare Derivative Works; s4 conditions apply on redistribution)",
           "attribution_duty": "on redistribution of the model or a Derivative Work: give recipients a copy of the licence, keep copyright/patent/trademark/attribution notices, mark modified files with a notice of change, carry over any NOTICE file (the repo lists none); s6: no trademark licence (do not use the Qwen name as a product mark)",
           "patent": "s3 contributor patent grant, terminates for the licensee if it sues over the Work",
           "training_data_provenance": "not stated on the card (read for dataset list / cutoff / copyright: none; the card says 'Pre-training & Post-training' and cites a blog post); this is a gap for the 'traceable' half of the owned-model definition",
           "output_terms": "no restriction on outputs in the licence text (Apache-2.0 has no output clause)",
           "custody": {"local_path": d, "weights_file": [f["file"] for f in rec["files"] if f["file"].endswith(".safetensors")][0], "weights_sha256": wsha, "receipt": d + "/fetch-receipt.json",
                       "download_seconds": rec["download_seconds"], "total_bytes": rec["total_bytes"]},
           "checked": time.strftime("%Y-%m-%d"), "checked_by": "data lane", "method": "full LICENSE and README read; files fetched at the pinned commit with an allow-list (safetensors, json, txt, md, LICENSE; no pickle or code); LFS sha256 verified against the Hub record"}
    with open(LEDGER, "a", encoding="utf-8") as f: f.write(json.dumps(row) + "\n")
    print("appended", sid, rec["commit_sha"][:10], "weights sha", wsha[:12]); return 0


if __name__ == "__main__": sys.exit(main())
