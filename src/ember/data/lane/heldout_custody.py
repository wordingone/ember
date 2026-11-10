# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#1947 heldout custody manifest (read-only): sha256 / size / entry count / mtime of every heldout index the scrub + overlap gates use, plus whether a copy exists in the private HF repos.
Out: logs/heldout-custody-20261109.json + data/state/heldout-custody-20261109.md. Detects silent drift: rerun and diff against the committed sha."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_RAW_REPO, HF_TRAIN_REPO, LANE_ROOT, M_ROOT, SEAT_DATA
import os, sys, json, hashlib, time
import numpy as np
F = {"s4": (LANE_ROOT + "/heldout-index/heldout-sent-xxh64-s4.npy"), "full": (LANE_ROOT + "/heldout-index-full/heldout-sent-xxh64-full.npy"),
     "wiki2M": (LANE_ROOT + "/heldout-index/wiki-heldout-2M.npy"), "arxiv_pdf": (LANE_ROOT + "/arxiv/heldout-pdf-sent-hashes.npy"),
     "arxiv_excluded_ids": (LANE_ROOT + "/arxiv/heldout-excluded-ids.json")}
def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 24), b""):
            h.update(c)
    return h.hexdigest()
out = {}
for k, p in F.items():
    if not os.path.exists(p): out[k] = dict(path=p, missing=True); continue
    r = dict(path=p, bytes=os.path.getsize(p), mtime=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(os.path.getmtime(p))), sha256=sha(p))
    if p.endswith(".npy"):
        a = np.load(p, mmap_mode="r"); r.update(entries=int(a.shape[0]), dtype=str(a.dtype), sorted=bool(a.shape[0] < 2 or bool((a[:1000000][1:] >= a[:1000000][:-1]).all())), dup_in_first_1M=int(len(a[:1000000]) - len(np.unique(a[:1000000]))))
    out[k] = r
try:
    from huggingface_hub import HfApi
    api = HfApi(); names = {os.path.basename(v["path"]): v for v in out.values() if not v.get("missing")}
    for repo in (("wordingone/" + HF_RAW_REPO), ("wordingone/" + HF_TRAIN_REPO)):
        try:
            fs = {os.path.basename(x): x for x in api.list_repo_files(repo, repo_type="dataset")}
            for n, v in names.items():
                if n in fs: v.setdefault("on_hf", []).append(repo + ":" + fs[n])
        except Exception as e:
            out["_hf_error_" + repo] = str(e)[:120]
except Exception as e:
    out["_hf_error"] = str(e)[:120]
json.dump(out, open((LANE_ROOT + "/logs/heldout-custody-20261109.json"), "w"), indent=1)
with open((M_ROOT + "/avir/" + SEAT_DATA + "/state/heldout-custody-20261109.md"), "w", encoding="utf-8") as f:
    f.write("# Heldout custody 2026-11-09 (#1947)\n\n| index | bytes | entries | sha256 | on HF |\n|---|---|---|---|---|\n")
    for k, v in out.items():
        if isinstance(v, dict) and not v.get("missing"): f.write("| %s | %d | %s | %s | %s |\n" % (k, v["bytes"], v.get("entries", "-"), v["sha256"][:16], ", ".join(v.get("on_hf", [])) or "NO"))
        elif isinstance(v, dict): f.write("| %s | MISSING | | | |\n" % k)
print({k: (v.get("entries"), v.get("on_hf"), v.get("missing")) for k, v in out.items() if isinstance(v, dict)})
