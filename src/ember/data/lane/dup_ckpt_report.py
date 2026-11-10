# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""lead 82182 (3): find objects present in BOTH wordingone/ember-corpus (public) and wordingone/ember-raw-private by LFS sha256 (server-side, read only). Writes logs/dup-ckpt-20261109.json.
Zero overlap is operator's rule. This script NEVER deletes; the proposal needs lead's manifest approval first."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import json, sys, time
from huggingface_hub import HfApi
api = HfApi(); A = "wordingone/ember-corpus"; B = "wordingone/ember-raw-private"
def idx(repo):
    out = {}
    for e in api.list_repo_tree(repo, recursive=True, expand=True, repo_type="dataset"):
        if e.__class__.__name__ == "RepoFile" and e.lfs:
            sh = e.lfs["sha256"] if isinstance(e.lfs, dict) else e.lfs.sha256
            out.setdefault(sh, []).append((e.path, e.size))
    return out
a = idx(A); b = idx(B); both = sorted(set(a) & set(b))
rows = [dict(sha256=s, size=a[s][0][1], corpus_paths=[p for p, _ in a[s]], raw_paths=[p for p, _ in b[s]], size_equal=all(x[1] == a[s][0][1] for x in a[s] + b[s])) for s in both]
ck = [r for r in rows if "checkpoint" in " ".join(r["corpus_paths"] + r["raw_paths"]).lower() or r["sha256"] and any(p.endswith(".pt") for p in r["corpus_paths"] + r["raw_paths"])]
json.dump(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), corpus_unique_sha=len(a), raw_unique_sha=len(b), shared=len(rows), shared_checkpoint_like=len(ck), bytes_checkpoint_like=sum(r["size"] for r in ck), bytes_shared=sum(r["size"] for r in rows), rows=rows), open((LANE_ROOT + "/logs/dup-ckpt-20261109.json"), "w"), indent=1)
print(f"corpus {len(a)} sha, raw {len(b)} sha; shared {len(rows)} ({sum(r['size'] for r in rows)/2**30:.2f} GiB); checkpoint-like {len(ck)} ({sum(r['size'] for r in ck)/2**30:.2f} GiB)")
for r in ck[:4]: print(r["corpus_paths"], "|", r["raw_paths"][:2], r["size"])
