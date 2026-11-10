# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Declare the H19-overlap exclusion (lead 81829) as supersession-3.jsonl in ember-train-private + the exclusion id list under exclusions/. NO deletes, no pack edits, never overwrites an HF file.
Rows are kind=article_exclusion (one per pack): hf_inventory subtracts them from the unique train-ready text count; admission applies them at ledger time."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import sys as _hs; _hs.path.insert(0, (LANE_ROOT + "/scripts")); import hf_push   # lead 82104: one funnel for HF writes
import json, hashlib, time, collections
from huggingface_hub import HfApi
REPO = "wordingone/ember-train-private"; api = HfApi(); from lane_config import LANE_ROOT as ROOT
LIST = ROOT + "/audit/h19-overlap-exclude-proposal.jsonl"; LREMOTE = "exclusions/h19-overlap-exclude-20261108.jsonl"
sha = hashlib.sha256(open(LIST, "rb").read()).hexdigest(); assert sha.startswith("3afb3eb3"), sha
agg = collections.defaultdict(lambda: collections.Counter())
for l in open(LIST, encoding="utf-8"):
    d = json.loads(l); a = agg[d["pack"]]; a["articles"] += 1; a["tokens"] += d["tokens"]; a[d["cls"] + "_articles"] += 1; a[d["cls"] + "_tokens"] += d["tokens"]
rows = []
for pk, a in sorted(agg.items()):
    rows.append(dict(kind="article_exclusion", pack=pk, hf_prefix=f"text/{pk}/", exclusion_file=LREMOTE, exclusion_file_sha256=sha, exclusion_key="pack + id (page id) -> docs-index object_index/token span",
                     articles=a["articles"], tokens=a["tokens"], same_revision_articles=a["same_revision_articles"], same_revision_tokens=a["same_revision_tokens"], later_revision_articles=a["later_revision_articles"], later_revision_tokens=a["later_revision_tokens"],
                     reason="page ids already trained in H19 (structured-wikipedia projections, objects 0d544e19/1983e863/a6ac037d/3bc93f29); same or later revision; near-duplicate is not new data",
                     authority="lead 81829 (conservative ruling: exclude all, same and later revision)", count_policy="subtract from the unique train-ready text count; apply at ledger/admission time", no_deletes=True, declared=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
out = ROOT + "/audit/supersession-3.jsonl"; open(out, "w", encoding="utf-8").write("".join(json.dumps(r) + "\n" for r in rows))
files = {t.path for t in api.list_repo_tree(REPO, repo_type="dataset", recursive=True) if hasattr(t, "size")}
assert "supersession-3.jsonl" not in files and LREMOTE not in files
hf_push.upload_file(api, path_or_fileobj=LIST, path_in_repo=LREMOTE, repo_id=REPO, repo_type="dataset", commit_message="H19-overlap exclusion id list (222,808 page ids; lead 81829), no deletes")
hf_push.upload_file(api, path_or_fileobj=out, path_in_repo="supersession-3.jsonl", repo_id=REPO, repo_type="dataset", commit_message="supersession-3: H19-overlap article exclusion, 12 packs (lead 81829), no deletes")
print("UPLOADED", len(rows), "rows;", sum(r["articles"] for r in rows), "articles;", sum(r["tokens"] for r in rows), "tokens")
