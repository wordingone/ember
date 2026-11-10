# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Supersession manifest (lead 81767): declare each original wikipedia pack -> its redacted -r1 twin in wordingone/ember-train-private. NO deletes; originals stay (H41 and other ledgers bind their shard shas).
A pair is declared only when the -r1 pack is fully on HF (text/<name>-r1/intake.json present). Each run writes ONE NEW file (supersession.jsonl, then supersession-2.jsonl, ...) holding only
pairs not already declared in an existing supersession*.jsonl (never overwrites an HF file). hf_inventory.py reads supersession*.jsonl: unique totals count only the -r1 side, declared pairs go on a
'superseded (kept for provenance)' line and are NOT overlap; undeclared duplicates stay a failure. Rows carry shas, no text."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import sys as _hs; _hs.path.insert(0, (LANE_ROOT + "/scripts")); import hf_push   # lead 82104: one funnel for HF writes
import os, sys, json, re, time
from huggingface_hub import HfApi
REPO = "wordingone/ember-train-private"; from lane_config import LANE_ROOT as ROOT; api = HfApi()
files = [t.path for t in api.list_repo_tree(REPO, repo_type="dataset", recursive=True) if hasattr(t, "size")]
declared = set(); existing = []
for p in files:
    if re.fullmatch(r"supersession(-\d+)?\.jsonl", p):
        existing.append(p)
        from huggingface_hub import hf_hub_download
        for l in open(hf_hub_download(REPO, p, repo_type="dataset", force_download=True), encoding="utf-8"):
            if l.strip():
                _r = json.loads(l)
                if _r.get("kind") != "article_exclusion": declared.add(_r["r1_pack"])
on_hf = {p.split("/")[1] for p in files if p.startswith("text/") and p.endswith("/intake.json")}
rows = []
for name in sorted(on_hf):
    if not name.endswith("-r1") or name in declared: continue
    old = name[:-3]
    if old not in on_hf: continue          # the original must be on HF too, else there is nothing to supersede
    a = json.load(open(f"{ROOT}/packed/{old}/intake.json")); b = json.load(open(f"{ROOT}/packed/{name}/intake.json"))
    mp = f"{ROOT}/logs/repack-r1/{old}.manifest.json"; m = json.load(open(mp)) if os.path.exists(mp) else {}
    rows.append(dict(original_pack=old, original_hf_prefix=f"text/{old}/", original_dataset_id=a["dataset_id"], original_docs=a["docs"], original_content_tokens=a["content_tokens"], original_shards=a["shards"],
                     original_ledger_sha256=a["ledger_sha256"], original_docs_index_sha256=a["docs_index_sha256"], original_source_manifest_sha256=a["source_manifest_sha256"],
                     r1_pack=name, r1_hf_prefix=f"text/{name}/", r1_dataset_id=b["dataset_id"], r1_docs=b["docs"], r1_content_tokens=b["content_tokens"], r1_shards=b["shards"],
                     r1_ledger_sha256=b["ledger_sha256"], r1_docs_index_sha256=b["docs_index_sha256"], r1_source_manifest_sha256=b["source_manifest_sha256"],
                     shards_changed=m.get("shards_changed"), reason="credential-shaped spans replaced by <REDACTED_CREDENTIAL> (lead 81713); same documents, redacted text; re-tokenized",
                     kept_original_for="provenance (H41 and other ledgers bind the original shard shas); no deletes", count_policy="count the -r1 side once; the original is superseded, not overlap",
                     declared=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
if not rows: print("nothing new to declare"); sys.exit(0)
n = len(existing) + 1; dest = "supersession.jsonl" if n == 1 else f"supersession-{n}.jsonl"
loc = f"{ROOT}/audit/{dest}"; open(loc, "w", encoding="utf-8").write("".join(json.dumps(r) + "\n" for r in rows))
assert dest not in files
hf_push.upload_file(api, path_or_fileobj=loc, path_in_repo=dest, repo_id=REPO, repo_type="dataset", commit_message=f"supersession manifest {n}: {len(rows)} original->-r1 pair(s) (lead 81767), no deletes")
print("UPLOADED", dest, [r["r1_pack"] for r in rows])
