# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Declare a rescrub supersession (new file only, never overwrites): python supersession_r2.py SUPERSEDED_PACK NEW_PACK "reason".
Row schema = the existing supersession row (hf_inventory keys on original_hf_prefix; r1_pack field = the new pack so supersession.py's `declared` set stays correct) + kind-free; both packs must have intake.json on the train repo.
Example: supersession_r2.py wikipedia-20220501-p41243p151573-r1 wikipedia-20220501-p41243p151573-r2 "rescrub vs wiki-heldout-2M (44.2% docs had >=1 heldout sentence)"."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_TRAIN_REPO, LANE_ROOT
import sys as _hs; _hs.path.insert(0, (LANE_ROOT + "/scripts")); import hf_push   # lead 82104: one funnel for HF writes
import os, sys, json, re, time
from huggingface_hub import HfApi, hf_hub_download
REPO = ("wordingone/" + HF_TRAIN_REPO); from lane_config import LANE_ROOT as ROOT; api = HfApi()
old, new, reason = sys.argv[1], sys.argv[2], sys.argv[3]
files = [t.path for t in api.list_repo_tree(REPO, repo_type="dataset", recursive=True) if hasattr(t, "size")]
for n in (old, new):
    assert f"text/{n}/intake.json" in files, f"{n} not fully on HF (intake.json missing) - declare only after upload"
existing = [p for p in files if re.fullmatch(r"supersession(-\d+)?\.jsonl", p)]
a = json.load(open(f"{ROOT}/packed/{old}/intake.json")); b = json.load(open(f"{ROOT}/packed/{new}/intake.json"))
row = dict(original_pack=old, original_hf_prefix=f"text/{old}/", original_dataset_id=a["dataset_id"], original_docs=a["docs"], original_content_tokens=a["content_tokens"], original_shards=a["shards"],
           original_ledger_sha256=a["ledger_sha256"], original_docs_index_sha256=a["docs_index_sha256"], original_source_manifest_sha256=a["source_manifest_sha256"],
           r1_pack=new, r1_hf_prefix=f"text/{new}/", r1_dataset_id=b["dataset_id"], r1_docs=b["docs"], r1_content_tokens=b["content_tokens"], r1_shards=b["shards"],
           r1_ledger_sha256=b["ledger_sha256"], r1_docs_index_sha256=b["docs_index_sha256"], r1_source_manifest_sha256=b["source_manifest_sha256"], reason=reason,
           kept_original_for="provenance (ledgers may bind the shard shas); no deletes", count_policy="count the new side once; the superseded pack is not overlap", declared=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
n = len(existing) + 1; dest = "supersession.jsonl" if n == 1 else f"supersession-{n}.jsonl"; assert dest not in files
loc = f"{ROOT}/audit/{dest}"; open(loc, "w", encoding="utf-8").write(json.dumps(row) + "\n")
if "--dry" in sys.argv: print("DRY", dest, row["original_pack"], "->", row["r1_pack"]); sys.exit(0)
hf_push.upload_file(api, path_or_fileobj=loc, path_in_repo=dest, repo_id=REPO, repo_type="dataset", commit_message=f"supersession manifest {n}: {old} -> {new} (rescrub, lead 82002), no deletes")
print("UPLOADED", dest)
