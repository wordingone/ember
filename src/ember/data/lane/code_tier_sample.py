# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""training 81999 blocking measurement: code-tier admit share using the REAL prep functions on range-read samples (6 spread shards x first 3 MB). Out logs/code-tier-sample-20261109.json"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import sys, zlib, json, requests, collections
sys.argv = ["text_lane.py", "stackv2_edu"]; pass
import importlib; T = importlib.import_module("text_lane")
from huggingface_hub import hf_hub_url, get_token, HfApi
H = {"Authorization": "Bearer " + (get_token() or "")}; api = HfApi(); res = {}
for repo, fn in [("stackv2_edu_filtered", T.prep_stackv2_edu), ("github_archive_filtered", T.prep_github_archive)]:
    fs = sorted(t.path for t in api.list_repo_tree("common-pile/" + repo, repo_type="dataset") if t.path.endswith(".json.gz"))
    pick = [fs[i] for i in range(0, len(fs), max(1, len(fs) // 6))][:6]
    st = collections.Counter(); n = kept = 0; chars_in = chars_kept = 0
    for f in pick:
        b = requests.get(hf_hub_url("common-pile/" + repo, f, repo_type="dataset"), headers=dict(H, Range="bytes=0-3000000"), timeout=90).content
        for l in zlib.decompressobj(31).decompress(b).decode("utf-8", "ignore").split("\n")[:-1]:
            try: o = json.loads(l)
            except Exception: continue
            n += 1; chars_in += len(o.get("text", "")); x = fn(o, st)
            if x: kept += 1; chars_kept += len(x["text"])
    res[repo] = dict(shards=len(fs), sampled_docs=n, kept_docs=kept, kept_doc_share=round(kept / n, 4), kept_char_share=round(chars_kept / max(1, chars_in), 4), drops=dict(st))
    print(repo, res[repo], flush=True)
json.dump(res, open((LANE_ROOT + "/logs/code-tier-sample-20261109.json"), "w"), indent=1)
