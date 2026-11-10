# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Backfill the exact HF dataset revision for packs whose origin names a huggingface.co dataset without a hash (rule 2). For each repo: latest commit at or before the pack fetch_date (+1 day) via list_repo_commits;
writes sidecar logs/revision-backfill-20261109.json {pack: {repo, fetch_date, revision, commit_date, current_head}}. Read-only API calls (tiny); no pack file is modified."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import json, re, datetime
from huggingface_hub import HfApi
D = json.load(open((LANE_ROOT + "/logs/licence-audit-20261109.json"))); api = HfApi(); out = {}
for n, r in D.items():
    o = " ".join(r["origin"]); m = re.search(r"huggingface\.co/datasets/([\w.-]+/[\w.-]+)", o)
    if not m or r["version_hash"]: continue
    repo = m.group(1); fd = r["fetch_dates"][0].split("..")[-1][:10]; lim = datetime.datetime.fromisoformat(fd).replace(tzinfo=datetime.timezone.utc) + datetime.timedelta(days=1)
    cs = api.list_repo_commits(repo, repo_type="dataset"); pick = next((c for c in cs if c.created_at <= lim), cs[-1])
    out[n] = dict(repo=repo, fetch_date=fd, revision=pick.commit_id, commit_date=pick.created_at.isoformat(), current_head=cs[0].commit_id, head_moved=cs[0].commit_id != pick.commit_id)
    print(n, repo, pick.commit_id[:10], pick.created_at.date(), "head_moved" if out[n]["head_moved"] else "head==pick")
json.dump(out, open((LANE_ROOT + "/logs/revision-backfill-20261109.json"), "w"), indent=1)
