# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Read-only index of the three HF dataset repos for the deleter audit (lead 82450): one jsonl row per file (repo, path, size, lfs sha256 or None). Lists the server tree only; downloads, writes and deletes nothing on the Hub.
Usage: python scripts/audit_hf_index.py [--out PATH]   (default <m-root>/avir/<data>/state/audit-82450/hf-index.jsonl, written to a temp file and renamed when complete)"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_RAW_REPO, HF_TRAIN_REPO, M_ROOT, SEAT_DATA
import os, sys, json, time
REPOS = ["wordingone/ember-corpus", ("wordingone/" + HF_RAW_REPO), ("wordingone/" + HF_TRAIN_REPO)]


def main(argv=None):
    from huggingface_hub import HfApi
    argv = sys.argv[1:] if argv is None else argv
    out = argv[argv.index("--out") + 1] if "--out" in argv else (M_ROOT + "/avir/" + SEAT_DATA + "/state/audit-82450/hf-index.jsonl")
    os.makedirs(os.path.dirname(out), exist_ok=True); tmp = out + ".part"; api = HfApi(); n = 0; t0 = time.time()
    with open(tmp, "w", encoding="utf-8") as f:
        for repo in REPOS:
            k = 0
            for t in api.list_repo_tree(repo, repo_type="dataset", recursive=True, expand=True):
                if not hasattr(t, "size"): continue
                l = getattr(t, "lfs", None); sha = (l.get("sha256") if isinstance(l, dict) else getattr(l, "sha256", None)) if l else None
                f.write(json.dumps(dict(repo=repo, path=t.path, size=t.size, sha256=sha)) + "\n"); k += 1
            print(repo, k, "files", round(time.time() - t0), "s", flush=True); n += k
    os.replace(tmp, out); print("DONE", n, "files ->", out)


if __name__ == "__main__":
    main()
